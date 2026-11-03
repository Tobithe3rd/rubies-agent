"use client";

import { useState, useCallback } from "react";
import { ArrowUp, RotateCcw } from "lucide-react";
import {
  Conversation,
  ConversationContent,
} from "@/components/ai-elements/conversation";
import {
  Message,
  MessageContent,
  MessageResponse,
} from "@/components/ai-elements/message";
import {
  PromptInput,
  PromptInputFooter,
  PromptInputSubmit,
  PromptInputTextarea,
} from "@/components/ai-elements/prompt-input";
import { Suggestion } from "@/components/ai-elements/suggestion";
import { Loader } from "@/components/ai-elements/loader";
import { StepPanel } from "@/components/step-panel";
import { useChat } from "@/lib/use-chat";
import { config } from "@/lib/config";
import type { Citation } from "@/lib/stream";
import { cn } from "@/lib/utils";

const SUGGESTIONS = [
  "What is the fee for transfers above ₦50,000?",
  "I lost my card, please block it",
  "Abeg, my money no gree enter o",
];

function Citations({ citations }: { citations: Citation[] }) {
  if (citations.length === 0) return null;

  return (
    <div className="mt-3 border-t border-[var(--border)] pt-2.5">
      <p className="text-[11px] font-semibold uppercase tracking-[0.08em] text-[var(--muted)]">
        Sources
      </p>
      <ul className="mt-1.5 space-y-1">
        {citations.map((citation, index) => (
          <li
            key={`${citation.document}-${citation.section}-${index}`}
            className="text-[13px] leading-snug text-[var(--muted)]"
          >
            <span className="text-[var(--text)]">{citation.document}</span>
            {citation.section ? <> · {citation.section}</> : null}
          </li>
        ))}
      </ul>
    </div>
  );
}

