import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { useLocation, useNavigate } from "react-router-dom";

import { supabase } from "../lib/supabase";
import { queryClient } from "./query-client";

interface AuthContextValue {
  isAuthenticated: boolean;
  isLoading: boolean;
  signOut: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<Awaited<ReturnType<typeof supabase.auth.getSession>>["data"]["session"]>(null);
  const [isLoading, setIsLoading] = useState(true);
  const navigate = useNavigate();
  const location = useLocation();

  useEffect(() => {
    let active = true;
    void supabase.auth.getSession().then(({ data }) => {
      if (!active) return;
      setSession(data.session);
      setIsLoading(false);
    });
    const { data: { subscription } } = supabase.auth.onAuthStateChange((_event, nextSession) => {
      setSession(nextSession);
      setIsLoading(false);
    });
    return () => {
      active = false;
      subscription.unsubscribe();
    };
  }, []);

  const signOut = useCallback(async () => {
    try {
      await supabase.auth.signOut({ scope: "local" });
    } catch {
      // The local session is still cleared below if Supabase no longer knows it.
    } finally {
      setSession(null);
      queryClient.clear();
      navigate("/login", { replace: true });
    }
  }, [navigate]);

  useEffect(() => {
    async function handleUnauthorized() {
      const returnTo = `${location.pathname}${location.search}${location.hash}`;
      try {
        await supabase.auth.signOut({ scope: "local" });
      } catch {
        // Continue clearing the local session after an expired or missing remote session.
      } finally {
        setSession(null);
        queryClient.clear();
        if (location.pathname !== "/login") {
          navigate(`/login?next=${encodeURIComponent(returnTo)}`, { replace: true });
        }
      }
    }
    window.addEventListener("finpilot:unauthorized", handleUnauthorized);
    return () => window.removeEventListener("finpilot:unauthorized", handleUnauthorized);
  }, [location.hash, location.pathname, location.search, navigate]);

  const value = useMemo(
    () => ({ isAuthenticated: session !== null, isLoading, signOut }),
    [isLoading, session, signOut],
  );
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext);
  if (!context) throw new Error("useAuth must be used within AuthProvider.");
  return context;
}
