import { useCallback, useEffect, useState } from "react";
import { useApolloClient } from "@apollo/client";
import type { GraphQLFormattedError } from "graphql";
import { CLEAR_CONVERSATION, GET_CONVERSATION, SEND_MESSAGE_STREAM, SUBMIT_FEEDBACK } from "../graphql";
import type { ChatError, ChatMessage } from "../types";

const STORAGE_KEY = "shopbot.conversationId";

const FRIENDLY_ERRORS: Record<string, string> = {
  LLM_UNAVAILABLE: "ShopBot is temporarily unavailable. Please try again in a moment.",
  UPSTREAM_TIMEOUT: "ShopBot is taking too long to respond. Please try again.",
  UPSTREAM_UNAVAILABLE: "We can't reach ShopBot right now. Please try again shortly.",
  UPSTREAM_ERROR: "ShopBot hit an error. Please try again.",
  BAD_USER_INPUT: "That message couldn't be sent. Please check it and try again.",
  RATE_LIMITED: "You're sending messages too quickly. Please wait a minute and try again.",
  NETWORK_ERROR: "Network error. Check your connection and try again.",
};

function readStoredId(): string | null {
  try {
    return localStorage.getItem(STORAGE_KEY);
  } catch {
    return null;
  }
}

function storeId(id: string | null) {
  try {
    if (id) localStorage.setItem(STORAGE_KEY, id);
    else localStorage.removeItem(STORAGE_KEY);
  } catch {
    /* storage unavailable (private mode) - chat still works for this page view */
  }
}

function toChatError(code: string, message?: string): ChatError {
  return { code, message: FRIENDLY_ERRORS[code] ?? message ?? "Something went wrong. Please try again." };
}

function fromGraphQLErrors(errors: readonly GraphQLFormattedError[] | undefined): ChatError {
  const first = errors?.[0];
  return toChatError(String(first?.extensions?.code ?? "UNKNOWN"), first?.message);
}

export function useChat() {
  const client = useApolloClient();
  const [conversationId, setConversationId] = useState<string | null>(readStoredId);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [pending, setPending] = useState(false);
  const [restoring, setRestoring] = useState(Boolean(conversationId));
  const [error, setError] = useState<ChatError | null>(null);

  // Restore an existing conversation after a page reload
  useEffect(() => {
    const id = readStoredId();
    if (!id) return;
    client
      .query({ query: GET_CONVERSATION, variables: { id } })
      .then(({ data }) => {
        if (data?.conversation) setMessages(data.conversation.messages);
        else {
          storeId(null);
          setConversationId(null);
        }
      })
      .catch(() => setError({ code: "RESTORE_FAILED", message: "Couldn't load your previous chat." }))
      .finally(() => setRestoring(false));
  }, [client]);

  const send = useCallback(
    async (text: string, retryOf?: string) => {
      const trimmed = text.trim();
      if (!trimmed || pending) return;
      setError(null);
      setPending(true);

      const userId = retryOf ?? `local-${Date.now()}`;
      const botId = `stream-${userId}`;
      setMessages((prev) =>
        retryOf
          ? prev.map((m) => (m.id === retryOf ? { ...m, status: "sending" } : m))
          : [...prev, { id: userId, role: "user", content: trimmed, createdAt: new Date().toISOString(), status: "sending" }],
      );

      const fail = (err: ChatError) => {
        setError(err);
        setMessages((prev) =>
          prev.filter((m) => m.id !== botId).map((m) => (m.id === userId ? { ...m, status: "failed" } : m)),
        );
      };

      // Stream tokens into a temporary bubble; the final (guardrail-validated) reply replaces it
      await new Promise<void>((resolve) => {
        const subscription = client
          .subscribe({ query: SEND_MESSAGE_STREAM, variables: { input: { text: trimmed, conversationId } } })
          .subscribe({
            next: ({ data, errors }) => {
              if (errors?.length) return fail(fromGraphQLErrors(errors));
              const event = data?.sendMessageStream;
              if (!event) return;
              if (event.type === "token") {
                setMessages((prev) => {
                  const streaming = prev.find((m) => m.id === botId);
                  if (streaming) return prev.map((m) => (m.id === botId ? { ...m, content: m.content + event.token } : m));
                  return [...prev, { id: botId, role: "assistant", content: event.token, createdAt: new Date().toISOString(), status: "streaming" }];
                });
              } else if (event.type === "final") {
                const res = event.response;
                setConversationId(res.conversationId);
                storeId(res.conversationId);
                setMessages((prev) => [
                  ...prev.filter((m) => m.id !== botId).map((m) => (m.id === userId ? { ...m, status: undefined } : m)),
                  { ...res.message, debug: res.debug },
                ]);
              } else {
                fail(toChatError(event.errorCode, event.errorMessage));
              }
            },
            error: (err) => {
              fail(err?.graphQLErrors ? fromGraphQLErrors(err.graphQLErrors) : toChatError("NETWORK_ERROR"));
              resolve();
            },
            complete: () => {
              subscription.unsubscribe();
              resolve();
            },
          });
      });
      setPending(false);
    },
    [client, conversationId, pending],
  );

  const retry = useCallback((message: ChatMessage) => send(message.content, message.id), [send]);

  const sendFeedback = useCallback(
    async (messageId: string, rating: 1 | -1) => {
      if (!conversationId) return false;
      try {
        const { data } = await client.mutate({
          mutation: SUBMIT_FEEDBACK,
          variables: { input: { conversationId, messageId, rating } },
        });
        return Boolean(data?.submitFeedback);
      } catch {
        return false;
      }
    },
    [client, conversationId],
  );

  const newChat = useCallback(async () => {
    if (conversationId) {
      client.mutate({ mutation: CLEAR_CONVERSATION, variables: { id: conversationId } }).catch(() => {});
    }
    storeId(null);
    setConversationId(null);
    setMessages([]);
    setError(null);
  }, [client, conversationId]);

  return { conversationId, messages, pending, restoring, error, send, retry, sendFeedback, newChat };
}
