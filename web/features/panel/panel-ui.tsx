import {
  type ReactNode,
} from "react";
import { Check, Copy, CreditCard, FileText, Headphones } from "lucide-react";
import { cn } from "@/lib/utils";
import { copy } from "@/core/config";
import type { ReceiptKind } from "@/core/contract";

export const SECTION_TITLE =
  "text-[12px] font-semibold uppercase tracking-[0.06em] text-[var(--muted)]";

export const OUTLINED_BUTTON =
  "inline-flex min-h-11 items-center justify-center gap-2 rounded-lg border border-[var(--input-border)] bg-[var(--surface)] px-3 text-[13px] font-medium text-[var(--text)] transition-colors hover:bg-[var(--avatar-bg)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent)] disabled:cursor-not-allowed disabled:opacity-50 sm:min-h-9";

export const ICON_BUTTON =
  "inline-flex size-11 shrink-0 items-center justify-center rounded-lg text-[var(--muted)] transition-colors hover:bg-[var(--avatar-bg)] hover:text-[var(--text)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent)] sm:size-9";

export function Section({
  title,
  children,
  className,
}: {
  title: string;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={cn("border-b border-[var(--border)] px-4 py-4", className)}>
      <h2 className={SECTION_TITLE}>{title}</h2>
      <div className="mt-3">{children}</div>
    </section>
  );
}

export function ReceiptIcon({ kind }: { kind: ReceiptKind }) {
  if (kind === "card_block") {
    return <CreditCard size={14} className="shrink-0 text-[var(--muted)]" />;
  }
  if (kind === "handoff") {
    return <Headphones size={14} className="shrink-0 text-[var(--muted)]" />;
  }
  return <FileText size={14} className="shrink-0 text-[var(--muted)]" />;
}

export function CopyButton({
  value,
  label,
  copied,
  onCopy,
}: {
  value: string;
  label: string;
  copied: boolean;
  onCopy: (value: string) => void;
}) {
  return (
    <button
      type="button"
      onClick={() => onCopy(value)}
      className="inline-flex min-h-11 shrink-0 items-center gap-1 rounded-md px-2 text-[12px] font-medium text-[var(--muted)] transition-colors hover:text-[var(--text)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent)] sm:min-h-7"
      aria-label={`${copy.panel.copyAria}${label}`}
    >
      {copied ? <Check size={13} /> : <Copy size={13} />}
      {copied ? copy.panel.copied : copy.panel.copy}
    </button>
  );
}
