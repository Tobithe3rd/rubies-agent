import { useState, useRef, useCallback, useEffect } from "react";
import {
  createChat,
  deleteChat,
  getChatHistory,
  ChatExpiredError,
} from "@/lib/api";
import {
  emptyPanel,
  parsePanel,
  streamMessage,
  StreamHttpError,
  type Citation,
  type SessionPanel,
  type Step,
} from "@/lib/stream";
import { mapHistoryMessages } from "@/lib/history";
import * as chatIdStore from "@/lib/chat-id-store";

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

const EXPIRED_NOTICE = "Your session ended. Started a new chat.";
const NOTICE_VISIBLE_MS = 8000;
const POLL_INTERVAL_MS = 2000;
const MAX_POLL_ATTEMPTS = 15;

export function useChat() {
  const [chatId, setChatId] = useState<string | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [restoring, setRestoring] = useState(false);
  const [restoreFailed, setRestoreFailed] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [incompleteNote, setIncompleteNote] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [panel, setPanel] = useState<SessionPanel>(emptyPanel);
  const [panelReceivedAt, setPanelReceivedAt] = useState<number | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const initRef = useRef(false);
  const runRef = useRef(0);

  const patchMessage = useCallback(
    (id: string, patch: (message: ChatMessage) => ChatMessage) => {
      setMessages((prev) =>
        prev.map((message) => (message.id === id ? patch(message) : message))
      );
    },
    []
  );

  const resetPanel = useCallback(() => {
    setPanel(emptyPanel());
    setPanelReceivedAt(null);
  }, []);

  const startFreshChat = useCallback(async () => {
    const id = await createChat();
    chatIdStore.set(id);
    setChatId(id);
    setMessages([]);
    resetPanel();
    setError(null);
    setRestoreFailed(false);
    setIncompleteNote(false);
    return id;
  }, [resetPanel]);

  const recoverExpiredChat = useCallback(async () => {
    runRef.current += 1;
    abortRef.current?.abort();
    chatIdStore.clear();
    setMessages([]);
    resetPanel();
    setError(null);
    setRestoreFailed(false);
    setIncompleteNote(false);
    setNotice(null);
    try {
      await startFreshChat();
      setNotice(EXPIRED_NOTICE);
    } catch {
      setError("Couldn’t start a new chat. Please refresh the page.");
    }
  }, [resetPanel, startFreshChat]);

  const pollRestoredChat = useCallback(
    async (id: string, run: number) => {
      for (let attempt = 0; attempt < MAX_POLL_ATTEMPTS; attempt++) {
        await new Promise((resolve) => setTimeout(resolve, POLL_INTERVAL_MS));
        if (runRef.current !== run) return;
        try {
          const history = await getChatHistory(id);
          if (runRef.current !== run) return;
          const restored = mapHistoryMessages(history.messages);
          setMessages(restored);
          setPanel(parsePanel(history.panel) ?? emptyPanel());
          setPanelReceivedAt(Date.now());
          const last = restored[restored.length - 1];
          if (
            !(
              last?.role === "assistant" && last.status === "streaming"
            )
          ) {
            setIncompleteNote(false);
            return;
          }
        } catch (e) {
          if (runRef.current !== run) return;
          if (e instanceof ChatExpiredError) {
            await recoverExpiredChat();
            return;
          }
          setIncompleteNote(true);
          return;
        }
      }
      if (runRef.current === run) setIncompleteNote(true);
    },
    [recoverExpiredChat]
  );

  const restoreChat = useCallback(async () => {
    const storedId = chatIdStore.get();
    if (!storedId) {
      setLoading(true);
      try {
        await startFreshChat();
      } catch (e) {
        setError(
          "Failed to start chat: " +
            (e instanceof Error ? e.message : "unknown")
        );
      } finally {
        setLoading(false);
      }
      return;
    }

    const run = ++runRef.current;
    setRestoring(true);
    setRestoreFailed(false);
    setNotice(null);
    setIncompleteNote(false);
    setError(null);

    try {
      const history = await getChatHistory(storedId);
      if (runRef.current !== run) return;
      const restored = mapHistoryMessages(history.messages);
      setChatId(storedId);
      setMessages(restored);
      setPanel(parsePanel(history.panel) ?? emptyPanel());
      setPanelReceivedAt(Date.now());
      setError(null);

      const last = restored[restored.length - 1];
      if (last?.role === "assistant" && last.status === "streaming") {
        void pollRestoredChat(storedId, run);
      }
    } catch (e) {
      if (runRef.current !== run) return;
      if (e instanceof ChatExpiredError) {
        await recoverExpiredChat();
        setRestoring(false);
      } else {
        setRestoreFailed(true);
        setError("Couldn’t restore your chat. Please retry.");
      }
    } finally {
      if (runRef.current === run) {
        setRestoring(false);
        setLoading(false);
      }
    }
  }, [pollRestoredChat, recoverExpiredChat, startFreshChat]);

  // Restore or create exactly once per page load, even under StrictMode.
  useEffect(() => {
    if (initRef.current) return;
    initRef.current = true;
    void restoreChat();
  }, [restoreChat]);

  // Notices are transient: they clear themselves after a few seconds.
  useEffect(() => {
    if (!notice) return;
    const timer = setTimeout(() => setNotice(null), NOTICE_VISIBLE_MS);
    return () => clearTimeout(timer);
  }, [notice]);

  const send = useCallback(
    async (text: string, appendUser: boolean) => {
      const trimmed = text.trim();
      if (!chatId || !trimmed || loading || restoring) return;
      setNotice(null);

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
      setIncompleteNote(false);

      const controller = new AbortController();
      abortRef.current = controller;

      let streamedText = "";
      let stepsSinceText = false;

      try {
        await streamMessage(
          chatId,
          trimmed,
          {
            onStep: (step) => {
              stepsSinceText = true;
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
              const separator = stepsSinceText && streamedText ? "\n\n" : "";
              streamedText += separator + delta;
              stepsSinceText = false;
              patchMessage(assistantId, (message) => ({
                ...message,
                text: streamedText,
              }));
            },
            onPanel: (nextPanel) => {
              setPanel(nextPanel);
              setPanelReceivedAt(Date.now());
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
          await recoverExpiredChat();
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
    [chatId, loading, restoring, patchMessage, recoverExpiredChat]
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

  const retryRestore = useCallback(() => {
    if (restoring) return;
    void restoreChat();
  }, [restoring, restoreChat]);

  const newChat = useCallback(async () => {
    abortRef.current?.abort();
    runRef.current += 1;
    const previousId = chatId;
    setRestoring(false);
    setMessages([]);
    setError(null);
    setRestoreFailed(false);
    setNotice(null);
    setIncompleteNote(false);
    resetPanel();
    if (previousId) {
      try {
        await deleteChat(previousId);
      } catch {
        // ignore delete errors
      }
    }
    chatIdStore.clear();
    setLoading(true);
    try {
      await startFreshChat();
    } catch (e) {
      setError(
        "Failed to start chat: " + (e instanceof Error ? e.message : "unknown")
      );
    } finally {
      setLoading(false);
    }
  }, [chatId, resetPanel, startFreshChat]);

  return {
    chatId,
    messages,
    input,
    setInput,
    loading,
    restoring,
    restoreFailed,
    notice,
    incompleteNote,
    error,
    panel,
    panelReceivedAt,
    submit,
    stop,
    retry,
    retryRestore,
    recoverExpiredChat,
    newChat,
  };
}
