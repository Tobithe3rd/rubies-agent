"use client";

import { PanelRight } from "lucide-react";
import { config, copy } from "@/core/config";
import { MessageList } from "@/features/chat/MessageList";
import { Composer } from "@/features/chat/Composer";
import type { ChatController } from "@/features/chat/use-chat";

interface ChatScreenProps {
  chat: ChatController;
  panelOpen: boolean;
  panelEnabled: boolean;
  verificationExpired: boolean;
  showOtp: boolean;
  otpLine: string;
  onTogglePanel: () => void;
  onToggleOtp: () => void;
  onNewChat: () => void;
}

export function ChatScreen({
  chat,
  panelOpen,
  panelEnabled,
  verificationExpired,
  showOtp,
  otpLine,
  onTogglePanel,
  onToggleOtp,
  onNewChat,
}: ChatScreenProps) {
  return (
    <div className="flex min-w-0 flex-1 flex-col">
      <header className="shrink-0 border-b border-[var(--border)] bg-[var(--surface)]">
        <div className="mx-auto flex h-14 w-full max-w-3xl items-center justify-between gap-3 px-4 sm:px-6">
          <div className="flex min-w-0 items-center gap-2.5">
            <div
              className="flex size-7 shrink-0 items-center justify-center rounded-[7px] bg-[var(--accent)] text-[14px] font-bold text-white sm:size-8 sm:rounded-[8px] sm:text-[15px]"
              aria-hidden="true"
            >
              {config.logoLetter}
            </div>
            <h1 className="truncate text-[15px] font-semibold tracking-[-0.01em]">
              {config.brandName}
            </h1>
          </div>

          <div className="flex shrink-0 items-center gap-2">
            {config.demoOtp && (
              <button
                type="button"
                onClick={onToggleOtp}
                className="rounded-lg border border-[var(--demo-border)] bg-[var(--demo-bg)] px-2.5 py-1.5 text-[12px] font-medium text-[var(--demo-text)] transition-colors hover:brightness-[0.98] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent)]"
                aria-label={copy.chat.demoOtpAria}
                aria-expanded={showOtp}
              >
                {copy.chat.demoOtpButton}
              </button>
            )}
            {panelEnabled && (
              <button
                type="button"
                onClick={onTogglePanel}
                aria-label={copy.chat.sessionButton}
                aria-expanded={panelOpen}
                className="inline-flex size-11 items-center justify-center gap-1.5 rounded-lg border border-[var(--input-border)] bg-[var(--surface)] text-[13px] font-medium text-[var(--text)] transition-colors hover:bg-[var(--avatar-bg)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent)] sm:h-9 sm:w-auto sm:px-3"
              >
                <PanelRight size={16} aria-hidden="true" />
                <span className="hidden sm:inline">
                  {copy.chat.sessionButton}
                </span>
              </button>
            )}
            <button
              type="button"
              onClick={onNewChat}
              className="rounded-lg border border-[var(--input-border)] bg-[var(--surface)] px-3 py-1.5 text-[13px] font-medium text-[var(--text)] transition-colors hover:bg-[var(--avatar-bg)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent)]"
            >
              {copy.chat.newChatButton}
            </button>
          </div>
        </div>
      </header>

      <MessageList
        messages={chat.messages}
        restoring={chat.restoring}
        loading={chat.loading}
        chatId={chat.chatId}
        onSend={chat.submit}
        onQuickMessage={chat.submit}
        onRetry={chat.retry}
      />

      <Composer
        input={chat.input}
        setInput={chat.setInput}
        loading={chat.loading}
        restoring={chat.restoring}
        chatId={chat.chatId}
        notice={chat.notice}
        incompleteNote={chat.incompleteNote}
        error={chat.error}
        restoreFailed={chat.restoreFailed}
        verificationExpired={verificationExpired}
        showOtp={showOtp}
        otpLine={otpLine}
        onSubmit={chat.submit}
        onStop={chat.stop}
        onRetryRestore={chat.retryRestore}
        onNewChat={onNewChat}
      />
    </div>
  );
}
