import type { HistoryPayload, StreamEvent } from "@/core/contract";

/** The only transport surface the chat feature knows about. */
export interface ChatTransport {
  createChat(): Promise<string>;
  deleteChat(id: string): Promise<void>;
  sendMessage(
    id: string,
    text: string,
    signal?: AbortSignal
  ): AsyncIterable<StreamEvent>;
  loadHistory(id: string): Promise<HistoryPayload>;
  getDevOtp(id: string): Promise<string>;
}

export class ChatExpiredError extends Error {
  constructor() {
    super("chat_expired");
    this.name = "ChatExpiredError";
  }
}

export class ValidationError extends Error {
  detail: string;

  constructor(detail: string) {
    super(detail || "Message failed");
    this.name = "ValidationError";
    this.detail = detail;
  }
}

export class NetworkError extends Error {
  detail: string;

  constructor(detail: string) {
    super(detail || "Network error");
    this.name = "NetworkError";
    this.detail = detail;
  }
}
