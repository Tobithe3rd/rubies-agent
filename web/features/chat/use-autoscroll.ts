import { useEffect, useRef } from "react";
import type { StickToBottomContext } from "use-stick-to-bottom";

export function useAutoscroll(restoring: boolean) {
  const conversationRef = useRef<StickToBottomContext | null>(null);
  const wasRestoring = useRef(false);

  useEffect(() => {
    if (wasRestoring.current && !restoring) {
      window.requestAnimationFrame(() => {
        conversationRef.current?.scrollToBottom("instant");
      });
    }
    wasRestoring.current = restoring;
  }, [restoring]);

  return conversationRef;
}
