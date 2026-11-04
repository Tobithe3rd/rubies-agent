import { cn } from "@/lib/utils";
import { copy } from "@/core/config";
import type { PanelState } from "@/core/contract";
import { OUTLINED_BUTTON, Section } from "@/features/panel/panel-ui";

export function SessionSection({
  panel,
  remaining,
  expired,
  verified,
  onEndChat,
}: {
  panel: PanelState;
  remaining: number | null;
  expired: boolean;
  verified: boolean;
  onEndChat: () => void;
}) {
  return (
    <Section title={copy.panel.sessionTitle}>
      <div className="flex items-center gap-2">
        <span
          className={cn(
            "inline-block size-2 rounded-full",
            verified ? "bg-[var(--success)]" : "bg-[var(--muted)]"
          )}
          aria-hidden="true"
        />
        <span
          className={cn(
            "text-[14px] font-medium",
            verified ? "text-[var(--success)]" : "text-[var(--muted)]"
          )}
        >
          {verified ? copy.panel.verified : copy.panel.notVerified}
        </span>
      </div>

      {verified && panel.phone_masked ? (
        <p className="mt-1.5 text-[13px] text-[var(--text)]">
          {panel.phone_masked}
        </p>
      ) : null}

      {verified && remaining !== null ? (
        <p
          className="mt-2 text-[13px] tabular-nums text-[var(--muted)]"
          aria-hidden="true"
        >
          {copy.panel.expiresPrefix}
          {String(Math.floor(remaining / 60)).padStart(2, "0")}:
          {String(remaining % 60).padStart(2, "0")}
        </p>
      ) : null}

      {expired ? (
        <p className="mt-2 text-[13px] text-[var(--muted)]">
          {copy.panel.expired}
        </p>
      ) : null}

      <button
        type="button"
        onClick={onEndChat}
        className={cn(OUTLINED_BUTTON, "mt-4 w-full")}
      >
        {copy.panel.endChat}
      </button>
      <p className="mt-2 text-[12px] text-[var(--muted)]">
        {copy.panel.notSaved}
      </p>
    </Section>
  );
}
