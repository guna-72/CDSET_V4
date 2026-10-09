import React, { createContext, useContext, useState, useEffect } from 'react';
import { onAuthStateChanged } from 'firebase/auth';
import { 
  auth, 
  loginUser, 
  registerUser, 
  logoutUser, 
  resetPassword, 
  getUserProfile,
  firebaseConfigured
} from '../firebase';

const AuthContext = createContext({});

export function AuthProvider({ children }) {
  const [currentUser, setCurrentUser] = useState(null);
  const [userProfile, setUserProfile] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!firebaseConfigured || !auth) {
      setLoading(false);
      return () => {};
    }
    const unsubscribe = onAuthStateChanged(auth, async (user) => {
      setCurrentUser(user);
      if (user) {
        // Immediate baseline profile to prevent any UI delay
        const baseProfile = {
          displayName: user.displayName || user.email?.split('@')[0] || 'Operator',
          email: user.email,
          role: 'Chaos Engineer'
        };
        setUserProfile(baseProfile);

        // Fetch persisted Firestore/cached profile asynchronously in background
        getUserProfile(user.uid).then((profile) => {
          if (profile) setUserProfile(profile);
        }).catch(() => {});
      } else {
        setUserProfile(null);
      }
      setLoading(false);
    });

    return unsubscribe;
  }, []);

  const login = async (email, password) => {
    const user = await loginUser(email, password);
    setCurrentUser(user);
    const profile = {
      displayName: user.displayName || user.email?.split('@')[0] || 'Operator',
      email: user.email,
      role: 'Chaos Engineer'
    };
    setUserProfile(profile);
    getUserProfile(user.uid).then((p) => { if (p) setUserProfile(p); }).catch(() => {});
    return user;
  };

  const register = async (name, email, password) => {
    const user = await registerUser(name, email, password);
    setCurrentUser(user);
    const profile = {
      displayName: name || user.email?.split('@')[0] || 'Operator',
      email: user.email,
      role: 'Chaos Engineer'
    };
    setUserProfile(profile);
    return user;
  };

  const logout = async () => {
    await logoutUser();
    setCurrentUser(null);
    setUserProfile(null);
  };

  const sendReset = async (email) => {
    return await resetPassword(email);
  };

  const value = {
    currentUser,
    userProfile,
    loading,
    login,
    register,
    logout,
    sendReset
  };

  return (
    <AuthContext.Provider value={value}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  return useContext(AuthContext);
}
