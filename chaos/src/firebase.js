import { initializeApp } from 'firebase/app';
import { 
  getAuth, 
  createUserWithEmailAndPassword, 
  signInWithEmailAndPassword, 
  signOut, 
  sendPasswordResetEmail, 
  updateProfile
} from 'firebase/auth';
import { 
  getFirestore, 
  doc, 
  setDoc, 
  getDoc, 
  serverTimestamp 
} from 'firebase/firestore';

const firebaseConfig = {
  apiKey: import.meta.env.VITE_FIREBASE_API_KEY,
  authDomain: import.meta.env.VITE_FIREBASE_AUTH_DOMAIN,
  projectId: import.meta.env.VITE_FIREBASE_PROJECT_ID,
  storageBucket: import.meta.env.VITE_FIREBASE_STORAGE_BUCKET,
  messagingSenderId: import.meta.env.VITE_FIREBASE_MESSAGING_SENDER_ID,
  appId: import.meta.env.VITE_FIREBASE_APP_ID,
  measurementId: import.meta.env.VITE_FIREBASE_MEASUREMENT_ID,
};

const requiredFirebaseKeys = ['apiKey','authDomain','projectId','storageBucket','messagingSenderId','appId'];
const missingFirebaseKeys = requiredFirebaseKeys.filter((key) => !firebaseConfig[key]);
if (missingFirebaseKeys.length) {
  console.warn(`Firebase is not configured. Missing VITE_FIREBASE_* values: ${missingFirebaseKeys.join(', ')}`);
}

// Initialize Firebase only when the complete web configuration is present.
// This keeps the local/offline backend usable while making cloud auth explicit.
export const firebaseConfigured = missingFirebaseKeys.length === 0;
let app = null;
export let auth = null;
export let db = null;
if (firebaseConfigured) {
  app = initializeApp(firebaseConfig);
  auth = getAuth(app);
  db = getFirestore(app);
}

/**
 * Timeout wrapper for Firestore operations so slow or unconfigured databases
 * never freeze or hang the user authentication flow
 */
function withTimeout(promise, ms = 2000, fallback = null) {
  return Promise.race([
    promise,
    new Promise((resolve) => setTimeout(() => resolve(fallback), ms))
  ]);
}

/**
 * Register a new user with email and password, update profile, and persist to Firestore
 */
export async function registerUser(name, email, password) {
  if (!firebaseConfigured) throw new Error("Firebase is not configured. Copy chaos/.env.example to chaos/.env and add your Firebase Web App settings.");
  const userCredential = await createUserWithEmailAndPassword(auth, email, password);
  const user = userCredential.user;

  // Update display name in Firebase Auth
  if (name) {
    try {
      await updateProfile(user, { displayName: name });
    } catch (profileErr) {
      console.warn('Failed to update display name in auth:', profileErr);
    }
  }

  // Create user record in Firestore database and localStorage
  const userData = {
    uid: user.uid,
    displayName: name || user.email.split('@')[0],
    email: user.email,
    role: 'Chaos Engineer'
  };

  try {
    localStorage.setItem(`cd_set_user_${user.uid}`, JSON.stringify(userData));
  } catch (e) {
    // Ignore storage issues
  }

  // Non-blocking background Firestore write with timeout so UI never hangs
  withTimeout(
    setDoc(doc(db, 'users', user.uid), {
      ...userData,
      createdAt: serverTimestamp(),
      lastLogin: serverTimestamp(),
    }),
    2000
  ).catch((dbErr) => {
    console.warn('Firestore user profile write notice (auth succeeded):', dbErr?.message);
  });

  return user;
}

/**
 * Sign in existing user with email and password, and update lastLogin
 */
export async function loginUser(email, password) {
  if (!firebaseConfigured) throw new Error("Firebase is not configured. Add your Firebase Web App settings to the frontend environment.");
  const userCredential = await signInWithEmailAndPassword(auth, email, password);
  const user = userCredential.user;

  // Non-blocking background lastLogin update
  withTimeout(
    setDoc(
      doc(db, 'users', user.uid),
      { lastLogin: serverTimestamp() },
      { merge: true }
    ),
    2000
  ).catch((dbErr) => {
    console.warn('Firestore update lastLogin notice:', dbErr?.message);
  });

  return user;
}

/**
 * Send password reset email
 */
export async function resetPassword(email) {
  if (!firebaseConfigured) throw new Error("Firebase is not configured.");
  return await sendPasswordResetEmail(auth, email);
}

/**
 * Sign out current user
 */
export async function logoutUser() {
  if (!firebaseConfigured) return;
  return await signOut(auth);
}

/**
 * Fetch user document profile from local cache or Firestore with timeout
 */
export async function getUserProfile(uid) {
  if (!firebaseConfigured || !db) return null;
  // Check local cache first for instant response
  try {
    const cached = localStorage.getItem(`cd_set_user_${uid}`);
    if (cached) {
      return JSON.parse(cached);
    }
  } catch (e) {}

  try {
    const userDoc = await withTimeout(getDoc(doc(db, 'users', uid)), 2000, null);
    if (userDoc && userDoc.exists()) {
      const data = userDoc.data();
      try {
        localStorage.setItem(`cd_set_user_${uid}`, JSON.stringify(data));
      } catch (e) {}
      return data;
    }
  } catch (err) {
    console.warn('Failed to retrieve user profile from Firestore:', err?.message);
  }
  return null;
}

/**
 * Clean human-readable error messages from Firebase Auth codes
 */
export function getAuthErrorMessage(errorCode) {
  switch (errorCode) {
    case 'auth/invalid-email':
      return 'The email address is not valid.';
    case 'auth/user-disabled':
      return 'This user account has been disabled.';
    case 'auth/user-not-found':
      return 'No account found with this email address.';
    case 'auth/wrong-password':
    case 'auth/invalid-credential':
      return 'Incorrect email or password. Please try again.';
    case 'auth/email-already-in-use':
      return 'An account with this email address already exists. Please log in instead.';
    case 'auth/weak-password':
      return 'Password should be at least 6 characters long.';
    case 'auth/too-many-requests':
      return 'Too many unsuccessful attempts. Please try again later.';
    case 'auth/network-request-failed':
      return 'Network connection issue. Please check your internet connection.';
    case 'auth/operation-not-allowed':
      return 'Email/password sign-in is not enabled in Firebase Console.';
    default:
      return 'Authentication failed. Please check your credentials and try again.';
  }
}

export default app;
