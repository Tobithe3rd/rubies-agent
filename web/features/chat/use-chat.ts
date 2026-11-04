import { useCallback, useEffect, useReducer, useRef, useState } from "react";
import { ChatExpiredError, ValidationError } from "@/core/transport/types";
import { transport } from "@/core/transport";
import { chatReducer, initialState } from "@/core/reducer/chat-reducer";
import * as chatIdStore from "@/core/storage/chat-id-store";
import { copy } from "@/core/config";
import { useChatSession } from "@/features/chat/use-chat-session";

const NOTICE_VISIBLE_MS = 8000;

const makeId = () =>
  `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 9)}`;

function badRequestText(detail: string): string {
  if (detail === "empty_message") return copy.errors.emptyMessage;
  if (detail === "message_too_long") return copy.errors.tooLong;
  return copy.errors.sendFailed;
}

export type ChatController = ReturnType<typeof useChat>;

export function useChat() {
  const [state, dispatch] = useReducer(chatReducer, initialState);
  const [chatId, setChatId] = useState<string | null>(null);
  const [input, setInput] = useState("");
  const abortRef = useRef<AbortController | null>(null);
  const initRef = useRef(false);
  const runRef = useRef(0);

  const { startFreshChat, recoverExpiredChat, restoreChat } = useChatSession({
    dispatch,
    setChatId,
    runRef,
    abortRef,
  });

  useEffect(() => {
    if (initRef.current) return;
    initRef.current = true;
    void restoreChat();
  }, [restoreChat]);

  useEffect(() => {
    if (!state.notices.notice) return;
    const timer = setTimeout(
      () => dispatch({ type: "notice", message: null }),
      NOTICE_VISIBLE_MS
    );
    return () => clearTimeout(timer);
  }, [state.notices.notice]);

  const send = useCallback(
    async (text: string, appendUser: boolean) => {
      const trimmed = text.trim();
      if (!chatId || !trimmed || state.status.loading || state.status.restoring) {
        return;
      }
      dispatch({ type: "notice", message: null });

      const assistantId = makeId();
      dispatch({
        type: "sent",
        assistantId,
        user: appendUser ? { id: makeId(), text: trimmed } : null,
      });
      setInput("");
      dispatch({ type: "loading", value: true });
      dispatch({ type: "error", message: null });
      dispatch({ type: "incomplete", value: false });

      const controller = new AbortController();
      abortRef.current = controller;

      try {
        for await (const event of transport.sendMessage(
          chatId,
          trimmed,
          controller.signal
        )) {
          dispatch({
            type: "stream-event",
            id: assistantId,
            event,
            at: Date.now(),
          });
        }
        dispatch({ type: "stream-ended", id: assistantId });
      } catch (error) {
        if (controller.signal.aborted) {
          dispatch({ type: "stopped", id: assistantId });
        } else if (error instanceof ChatExpiredError) {
          await recoverExpiredChat();
        } else if (error instanceof ValidationError) {
          dispatch({ type: "message-removed", id: assistantId });
          dispatch({ type: "error", message: badRequestText(error.detail) });
        } else {
          dispatch({ type: "interrupted", id: assistantId });
        }
      } finally {
        if (abortRef.current === controller) abortRef.current = null;
        dispatch({ type: "loading", value: false });
      }
    },
    [
      chatId,
      state.status.loading,
      state.status.restoring,
      recoverExpiredChat,
    ]
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
    if (state.status.loading) return;
    const lastUser = [...state.messages]
      .reverse()
      .find((message) => message.role === "user");
    if (!lastUser) return;
    const trailing: string[] = [];
    for (let index = state.messages.length - 1; index >= 0; index--) {
      if (state.messages[index].role !== "assistant") break;
      trailing.push(state.messages[index].id);
    }
    trailing.forEach((id) => dispatch({ type: "message-removed", id }));
    void send(lastUser.text, false);
  }, [state.messages, state.status.loading, send]);

  const retryRestore = useCallback(() => {
    if (state.status.restoring) return;
    void restoreChat();
  }, [state.status.restoring, restoreChat]);

  const newChat = useCallback(async () => {
    abortRef.current?.abort();
    runRef.current += 1;
    const previousId = chatId;
    dispatch({ type: "restoring", value: false });
    dispatch({ type: "reset" });
    dispatch({ type: "error", message: null });
    dispatch({ type: "restore-failed", value: false });
    dispatch({ type: "notice", message: null });
    dispatch({ type: "incomplete", value: false });
    if (previousId) {
      try {
        await transport.deleteChat(previousId);
      } catch {
        // ignore delete errors
      }
    }
    chatIdStore.clear();
    dispatch({ type: "loading", value: true });
    try {
      await startFreshChat();
    } catch (error) {
      const detail = error instanceof Error ? error.message : copy.errors.unknown;
      dispatch({ type: "error", message: copy.errors.startChatPrefix + detail });
    } finally {
      dispatch({ type: "loading", value: false });
    }
  }, [chatId, startFreshChat]);

  return {
    chatId,
    messages: state.messages,
    input,
    setInput,
    loading: state.status.loading,
    restoring: state.status.restoring,
    restoreFailed: state.status.restoreFailed,
    notice: state.notices.notice,
    incompleteNote: state.notices.incomplete,
    error: state.notices.error,
    panel: state.panel,
    panelReceivedAt: state.panelReceivedAt,
    submit,
    stop,
    retry,
    retryRestore,
    recoverExpiredChat,
    newChat,
  };
}
