import { createContext, useContext, useEffect, useState, useCallback } from "react";
import { supabase } from "../services/supabase";
import api from "../services/api";

const AuthContext = createContext(null);

/**
 * Owns the Supabase session and the resulting employee profile (role,
 * name, department, etc. — fetched from the backend, never trusted from
 * anything client-side). Every page that needs to know "who is logged in"
 * or "what's their role" reads from here via useAuth(), rather than
 * re-deriving it.
 */
export function AuthProvider({ children }) {
  const [session, setSession] = useState(undefined); // undefined = not checked yet
  const [employee, setEmployee] = useState(null);
  const [profileError, setProfileError] = useState(null);
  const [loading, setLoading] = useState(true);

  const loadProfile = useCallback(async () => {
    try {
      const { data } = await api.post("/auth/profile");
      setEmployee(data);
      setProfileError(null);
    } catch (err) {
      setEmployee(null);
      setProfileError(
        err?.response?.data?.detail ||
          "We couldn't load your profile. Contact an administrator."
      );
    }
  }, []);

  useEffect(() => {
    let isMounted = true;

    supabase.auth.getSession().then(async ({ data }) => {
      if (!isMounted) return;
      setSession(data.session);
      if (data.session) {
        await loadProfile();
      }
      setLoading(false);
    });

    const { data: listener } = supabase.auth.onAuthStateChange(async (_event, newSession) => {
      if (!isMounted) return;
      setSession(newSession);
      if (newSession) {
        setLoading(true);
        await loadProfile();
        setLoading(false);
      } else {
        setEmployee(null);
        setProfileError(null);
      }
    });

    return () => {
      isMounted = false;
      listener?.subscription?.unsubscribe();
    };
  }, [loadProfile]);

  const login = useCallback(async (email, password) => {
    const { error } = await supabase.auth.signInWithPassword({ email, password });
    if (error) throw error;
  }, []);

  const logout = useCallback(async () => {
    await supabase.auth.signOut();
  }, []);

  const value = {
    session,
    employee,
    profileError,
    loading,
    isAuthenticated: !!session && !!employee,
    login,
    logout,
    refreshProfile: loadProfile,
  };

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}
