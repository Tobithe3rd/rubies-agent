import type { HistoryPayload, StreamEvent } from "@/core/contract";
import { parseHistoryPayload, parseStreamEvent } from "@/core/contract";
import { config } from "@/core/config";
import {
  ChatExpiredError,
  NetworkError,
  ValidationError,
  type ChatTransport,
} from "@/core/transport/types";

async function request(url: string, init?: RequestInit): Promise<Response> {
  try {
    return await fetch(url, init);
  } catch (error) {
    throw new NetworkError(
      error instanceof Error ? error.message : "Network error"
    );
  }
}

async function detail(response: Response, fallback: string): Promise<string> {
  const body = (await response.json().catch(() => ({}))) as { detail?: string };
  return body.detail || fallback;
}

async function expiredIfNeeded(response: Response, body: string): Promise<void> {
  if (response.status === 404 && body === "chat_expired") {
    throw new ChatExpiredError();
  }
}

async function createChat(): Promise<string> {
  const response = await request(`${config.apiUrl}/chats`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
  });
  if (!response.ok) throw new NetworkError("Failed to create chat");
  const data = (await response.json()) as { chat_id: string };
  return data.chat_id;
}

async function deleteChat(id: string): Promise<void> {
  const response = await request(`${config.apiUrl}/chats/${id}`, {
    method: "DELETE",
  });
  if (!response.ok && response.status !== 404) {
    throw new NetworkError("Failed to delete chat");
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

function toStreamEvent(parsed: ParsedEvent): StreamEvent | null {
  let payload: unknown;
  try {
    payload = JSON.parse(parsed.data);
  } catch {
    return null;
  }
  return parseStreamEvent(parsed.event, payload);
}

async function* sendMessage(
  id: string,
  text: string,
  signal?: AbortSignal
): AsyncIterable<StreamEvent> {
  const response = await request(
    `${config.apiUrl}/chats/${id}/messages/stream`,
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Accept: "text/event-stream",
      },
      body: JSON.stringify({ message: text }),
      signal,
    }
  );

  if (!response.ok) {
    const body = await detail(response, "Message failed");
    await expiredIfNeeded(response, body);
    if (response.status === 400) throw new ValidationError(body);
    throw new NetworkError(body);
  }
  if (!response.body) throw new NetworkError("Stream unavailable");

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let finished = false;

  const flush = function* (raw: string): Generator<StreamEvent> {
    const parsed = parseEvent(raw);
    if (!parsed) return;
    const event = toStreamEvent(parsed);
    if (event) yield event;
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
      for (const event of flush(raw)) {
        if (event.type === "done" || event.type === "error") finished = true;
        yield event;
      }
      boundary = buffer.indexOf("\n\n");
    }
  }

  buffer += decoder.decode();
  for (const event of flush(buffer.replace(/\r\n/g, "\n"))) {
    if (event.type === "done" || event.type === "error") finished = true;
    yield event;
  }
  if (!finished) throw new NetworkError("Stream interrupted");
}

async function loadHistory(id: string): Promise<HistoryPayload> {
  const response = await request(`${config.apiUrl}/chats/${id}/history`);
  if (!response.ok) {
    const body = await detail(response, "Failed to load chat history");
    await expiredIfNeeded(response, body);
    throw new NetworkError(body);
  }
  const payload = parseHistoryPayload(await response.json());
  if (!payload) throw new NetworkError("Failed to load chat history");
  return payload;
}

async function getDevOtp(id: string): Promise<string> {
  const response = await request(`${config.apiUrl}/chats/${id}/dev-otp`);
  if (!response.ok) {
    const body = await detail(response, "OTP unavailable");
    await expiredIfNeeded(response, body);
    throw new NetworkError(body);
  }
  const data = (await response.json()) as { otp_line: string };
  return data.otp_line;
}

export const httpTransport: ChatTransport = {
  createChat,
  deleteChat,
  sendMessage,
  loadHistory,
  getDevOtp,
};
