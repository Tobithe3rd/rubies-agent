"use client";

import { RotateCcw } from "lucide-react";
import {
  Message,
  MessageContent,
  MessageResponse,
} from "@/components/ai-elements/message";
import { Loader } from "@/components/ai-elements/loader";
import { StepPanel } from "@/features/chat/StepPanel";
import { Sources } from "@/features/chat/Sources";
import { QuickReplies } from "@/features/chat/QuickReplies";
import { config, copy } from "@/core/config";
import type { ChatMessage } from "@/core/contract";

interface AgentMessageProps {
  message: ChatMessage;
  showQuickReplies: boolean;
  replies: readonly string[];
  loading: boolean;
  restoring: boolean;
  chatId: string | null;
  onQuickMessage: (message: string) => void;
  onRetry: () => void;
}

export function AgentMessage({
  message,
  showQuickReplies,
  replies,
  loading,
  restoring,
  chatId,
  onQuickMessage,
  onRetry,
}: AgentMessageProps) {
  return (
    <div className="flex items-start gap-3">
      <div
        className="mt-0.5 flex size-7 shrink-0 items-center justify-center rounded-full bg-[var(--avatar-bg)] text-[12px] font-semibold text-[var(--avatar-fg)]"
        aria-hidden="true"
      >
        {config.logoLetter}
      </div>
      <Message
        from="assistant"
        className="min-w-0 max-w-full flex-1"
        aria-label={copy.chat.agentAria}
      >
        <MessageContent className="w-full max-w-full gap-0 overflow-visible p-0 text-[15px] leading-[1.6] text-[var(--text)]">
          {message.steps.length > 0 && (
            <StepPanel
              steps={message.steps}
              streaming={message.status === "streaming"}
            />
          )}

          {message.text ? (
            <div
              className="agent-text"
              data-streaming={message.status === "streaming" ? "" : undefined}
            >
              <MessageResponse controls={{ table: false }}>
                {message.text}
              </MessageResponse>
            </div>
          ) : message.status === "streaming" ? (
            <div className="flex items-center gap-2 py-1 text-[14px] text-[var(--muted)]">
              <Loader size={14} />
              {copy.chat.thinking}
            </div>
          ) : null}

          <Sources citations={message.citations} />

          {showQuickReplies && (
            <QuickReplies
              replies={replies}
              disabled={loading || restoring || !chatId}
              onReply={onQuickMessage}
            />
          )}

          {(message.status === "stopped" ||
            (message.status === "error" && message.canRetry)) && (
            <div className="mt-2 flex items-center gap-2 text-[13px] text-[var(--muted)]">
              <span>
                {message.status === "stopped"
                  ? copy.chat.stopped
                  : copy.chat.interrupted}
              </span>
              {message.canRetry && (
                <button
                  type="button"
                  onClick={onRetry}
                  disabled={loading}
                  className="inline-flex items-center gap-1 rounded-md font-medium text-[var(--text)] underline decoration-[var(--input-border)] underline-offset-2 transition-colors hover:decoration-[var(--text)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent)] disabled:opacity-50"
                >
                  <RotateCcw size={12} />
                  {copy.chat.retry}
                </button>
              )}
            </div>
          )}
        </MessageContent>
      </Message>
    </div>
  );
}
