import { useCallback, useEffect, useState } from "react";
import { ApolloError, useApolloClient } from "@apollo/client";
import { LOGIN, ME } from "../graphql";
import { TOKEN_KEY, readToken, wsClient } from "../apollo";
import type { User } from "../types";

function storeToken(token: string | null) {
  try {
    if (token) localStorage.setItem(TOKEN_KEY, token);
    else localStorage.removeItem(TOKEN_KEY);
  } catch {
    /* storage unavailable: session lasts for this page view only */
  }
  wsClient.terminate(); // next subscription reconnects with the new identity
}

export function useAuth() {
  const client = useApolloClient();
  const [user, setUser] = useState<User | null>(null);
  const [checking, setChecking] = useState(Boolean(readToken()));

  // Validate a stored token on load (expired/invalid -> signed out)
  useEffect(() => {
    if (!readToken()) return;
    client
      .query({ query: ME })
      .then(({ data }) => {
        if (data?.me) setUser(data.me);
        else storeToken(null);
      })
      .catch(() => storeToken(null))
      .finally(() => setChecking(false));
  }, [client]);

  const login = useCallback(
    async (email: string, password: string): Promise<string | null> => {
      try {
        const { data } = await client.mutate({ mutation: LOGIN, variables: { email, password } });
        storeToken(data!.login.token);
        setUser(data!.login.user);
        return null;
      } catch (err) {
        const gqlError = err instanceof ApolloError ? err.graphQLErrors[0] : undefined;
        return gqlError?.message ?? "Sign-in failed. Please try again.";
      }
    },
    [client],
  );

  const logout = useCallback(() => {
    storeToken(null);
    setUser(null);
  }, []);

  return { user, checking, login, logout };
}
