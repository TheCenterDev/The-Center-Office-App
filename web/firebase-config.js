/* Firebase project config for the mobile site's login + settings sync.
 *
 * This is NOT a secret -- Firebase API keys are meant to be public and
 * shipped in client-side code (unlike a server API key). The actual
 * security boundary is enforced by Firebase Authentication (who can
 * sign in) and the Firestore security rules (see firestore.rules at
 * the repo root, which must be pasted into the Firebase console once),
 * not by hiding this file. See:
 * https://firebase.google.com/docs/projects/api-keys
 */
window.FIREBASE_CONFIG = {
  apiKey: "AIzaSyB2rLNc8NaBcWzk_kCyhulEIseXeMbNZEg",
  authDomain: "the-center-office-app.firebaseapp.com",
  projectId: "the-center-office-app",
  storageBucket: "the-center-office-app.firebasestorage.app",
  messagingSenderId: "282726386673",
  appId: "1:282726386673:web:bdd0c91062a7ac2d0b9250",
  measurementId: "G-GFVPF8N6ZF",
};
