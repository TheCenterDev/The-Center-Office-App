#!/usr/bin/env python3
"""Publishes firestore.rules to the live database.

Talks to the Firebase Rules API directly rather than going through the
Firebase CLI. The CLI does the same job, but first calls
serviceusage.googleapis.com to check whether the Firestore API is
enabled -- and a Firebase Admin SDK service account isn't permitted to
read that, so `firebase deploy` fails with:

    HTTP Error: 403, Permission denied to get service
    [firestore.googleapis.com]

before it ever gets near the rules. The check is pointless here: the
Firestore API is obviously enabled, the app has been using it for
months. Granting the key serviceusage rights purely to satisfy a
pre-flight check would be widening a credential to work around a
question we already know the answer to.

This does the two steps the CLI would have done:

  1. Create a ruleset from the file. This is also where syntax errors
     are caught -- the API refuses to create a ruleset that doesn't
     compile, and reports the line and column.
  2. Point the "cloud.firestore" release at that ruleset, which is the
     moment the new rules take effect.

Needs GOOGLE_APPLICATION_CREDENTIALS pointing at a service account key.

Usage:
    python3 scripts/publish_rules.py [--project ID] [--check-only]

--check-only compiles the rules and reports problems without publishing.
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

API = "https://firebaserules.googleapis.com/v1"
DEFAULT_PROJECT = "the-center-office-app"
RULES_FILE = Path(__file__).resolve().parent.parent / "firestore.rules"

# The release name Firestore reads its rules from. Firebase Storage uses
# "firebase.storage/<bucket>"; this project has no Storage rules.
RELEASE = "cloud.firestore"


def access_token() -> str:
    try:
        from google.oauth2 import service_account
        from google.auth.transport.requests import Request
    except ImportError:
        sys.exit(
            "google-auth isn't installed.\n"
            "  pip install google-auth --break-system-packages"
        )
    import os

    key_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
    if not key_path or not Path(key_path).is_file():
        sys.exit(
            "GOOGLE_APPLICATION_CREDENTIALS isn't set, or doesn't point at a "
            "readable service account key file."
        )
    credentials = service_account.Credentials.from_service_account_file(
        key_path, scopes=["https://www.googleapis.com/auth/cloud-platform"]
    )
    credentials.refresh(Request())
    return credentials.token


def call(method: str, url: str, token: str, payload=None):
    body = json.dumps(payload).encode() if payload is not None else None
    request = urllib.request.Request(url, data=body, method=method)
    request.add_header("Authorization", "Bearer " + token)
    request.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return response.status, json.loads(response.read().decode() or "{}")
    except urllib.error.HTTPError as error:
        raw = error.read().decode(errors="replace")
        try:
            return error.code, json.loads(raw)
        except ValueError:
            return error.code, {"raw": raw}


def explain(status: int, body: dict) -> str:
    """Turns an API error into something that names the fix."""
    message = (body.get("error") or {}).get("message", "") or body.get("raw", "")
    if status == 403:
        return (
            f"Permission denied.\n  {message}\n\n"
            "  The service account needs to publish rules. In the Google Cloud\n"
            "  console -> IAM, find the service account and add the role\n"
            "  'Firebase Rules Admin' (roles/firebaserules.admin)."
        )
    if status == 404:
        return (
            f"Not found.\n  {message}\n\n"
            "  Check the project id is right, and that this key belongs to it."
        )
    return f"HTTP {status}\n  {message or json.dumps(body)[:500]}"


def report_compile_errors(body: dict) -> None:
    """The API returns each problem with a line and column; print them in
    a form you can act on rather than a wall of JSON."""
    issues = []
    for detail in (body.get("error") or {}).get("details", []):
        issues.extend(detail.get("issues", []) or [])
    if not issues:
        return
    print("\nfirestore.rules doesn't compile:\n", file=sys.stderr)
    for issue in issues:
        where = issue.get("sourcePosition", {})
        print(
            f"  line {where.get('line', '?')}, column {where.get('column', '?')}: "
            f"{issue.get('description', '')}",
            file=sys.stderr,
        )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", default=DEFAULT_PROJECT)
    parser.add_argument("--check-only", action="store_true")
    args = parser.parse_args()

    if not RULES_FILE.is_file():
        sys.exit(f"{RULES_FILE} doesn't exist.")
    source = RULES_FILE.read_text(encoding="utf-8")
    print(f"Read {RULES_FILE.name} ({len(source)} bytes)")

    token = access_token()
    project = args.project

    # 1. Create the ruleset. Also the compile check.
    status, body = call(
        "POST",
        f"{API}/projects/{project}/rulesets",
        token,
        {"source": {"files": [{"name": "firestore.rules", "content": source}]}},
    )
    if status not in (200, 201):
        report_compile_errors(body)
        print("\n" + explain(status, body), file=sys.stderr)
        return 1

    ruleset = body.get("name", "")
    print(f"Rules compiled cleanly. Ruleset: {ruleset.rsplit('/', 1)[-1]}")

    if args.check_only:
        print("--check-only, so not publishing.")
        return 0

    # 2. Point the release at it. The release already exists in any
    # project that has ever had rules, so create-then-update rather than
    # assuming either.
    release_name = f"projects/{project}/releases/{RELEASE}"
    status, body = call(
        "POST",
        f"{API}/projects/{project}/releases",
        token,
        {"name": release_name, "rulesetName": ruleset},
    )
    if status == 409:  # already exists -- update it instead
        status, body = call(
            "PATCH",
            f"{API}/{release_name}",
            token,
            {"release": {"name": release_name, "rulesetName": ruleset}},
        )
    if status not in (200, 201):
        print("\n" + explain(status, body), file=sys.stderr)
        return 1

    print(f"Published. {RELEASE} is now serving this ruleset.")
    print("Live immediately -- no app rebuild or redeploy needed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
