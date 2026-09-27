import { ApolloClient, HttpLink, InMemoryCache, split } from "@apollo/client";
import { setContext } from "@apollo/client/link/context";
import { GraphQLWsLink } from "@apollo/client/link/subscriptions";
import { getMainDefinition } from "@apollo/client/utilities";
import { createClient } from "graphql-ws";

export const TOKEN_KEY = "shopbot.token"; // ShopBot demo customer (orders/returns lessons)
export const LAB_TOKEN_KEY = "lab.token"; // AI Testing Lab account
const GRAPHQL_PATH = import.meta.env.VITE_GRAPHQL_URL ?? "/graphql";

function read(key: string): string | null {
  try {
    return localStorage.getItem(key);
  } catch {
    return null;
  }
}

export const readToken = () => read(TOKEN_KEY);
export const readLabToken = () => read(LAB_TOKEN_KEY);

// Queries/mutations over HTTP with the JWT header
const authLink = setContext((_, { headers }) => {
  const token = readToken();
  const labToken = readLabToken();
  return {
    headers: {
      ...headers,
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(labToken ? { "X-Lab-Token": labToken } : {}),
    },
  };
});
const httpLink = authLink.concat(new HttpLink({ uri: GRAPHQL_PATH }));

// Subscriptions (token streaming) over WebSocket; browsers can't set WS headers, so the JWT
// travels in connectionParams. lazy + a fresh read of the token on every (re)connect.
const wsUrl = new URL(GRAPHQL_PATH, window.location.href);
wsUrl.protocol = wsUrl.protocol === "https:" ? "wss:" : "ws:";
export const wsClient = createClient({
  url: wsUrl.toString(),
  lazy: true,
  connectionParams: () => {
    const token = readToken();
    const labToken = readLabToken();
    return { ...(token ? { authorization: `Bearer ${token}` } : {}), ...(labToken ? { labToken } : {}) };
  },
});
const wsLink = new GraphQLWsLink(wsClient);

export const apolloClient = new ApolloClient({
  link: split(
    ({ query }) => {
      const def = getMainDefinition(query);
      return def.kind === "OperationDefinition" && def.operation === "subscription";
    },
    wsLink,
    httpLink,
  ),
  cache: new InMemoryCache(),
  defaultOptions: {
    query: { fetchPolicy: "no-cache" },
    mutate: { fetchPolicy: "no-cache" },
  },
});
