"use client";

import { copy } from "@/core/config";

export function QuickReplies({
  replies,
  disabled,
  onReply,
}: {
  replies: readonly string[];
  disabled: boolean;
  onReply: (reply: string) => void;
}) {
  return (
    <div className="mt-2 flex flex-wrap gap-2">
      {replies.map((reply) => (
        <button
          key={reply}
          type="button"
          disabled={disabled}
          onClick={() => onReply(reply)}
          className="inline-flex min-h-11 items-center rounded-full border border-[var(--input-border)] bg-[var(--surface)] px-3.5 text-[13px] font-medium text-[var(--text)] transition-colors hover:bg-[var(--avatar-bg)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent)] disabled:cursor-not-allowed disabled:opacity-50 sm:min-h-9"
        >
          {reply}
        </button>
      ))}
    </div>
  );
}
