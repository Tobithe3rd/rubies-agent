import { useState, useRef, useCallback, useEffect } from "react";
import { createChat, deleteChat, ChatExpiredError } from "@/lib/api";
import {
  streamMessage,
  StreamHttpError,
  type Citation,
  type Step,
} from "@/lib/stream";

export type MessageStatus = "streaming" | "done" | "stopped" | "error";

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  text: string;
  steps: Step[];
  citations: Citation[];
  status: MessageStatus;
  canRetry?: boolean;
}

export interface ChatState {
  chatId: string | null;
  messages: ChatMessage[];
  input: string;
  loading: boolean;
  error: string | null;
}

const makeId = () =>
  `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 9)}`;

function emptyMessage(role: ChatMessage["role"]): ChatMessage {
  return {
    id: makeId(),
    role,
    text: "",
    steps: [],
    citations: [],
    status: role === "user" ? "done" : "streaming",
  };
}

function badRequestText(detail: string): string {
  if (detail === "empty_message") return "Please enter a message.";
  if (detail === "message_too_long") {
    return "That message is too long. Please shorten it.";
  }
  return "That message couldn’t be sent. Please try again.";
}

export function useChat() {
  const [chatId, setChatId] = useState<string | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  const patchMessage = useCallback(
    (id: string, patch: (message: ChatMessage) => ChatMessage) => {
      setMessages((prev) =>
        prev.map((message) => (message.id === id ? patch(message) : message))
      );
    },
    []
  );

  const initChat = useCallback(async () => {
    try {
      setLoading(true);
      const id = await createChat();
      setChatId(id);
      setMessages([]);
      setError(null);
    } catch (e) {
      setError(
        "Failed to start chat: " +
          (e instanceof Error ? e.message : "unknown")
      );
    } finally {
      setLoading(false);
    }
  }, []);

  // Auto-create on mount (refresh = new chat, no persistence)
  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- initChat owns the loading state
    initChat();
  }, [initChat]);

  const send = useCallback(
    async (text: string, appendUser: boolean) => {
      const trimmed = text.trim();
      if (!chatId || !trimmed || loading) return;

      const userMessage = emptyMessage("user");
      userMessage.text = trimmed;
      const agentMessage = emptyMessage("assistant");
      const assistantId = agentMessage.id;

      setMessages((prev) => [
        ...prev,
        ...(appendUser ? [userMessage] : []),
        agentMessage,
      ]);
      setInput("");
      setLoading(true);
      setError(null);

      const controller = new AbortController();
      abortRef.current = controller;

      try {
        await streamMessage(
          chatId,
          trimmed,
          {
            onStep: (step) => {
              patchMessage(assistantId, (message) => {
                const exists = message.steps.some((s) => s.id === step.id);
                return {
                  ...message,
                  steps: exists
                    ? message.steps.map((s) => (s.id === step.id ? step : s))
                    : [...message.steps, step],
                };
              });
            },
            onText: (delta) => {
              patchMessage(assistantId, (message) => ({
                ...message,
                text: message.text + delta,
              }));
            },
            onDone: (citations) => {
              patchMessage(assistantId, (message) => ({
                ...message,
                citations,
                status: "done",
              }));
            },
            onError: (detail) => {
              patchMessage(assistantId, (message) => ({
                ...message,
                text: message.text || detail,
                status: "error",
                canRetry: true,
              }));
            },
          },
          controller.signal
        );
      } catch (e) {
        if (controller.signal.aborted) {
          patchMessage(assistantId, (message) =>
            message.status === "streaming"
              ? { ...message, status: "stopped", canRetry: true }
              : message
          );
        } else if (e instanceof ChatExpiredError) {
          setError("Your session expired. Starting a new chat.");
          setMessages([]);
          try {
            const newId = await createChat();
            setChatId(newId);
          } catch {
            setError("Couldn’t start a new chat. Please refresh the page.");
          }
        } else if (e instanceof StreamHttpError && e.status === 400) {
          setMessages((prev) => prev.filter((m) => m.id !== assistantId));
          setError(badRequestText(e.detail));
        } else {
          patchMessage(assistantId, (message) => ({
            ...message,
            status: "error",
            canRetry: true,
          }));
        }
      } finally {
        if (abortRef.current === controller) abortRef.current = null;
        setLoading(false);
      }
    },
    [chatId, loading, patchMessage]
  );

  const submit = useCallback(
    (text: string) => {
      void send(text, true);
    },
    [send]
  );

  const stop = useCallback(() => {
    abortRef.current?.abort();
  }, []);

  const retry = useCallback(() => {
    if (loading) return;
    const lastUser = [...messages].reverse().find((m) => m.role === "user");
    if (!lastUser) return;
    setMessages((prev) => {
      const next = [...prev];
      while (next.length > 0 && next[next.length - 1].role === "assistant") {
        next.pop();
      }
      return next;
    });
    void send(lastUser.text, false);
  }, [messages, loading, send]);

  const newChat = useCallback(async () => {
    abortRef.current?.abort();
    const previousId = chatId;
    setMessages([]);
    setError(null);
    if (previousId) {
      try {
        await deleteChat(previousId);
      } catch {
        // ignore delete errors
      }
    }
    await initChat();
  }, [chatId, initChat]);

  return {
    chatId,
    messages,
    input,
    setInput,
    loading,
    error,
    submit,
    stop,
    retry,
    newChat,
  };
}
