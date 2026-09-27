import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import { ApolloError, useApolloClient } from "@apollo/client";
import { LAB_TOKEN_KEY, readLabToken, wsClient } from "../apollo";
import { COMPLETE_LESSON, LAB_LOGIN, LAB_ME, LAB_PROGRESS, LAB_SIGNUP } from "../graphql";
import type { LabUser } from "../types";

interface LabAuth {
  user: LabUser | null;
  checking: boolean;
  completed: Set<string>;
  login: (email: string, password: string) => Promise<string | null>;
  signup: (fullName: string, email: string, password: string) => Promise<string | null>;
  logout: () => void;
  completeLesson: (lessonId: string) => Promise<boolean>;
}

const LabAuthContext = createContext<LabAuth | null>(null);

function storeToken(token: string | null) {
  try {
    if (token) localStorage.setItem(LAB_TOKEN_KEY, token);
    else localStorage.removeItem(LAB_TOKEN_KEY);
  } catch {
    /* storage unavailable: signed in for this page view only */
  }
  wsClient.terminate(); // the chat WebSocket reconnects with the new identity
}

function errorMessage(err: unknown): string {
  const gqlError = err instanceof ApolloError ? err.graphQLErrors[0] : undefined;
  return gqlError?.message ?? "Something went wrong. Please try again.";
}

export function LabAuthProvider({ children }: { children: ReactNode }) {
  const client = useApolloClient();
  const [user, setUser] = useState<LabUser | null>(null);
  const [checking, setChecking] = useState(Boolean(readLabToken()));
  const [completed, setCompleted] = useState<Set<string>>(new Set());

  const loadProgress = useCallback(async () => {
    const { data } = await client.query({ query: LAB_PROGRESS });
    setCompleted(new Set(data.labProgress.map((p: { lessonId: string }) => p.lessonId)));
  }, [client]);

  // A stored token is re-validated on load (expired, invalid or disabled -> signed out)
  useEffect(() => {
    if (!readLabToken()) return;
    client
      .query({ query: LAB_ME })
      .then(async ({ data }) => {
        if (data?.labMe) {
          setUser(data.labMe);
          await loadProgress();
        } else storeToken(null);
      })
      .catch(() => storeToken(null))
      .finally(() => setChecking(false));
  }, [client, loadProgress]);

  const finish = useCallback(
    async (payload: { token: string; user: LabUser }) => {
      storeToken(payload.token);
      setUser(payload.user);
      await loadProgress().catch(() => setCompleted(new Set()));
    },
    [loadProgress],
  );

  const login = useCallback(
    async (email: string, password: string) => {
      try {
        const { data } = await client.mutate({ mutation: LAB_LOGIN, variables: { email, password } });
        await finish(data!.labLogin);
        return null;
      } catch (err) {
        return errorMessage(err);
      }
    },
    [client, finish],
  );

  const signup = useCallback(
    async (fullName: string, email: string, password: string) => {
      try {
        const { data } = await client.mutate({ mutation: LAB_SIGNUP, variables: { input: { fullName, email, password } } });
        await finish(data!.labSignup);
        return null;
      } catch (err) {
        return errorMessage(err);
      }
    },
    [client, finish],
  );

  const logout = useCallback(() => {
    storeToken(null);
    setUser(null);
    setCompleted(new Set());
  }, []);

  const completeLesson = useCallback(
    async (lessonId: string) => {
      try {
        const { data } = await client.mutate({ mutation: COMPLETE_LESSON, variables: { lessonId } });
        setCompleted(new Set(data!.completeLesson.map((p: { lessonId: string }) => p.lessonId)));
        return true;
      } catch {
        return false;
      }
    },
    [client],
  );

  return (
    <LabAuthContext.Provider value={{ user, checking, completed, login, signup, logout, completeLesson }}>
      {children}
    </LabAuthContext.Provider>
  );
}

export function useLabAuth(): LabAuth {
  const ctx = useContext(LabAuthContext);
  if (!ctx) throw new Error("useLabAuth must be used inside <LabAuthProvider>");
  return ctx;
}
