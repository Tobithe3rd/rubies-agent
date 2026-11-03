"use client";

import { useEffect, useRef, useState } from "react";
import { Check, Clock3, TriangleAlert } from "lucide-react";
import { Loader } from "@/components/ai-elements/loader";
import { cn } from "@/lib/utils";
import type { Step } from "@/lib/stream";

function StepIcon({ status }: { status: Step["status"] }) {
  if (status === "running") {
    return <Loader size={13} className="text-[var(--muted)]" />;
  }
  if (status === "done") {
    return <Check size={14} strokeWidth={2.5} className="text-[var(--success)]" />;
  }
  if (status === "failed") {
    return <TriangleAlert size={14} className="text-[var(--failed-text)]" />;
  }
  return <Clock3 size={14} className="text-[var(--muted)]" />;
}

export function StepPanel({
  steps,
  streaming,
}: {
  steps: Step[];
  streaming: boolean;
}) {
  const [open, setOpen] = useState(streaming);
  const wasStreaming = useRef(streaming);

  // Collapse to the header once the reply finishes; the user can expand again.
  useEffect(() => {
    if (wasStreaming.current && !streaming) setOpen(false);
    wasStreaming.current = streaming;
  }, [streaming]);

  if (steps.length === 0) return null;

  return (
    <section
      className="mb-3 overflow-hidden rounded-[12px] border border-[var(--border)] bg-[var(--surface)]"
      aria-label="What the agent did"
    >
      <div className="flex items-center justify-between gap-3 px-3.5 py-2.5">
        <p className="text-[13px] font-medium text-[var(--text)]">
          What I did · {steps.length} {steps.length === 1 ? "step" : "steps"}
        </p>
        <button
          type="button"
          onClick={() => setOpen((value) => !value)}
          className="rounded-md px-1.5 py-0.5 text-[12px] font-medium text-[var(--muted)] transition-colors hover:text-[var(--text)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent)]"
          aria-expanded={open}
        >
          {open ? "Hide" : "Show"}
        </button>
      </div>

      {open && (
        <ul className="border-t border-[var(--border)] px-1.5 py-1.5">
          {steps.map((step) => (
            <li
              key={step.id}
              className={cn(
                "flex items-center gap-2.5 rounded-lg border border-transparent px-2 py-1.5 text-[13px] leading-snug",
                step.status === "failed" &&
                  "border-[var(--failed-border)] bg-[var(--failed-bg)] text-[var(--failed-text)]"
              )}
            >
              <span className="flex size-4 shrink-0 items-center justify-center">
                <StepIcon status={step.status} />
              </span>
              <span
                className={cn(
                  step.status === "failed"
                    ? "text-[var(--failed-text)]"
                    : "text-[var(--text)]"
                )}
              >
                {step.label}
              </span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
