import { ChatExpiredError } from "@/lib/api";
import { config } from "@/lib/config";

export type StepStatus = "running" | "done" | "failed" | "awaiting";

export interface Step {
  id: string;
  status: StepStatus;
  label: string;
}

export interface Citation {
  document: string;
  section: string;
}

export interface StreamHandlers {
  onStep?: (step: Step) => void;
  onText?: (delta: string) => void;
  onDone?: (citations: Citation[]) => void;
  onError?: (message: string) => void;
}

export class StreamHttpError extends Error {
  status: number;
  detail: string;

  constructor(status: number, detail: string) {
    super(detail || "Message failed");
    this.name = "StreamHttpError";
    this.status = status;
    this.detail = detail;
  }
}

interface ParsedEvent {
  event: string;
  data: string;
}

function parseEvent(raw: string): ParsedEvent | null {
  let event = "message";
  const data: string[] = [];

  for (const line of raw.split("\n")) {
    if (!line || line.startsWith(":")) continue;
    const colon = line.indexOf(":");
    const field = colon === -1 ? line : line.slice(0, colon);
    let value = colon === -1 ? "" : line.slice(colon + 1);
    if (value.startsWith(" ")) value = value.slice(1);

    if (field === "event") event = value;
    else if (field === "data") data.push(value);
  }

  if (data.length === 0) return null;
  return { event, data: data.join("\n") };
}

/**
 * POST a message and consume the adapter's SSE stream.
 * HTTP failures (chat_expired, 400) are thrown before reading the body.
 */
export async function streamMessage(
  chatId: string,
  message: string,
  handlers: StreamHandlers,
  signal?: AbortSignal
): Promise<void> {
  const res = await fetch(`${config.apiUrl}/chats/${chatId}/messages/stream`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Accept: "text/event-stream",
    },
    body: JSON.stringify({ message }),
    signal,
  });

  if (!res.ok) {
    const body = (await res.json().catch(() => ({}))) as { detail?: string };
    if (res.status === 404 && body.detail === "chat_expired") {
      throw new ChatExpiredError();
    }
    throw new StreamHttpError(res.status, body.detail || "Message failed");
  }

  if (!res.body) throw new Error("Stream unavailable");

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let finished = false;

  const dispatch = (parsed: ParsedEvent) => {
    let payload: unknown;
    try {
      payload = JSON.parse(parsed.data);
    } catch {
      return;
    }
    if (!payload || typeof payload !== "object") return;

    if (parsed.event === "step") {
      const step = payload as Partial<Step>;
      if (
        typeof step.id === "string" &&
        typeof step.label === "string" &&
        (step.status === "running" ||
          step.status === "done" ||
          step.status === "failed" ||
          step.status === "awaiting")
      ) {
        handlers.onStep?.({
          id: step.id,
          status: step.status,
          label: step.label,
        });
      }
    } else if (parsed.event === "text") {
      const delta = (payload as { delta?: unknown }).delta;
      if (typeof delta === "string" && delta) handlers.onText?.(delta);
    } else if (parsed.event === "done") {
      const citations = (payload as { citations?: unknown }).citations;
      handlers.onDone?.(Array.isArray(citations) ? (citations as Citation[]) : []);
      finished = true;
    } else if (parsed.event === "error") {
      const detail = (payload as { message?: unknown }).message;
      handlers.onError?.(
        typeof detail === "string" && detail ? detail : "Something went wrong."
      );
      finished = true;
    }
  };

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });
    buffer = buffer.replace(/\r\n/g, "\n");

    let boundary = buffer.indexOf("\n\n");
    while (boundary !== -1) {
      const raw = buffer.slice(0, boundary);
      buffer = buffer.slice(boundary + 2);
      const parsed = parseEvent(raw);
      if (parsed) dispatch(parsed);
      boundary = buffer.indexOf("\n\n");
    }
  }

  buffer += decoder.decode();
  const rest = parseEvent(buffer.replace(/\r\n/g, "\n"));
  if (rest) dispatch(rest);

  if (!finished) throw new Error("Stream interrupted");
}
