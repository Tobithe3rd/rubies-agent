import { useCallback, type Dispatch, type MutableRefObject } from "react";
import { copy } from "@/core/config";
import { ChatExpiredError } from "@/core/transport/types";
import { transport } from "@/core/transport";
import { mapHistoryMessages } from "@/core/reducer/history";
import * as chatIdStore from "@/core/storage/chat-id-store";
import type { ChatAction } from "@/core/reducer/chat-reducer";

const POLL_INTERVAL_MS = 2000;
const MAX_POLL_ATTEMPTS = 15;

interface SessionArgs {
  dispatch: Dispatch<ChatAction>;
  setChatId: (id: string) => void;
  runRef: MutableRefObject<number>;
  abortRef: MutableRefObject<AbortController | null>;
}

export function useChatSession({
  dispatch,
  setChatId,
  runRef,
  abortRef,
}: SessionArgs) {
  const startFreshChat = useCallback(async () => {
    const id = await transport.createChat();
    chatIdStore.set(id);
    setChatId(id);
    dispatch({ type: "reset" });
    dispatch({ type: "error", message: null });
    dispatch({ type: "restore-failed", value: false });
    dispatch({ type: "incomplete", value: false });
    return id;
  }, [dispatch, setChatId]);

  const recoverExpiredChat = useCallback(async () => {
    runRef.current += 1;
    abortRef.current?.abort();
    chatIdStore.clear();
    dispatch({ type: "chat-expired" });
    dispatch({ type: "error", message: null });
    dispatch({ type: "restore-failed", value: false });
    dispatch({ type: "incomplete", value: false });
    dispatch({ type: "notice", message: null });
    try {
      await startFreshChat();
      dispatch({ type: "notice", message: copy.errors.expiredNotice });
    } catch {
      dispatch({ type: "error", message: copy.errors.newChatFailed });
    }
  }, [abortRef, dispatch, runRef, startFreshChat]);

  const pollRestoredChat = useCallback(
    async (id: string, run: number) => {
      for (let attempt = 0; attempt < MAX_POLL_ATTEMPTS; attempt++) {
        await new Promise((resolve) => setTimeout(resolve, POLL_INTERVAL_MS));
        if (runRef.current !== run) return;
        try {
          const history = await transport.loadHistory(id);
          if (runRef.current !== run) return;
          const restored = mapHistoryMessages(history.messages);
          dispatch({
            type: "history-restored",
            messages: restored,
            panel: history.panel,
            at: Date.now(),
          });
          const last = restored[restored.length - 1];
          if (!(last?.role === "assistant" && last.status === "streaming")) {
            dispatch({ type: "incomplete", value: false });
            return;
          }
        } catch (error) {
          if (runRef.current !== run) return;
          if (error instanceof ChatExpiredError) {
            await recoverExpiredChat();
            return;
          }
          dispatch({ type: "incomplete", value: true });
          return;
        }
      }
      if (runRef.current === run) dispatch({ type: "incomplete", value: true });
    },
    [dispatch, recoverExpiredChat, runRef]
  );

  const restoreChat = useCallback(async () => {
    const storedId = chatIdStore.get();
    if (!storedId) {
      dispatch({ type: "loading", value: true });
      try {
        await startFreshChat();
      } catch (error) {
        const detail = error instanceof Error ? error.message : copy.errors.unknown;
        dispatch({ type: "error", message: copy.errors.startChatPrefix + detail });
      } finally {
        dispatch({ type: "loading", value: false });
      }
      return;
    }

    const run = ++runRef.current;
    dispatch({ type: "restoring", value: true });
    dispatch({ type: "restore-failed", value: false });
    dispatch({ type: "notice", message: null });
    dispatch({ type: "incomplete", value: false });
    dispatch({ type: "error", message: null });

    try {
      const history = await transport.loadHistory(storedId);
      if (runRef.current !== run) return;
      const restored = mapHistoryMessages(history.messages);
      setChatId(storedId);
      dispatch({
        type: "history-restored",
        messages: restored,
        panel: history.panel,
        at: Date.now(),
      });
      dispatch({ type: "error", message: null });

      const last = restored[restored.length - 1];
      if (last?.role === "assistant" && last.status === "streaming") {
        void pollRestoredChat(storedId, run);
      }
    } catch (error) {
      if (runRef.current !== run) return;
      if (error instanceof ChatExpiredError) {
        await recoverExpiredChat();
        dispatch({ type: "restoring", value: false });
      } else {
        dispatch({ type: "restore-failed", value: true });
        dispatch({ type: "error", message: copy.errors.restoreFailed });
      }
    } finally {
      if (runRef.current === run) {
        dispatch({ type: "restoring", value: false });
        dispatch({ type: "loading", value: false });
      }
    }
  }, [dispatch, pollRestoredChat, recoverExpiredChat, runRef, setChatId, startFreshChat]);

  return { startFreshChat, recoverExpiredChat, restoreChat };
}
