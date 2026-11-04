import type { ChatMessage, MessageStatus } from "@/lib/use-chat";
import type { Citation, Step, StepStatus } from "@/lib/stream";

const STEP_STATUSES: StepStatus[] = ["running", "done", "failed", "awaiting"];
const MESSAGE_STATUSES: MessageStatus[] = [
  "streaming",
  "done",
  "stopped",
  "error",
];

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object";
}

function isStep(value: unknown): value is Step {
  if (!isRecord(value)) return false;
  return (
    typeof value.id === "string" &&
    typeof value.label === "string" &&
    STEP_STATUSES.includes(value.status as StepStatus)
  );
}

function isCitation(value: unknown): value is Citation {
  if (!isRecord(value)) return false;
  return (
    typeof value.document === "string" && typeof value.section === "string"
  );
}

function mapAgentEvents(
  events: unknown,
  fallbackStatus: MessageStatus
): {
  text: string;
  steps: Step[];
  citations: Citation[];
  status: MessageStatus;
  canRetry: boolean;
} {
  let text = "";
  let stepsSinceText = false;
  let status = fallbackStatus;
  let sawError = false;
  const steps: Step[] = [];
  const citations: Citation[] = [];

  if (!Array.isArray(events)) {
    return { text, steps, citations, status, canRetry: status !== "done" };
  }

  for (const event of events) {
    if (!isRecord(event)) continue;

    if (event.type === "step" && isStep(event)) {
      stepsSinceText = true;
      const index = steps.findIndex((step) => step.id === event.id);
      const step: Step = {
        id: event.id,
        status: event.status,
        label: event.label,
      };
      if (index === -1) steps.push(step);
      else steps[index] = step;
    } else if (event.type === "text" && typeof event.text === "string") {
      if (!event.text) continue;
      text += (stepsSinceText && text ? "\n\n" : "") + event.text;
      stepsSinceText = false;
    } else if (event.type === "done") {
      if (Array.isArray(event.citations)) {
        for (const citation of event.citations) {
          if (isCitation(citation)) citations.push(citation);
        }
      }
    } else if (event.type === "error") {
      sawError = true;
      status = "error";
      if (!text && typeof event.message === "string") text = event.message;
    }
  }

  if (sawError) status = "error";
  else if (!MESSAGE_STATUSES.includes(status)) status = "done";

  return {
    text,
    steps,
    citations,
    status,
    canRetry: status === "error" || status === "stopped",
  };
}

export function mapHistoryMessages(raw: unknown): ChatMessage[] {
  if (!Array.isArray(raw)) return [];

  return raw.flatMap((value, index): ChatMessage[] => {
    if (!isRecord(value)) return [];

    if (value.role === "user") {
      return [
        {
          id: `history-${index}-user`,
          role: "user",
          text: typeof value.text === "string" ? value.text : "",
          steps: [],
          citations: [],
          status: "done",
        },
      ];
    }

    if (value.role === "agent") {
      const status = MESSAGE_STATUSES.includes(value.status as MessageStatus)
        ? (value.status as MessageStatus)
        : "done";
      const mapped = mapAgentEvents(value.events, status);
      return [
        {
          id: `history-${index}-agent`,
          role: "assistant",
          text: mapped.text,
          steps: mapped.steps,
          citations: mapped.citations,
          status: mapped.status,
          canRetry: mapped.canRetry,
        },
      ];
    }

    return [];
  });
}
