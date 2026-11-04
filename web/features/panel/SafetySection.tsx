import { copy } from "@/core/config";
import { Section } from "@/features/panel/panel-ui";

export function SafetySection() {
  return (
    <Section title={copy.panel.safetyTitle} className="border-b-0">
      <p className="text-[13px] leading-snug text-[var(--muted)]">
        {copy.panel.safetyStorage}
      </p>
      <p className="mt-2 text-[13px] leading-snug text-[var(--muted)]">
        {copy.panel.safetyPin}
      </p>
    </Section>
  );
}
