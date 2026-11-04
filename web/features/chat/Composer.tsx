"use client";

import { ArrowUp } from "lucide-react";
import {
  PromptInput,
  PromptInputSubmit,
  PromptInputTextarea,
} from "@/components/ai-elements/prompt-input";
import { cn } from "@/lib/utils";
import { copy } from "@/core/config";

interface ComposerProps {
  input: string;
  setInput: (value: string) => void;
  loading: boolean;
  restoring: boolean;
  chatId: string | null;
  notice: string | null;
  incompleteNote: boolean;
  error: string | null;
  restoreFailed: boolean;
  verificationExpired: boolean;
  showOtp: boolean;
  otpLine: string;
  onSubmit: (text: string) => void;
  onStop: () => void;
  onRetryRestore: () => void;
  onNewChat: () => void;
}

export function Composer({
  input,
  setInput,
  loading,
  restoring,
  chatId,
  notice,
  incompleteNote,
  error,
  restoreFailed,
  verificationExpired,
  showOtp,
  otpLine,
  onSubmit,
  onStop,
  onRetryRestore,
  onNewChat,
}: ComposerProps) {
  return (
    <div className="shrink-0 bg-[var(--ground)]">
      <div className="mx-auto w-full max-w-3xl px-4 pb-[max(1rem,env(safe-area-inset-bottom))] pt-2 sm:px-6">
        {showOtp && otpLine && (
          <div className="mb-2 rounded-xl border border-[var(--demo-border)] bg-[var(--demo-bg)] px-4 py-2.5 text-[var(--demo-text)]">
            <div className="flex items-center gap-2">
              <span
                className="inline-block size-1.5 rounded-full bg-[var(--demo-text)]"
                aria-hidden="true"
              />
              <p className="text-[11px] font-semibold uppercase tracking-[0.08em]">
                {copy.chat.demoOtpLabel}
              </p>
            </div>
            <p className="mt-0.5 font-mono text-[13px] tracking-wide">
              {otpLine}
            </p>
          </div>
        )}

        {notice && (
          <div
            role="status"
            className="mb-2 rounded-lg border border-[var(--border)] bg-[var(--avatar-bg)] px-3 py-2 text-[13px] leading-snug text-[var(--text)]"
          >
            {notice}
          </div>
        )}

        {verificationExpired && (
          <div
            role="status"
            className="mb-2 rounded-lg border border-[var(--border)] bg-[var(--surface)] px-3 py-2 text-[13px] leading-snug text-[var(--muted)]"
          >
            {copy.chat.verificationExpired}
          </div>
        )}

        {incompleteNote && (
          <p className="mb-2 px-1 text-[12px] leading-snug text-[var(--muted)]">
            {copy.chat.incomplete}
          </p>
        )}

        {error && (
          <div
            role="status"
            className="mb-2 flex items-start gap-2 rounded-lg border border-[var(--failed-border)] bg-[var(--failed-bg)] px-3 py-2 text-[13px] leading-snug text-[var(--failed-text)]"
          >
            <span className="min-w-0 flex-1">{error}</span>
            {restoreFailed ? (
              <button
                type="button"
                onClick={onRetryRestore}
                disabled={restoring}
                className="shrink-0 font-semibold underline underline-offset-2 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent)] disabled:opacity-50"
              >
                {copy.chat.retry}
              </button>
            ) : (
              error.includes("expired") && (
                <button
                  type="button"
                  onClick={onNewChat}
                  className="shrink-0 font-semibold underline underline-offset-2 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent)]"
                >
                  {copy.chat.newChatButton}
                </button>
              )
            )}
          </div>
        )}

        <PromptInput
          className="composer"
          onSubmit={(message) => {
            if (message.text.trim() && !loading && !restoring) {
              onSubmit(message.text);
            }
          }}
        >
          <PromptInputTextarea
            value={input}
            onChange={(event) => setInput(event.target.value)}
            placeholder={loading ? copy.chat.inputBusy : copy.chat.inputIdle}
            aria-label={copy.chat.messageAria}
            disabled={loading || restoring || !chatId}
            className="max-h-[156px] min-h-11 flex-1 px-4 py-2.5 font-sans text-[15px] leading-[1.5] text-[var(--text)] placeholder:text-[var(--muted)]"
          />
          <PromptInputSubmit
            status={loading && chatId && !restoring ? "streaming" : "ready"}
            onStop={onStop}
            disabled={restoring || !chatId || (!loading && !input.trim())}
            className={cn(
              "size-11 shrink-0 rounded-full shadow-sm transition-colors disabled:pointer-events-auto disabled:cursor-not-allowed disabled:opacity-100",
              loading && chatId && !restoring
                ? "bg-[var(--stop-bg)] text-[var(--stop-fg)] hover:bg-[var(--stop-bg)]"
                : input.trim()
                  ? "bg-[var(--accent)] text-white hover:bg-[var(--accent)] hover:opacity-90"
                  : "bg-[var(--border)] text-[var(--muted)] hover:bg-[var(--border)]"
            )}
          >
            {loading && chatId && !restoring ? (
              <span className="size-3 rounded-[2px] bg-[var(--stop-fg)]" />
            ) : (
              <ArrowUp size={18} strokeWidth={2.5} />
            )}
          </PromptInputSubmit>
        </PromptInput>

        <p className="mt-2 text-center text-[11px] leading-relaxed text-[var(--muted)]">
          {copy.chat.safety}
        </p>
      </div>
    </div>
  );
}
