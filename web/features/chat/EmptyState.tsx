"use client";

import { Suggestion } from "@/components/ai-elements/suggestion";
import { config, copy, starterPrompts } from "@/core/config";

export function EmptyState({
  disabled,
  onSend,
}: {
  disabled: boolean;
  onSend: (message: string) => void;
}) {
  return (
    <div className="flex flex-col items-center justify-center px-2 py-12 text-center">
      <div
        className="flex size-12 items-center justify-center rounded-[12px] bg-[var(--accent)] text-[21px] font-bold text-white"
        aria-hidden="true"
      >
        {config.logoLetter}
      </div>
      <h2 className="mt-5 text-[26px] font-semibold tracking-[-0.02em]">
        {copy.chat.emptyTitle}
      </h2>
      <p className="mt-2 max-w-md text-[15px] leading-[1.6] text-[var(--muted)]">
        {copy.chat.emptyBody}
      </p>
      <div className="mt-7 flex w-full max-w-[480px] flex-col items-stretch gap-2">
        {starterPrompts.map((suggestion) => (
          <Suggestion
            key={suggestion}
            suggestion={suggestion}
            onClick={onSend}
            disabled={disabled}
            className="h-auto min-h-11 w-full max-w-full justify-start whitespace-normal break-words rounded-full border-[var(--input-border)] bg-[var(--surface)] px-4 py-2 text-left text-[13px] font-normal leading-snug text-[var(--text)] hover:bg-[var(--avatar-bg)] hover:text-[var(--text)]"
          />
        ))}
      </div>
    </div>
  );
}