export default function HomePage() {
  const {
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
  } = useChat();

  const [showOtp, setShowOtp] = useState(false);
  const [otpLine, setOtpLine] = useState("");

  const handleNewChat = useCallback(() => {
    setShowOtp(false);
    setOtpLine("");
    newChat();
  }, [newChat]);

  const handleOtp = useCallback(async () => {
    if (!chatId) return;
    if (showOtp) {
      setShowOtp(false);
      return;
    }
    try {
      const res = await fetch(`${config.apiUrl}/chats/${chatId}/dev-otp`);
      if (res.status === 404) {
        setShowOtp(false);
        setOtpLine("");
        return;
      }
      const data = await res.json();
      if (res.ok && "otp_line" in data) {
        setOtpLine(data.otp_line);
        setShowOtp(true);
      } else {
        setShowOtp(false);
        setOtpLine("");
      }
    } catch {
      setShowOtp(false);
      setOtpLine("");
    }
  }, [chatId, showOtp]);

  return (
    <main className="flex h-dvh flex-col bg-[var(--ground)] font-sans text-[var(--text)]">
      <header className="shrink-0 border-b border-[var(--border)] bg-[var(--surface)]">
        <div className="mx-auto flex h-14 w-full max-w-3xl items-center justify-between gap-3 px-4 sm:px-6">
          <div className="flex min-w-0 items-center gap-2.5">
            <div
              className="flex size-8 shrink-0 items-center justify-center rounded-full bg-[var(--accent)] text-[15px] font-bold text-white"
              aria-hidden="true"
            >
              R
            </div>
            <h1 className="truncate text-[15px] font-semibold tracking-[-0.01em]">
              Rubies MFB Support
            </h1>
          </div>

          <div className="flex shrink-0 items-center gap-2">
            {config.demoOtp && (
              <button
                type="button"
                onClick={handleOtp}
                className="rounded-lg border border-[var(--demo-border)] bg-[var(--demo-bg)] px-2.5 py-1.5 text-[12px] font-medium text-[var(--demo-text)] transition-colors hover:brightness-[0.98] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent)]"
                aria-label="Show demo OTP"
                aria-expanded={showOtp}
              >
                Demo OTP
              </button>
            )}
            <button
              type="button"
              onClick={handleNewChat}
              className="rounded-lg border border-[var(--input-border)] bg-[var(--surface)] px-3 py-1.5 text-[13px] font-medium text-[var(--text)] transition-colors hover:bg-[var(--avatar-bg)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent)]"
            >
              New chat
            </button>
          </div>
        </div>
      </header>

      <Conversation className="min-h-0 flex-1">
        <ConversationContent
          className={cn(
            "mx-auto w-full max-w-3xl gap-5 px-4 py-6 sm:px-6",
            messages.length === 0 && "min-h-full justify-center"
          )}
        >
          {messages.length === 0 && (
            <div className="flex flex-col items-center justify-center px-2 py-12 text-center">
              <div
                className="flex size-12 items-center justify-center rounded-full bg-[var(--accent)] text-[21px] font-bold text-white"
                aria-hidden="true"
              >
                R
              </div>
              <h2 className="mt-5 text-[26px] font-semibold tracking-[-0.02em]">
                How can we help?
              </h2>
              <p className="mt-2 max-w-md text-[15px] leading-[1.6] text-[var(--muted)]">
                Ask about fees, cards, transfers or loans. For account tasks I’ll
                verify you first.
              </p>
              <div className="mt-7 flex flex-wrap justify-center gap-2">
                {SUGGESTIONS.map((suggestion) => (
                  <Suggestion
                    key={suggestion}
                    suggestion={suggestion}
                    onClick={(value) => submit(value)}
                    disabled={loading || !chatId}
                    className="h-auto max-w-full whitespace-normal rounded-full border-[var(--input-border)] bg-[var(--surface)] px-4 py-2 text-left text-[13px] font-normal leading-snug text-[var(--text)] hover:bg-[var(--avatar-bg)] hover:text-[var(--text)]"
                  />
                ))}
              </div>
            </div>
          )}

          {messages.map((message) =>
            message.role === "user" ? (
              <Message
                key={message.id}
                from="user"
                className="max-w-[70%]"
                aria-label="Your message"
              >
                <div className="whitespace-pre-wrap break-words rounded-tl-[18px] rounded-tr-[18px] rounded-bl-[18px] rounded-br-[4px] bg-[var(--accent)] px-4 py-2.5 text-[15px] leading-[1.5] text-white">
                  {message.text}
                </div>
              </Message>
            ) : (
              <div key={message.id} className="flex items-start gap-3">
                <div
                  className="mt-0.5 flex size-7 shrink-0 items-center justify-center rounded-full bg-[var(--avatar-bg)] text-[12px] font-semibold text-[var(--accent)]"
                  aria-hidden="true"
                >
                  R
                </div>
                <Message
                  from="assistant"
                  className="min-w-0 max-w-full flex-1"
                  aria-label="Rubies reply"
                >
                  <MessageContent className="w-full max-w-full gap-0 overflow-visible p-0 text-[15px] leading-[1.6] text-[var(--text)]">
                    {message.steps.length > 0 && (
                      <StepPanel steps={message.steps} />
                    )}

                    {message.text ? (
                      <MessageResponse className="agent-text">
                        {message.text}
                      </MessageResponse>
                    ) : message.status === "streaming" ? (
                      <div className="flex items-center gap-2 py-1 text-[14px] text-[var(--muted)]">
                        <Loader size={14} />
                        Thinking…
                      </div>
                    ) : null}

                    {message.status === "streaming" && message.text && (
                      <span
                        className="ml-0.5 inline-block h-4 w-[2px] translate-y-[2px] animate-pulse bg-[var(--muted)]"
                        aria-hidden="true"
                      />
                    )}

                    <Citations citations={message.citations} />

                    {(message.status === "stopped" ||
                      (message.status === "error" && message.canRetry)) && (
                      <div className="mt-2 flex items-center gap-2 text-[13px] text-[var(--muted)]">
                        <span>
                          {message.status === "stopped"
                            ? "Stopped."
                            : "Reply interrupted."}
                        </span>
                        {message.canRetry && (
                          <button
                            type="button"
                            onClick={retry}
                            disabled={loading}
                            className="inline-flex items-center gap-1 rounded-md font-medium text-[var(--text)] underline decoration-[var(--input-border)] underline-offset-2 transition-colors hover:decoration-[var(--text)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent)] disabled:opacity-50"
                          >
                            <RotateCcw size={12} />
                            Retry
                          </button>
                        )}
                      </div>
                    )}
                  </MessageContent>
                </Message>
              </div>
            )
          )}
        </ConversationContent>
      </Conversation>

      <div className="shrink-0 bg-[var(--ground)]">
        <div className="mx-auto w-full max-w-3xl px-4 pb-4 pt-2 sm:px-6">
          {showOtp && otpLine && (
            <div className="mb-2 rounded-xl border border-[var(--demo-border)] bg-[var(--demo-bg)] px-4 py-2.5 text-[var(--demo-text)]">
              <div className="flex items-center gap-2">
                <span
                  className="inline-block size-1.5 rounded-full bg-[var(--demo-text)]"
                  aria-hidden="true"
                />
                <p className="text-[11px] font-semibold uppercase tracking-[0.08em]">
                  Demo OTP · Development only
                </p>
              </div>
              <p className="mt-0.5 font-mono text-[13px] tracking-wide">
                {otpLine}
              </p>
            </div>
          )}

          {error && (
            <div
              role="status"
              className="mb-2 flex items-start gap-2 rounded-lg border border-[var(--failed-border)] bg-[var(--failed-bg)] px-3 py-2 text-[13px] leading-snug text-[var(--failed-text)]"
            >
              <span className="min-w-0 flex-1">{error}</span>
              {error.includes("expired") && (
                <button
                  type="button"
                  onClick={handleNewChat}
                  className="shrink-0 font-semibold underline underline-offset-2 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent)]"
                >
                  New chat
                </button>
              )}
            </div>
          )}

          <PromptInput
            className="composer"
            onSubmit={(message) => {
              if (message.text.trim() && !loading) submit(message.text);
            }}
          >
            <PromptInputTextarea
              value={input}
              onChange={(event) => setInput(event.target.value)}
              placeholder="Message Rubies support"
              aria-label="Message"
              disabled={loading || !chatId}
              className="max-h-40 min-h-[44px] px-4 pb-1 pt-3.5 font-sans text-[15px] text-[var(--text)] placeholder:text-[var(--muted)]"
            />
            <PromptInputFooter className="px-2.5 pb-2.5 pt-0">
              <span />
              <PromptInputSubmit
                status={loading && chatId ? "streaming" : "ready"}
                onStop={stop}
                disabled={!chatId || (!loading && !input.trim())}
                className="size-9 shrink-0 rounded-full bg-[var(--accent)] text-white shadow-sm hover:bg-[var(--accent)] hover:opacity-90 disabled:opacity-40"
              >
                {loading && chatId ? (
                  <span className="size-3 rounded-[2px] bg-white" />
                ) : (
                  <ArrowUp size={18} strokeWidth={2.5} />
                )}
              </PromptInputSubmit>
            </PromptInputFooter>
          </PromptInput>

          <p className="mt-2 text-center text-[11px] leading-relaxed text-[var(--muted)]">
            Rubies will never ask for your PIN, password or full card number in
            chat.
          </p>
        </div>
      </div>
    </main>
  );
}
