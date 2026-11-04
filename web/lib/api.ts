import { config } from "@/lib/config";

interface ChatResponse {
  chat_id: string;
}

interface MessageBody {
  message: string;
}

interface MessageResponse {
  reply: string;
  error?: boolean;
}

interface OtpResponse {
  otp_line: string;
}

export interface ChatHistoryResponse {
  messages: unknown[];
  panel: unknown;
}

export async function createChat(): Promise<string> {
  const res = await fetch(`${config.apiUrl}/chats`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
  });
  if (!res.ok) throw new Error("Failed to create chat");
  const data = (await res.json()) as ChatResponse;
  return data.chat_id;
}

export async function deleteChat(chatId: string): Promise<void> {
  const res = await fetch(`${config.apiUrl}/chats/${chatId}`, {
    method: "DELETE",
  });
  if (!res.ok && res.status !== 404) throw new Error("Failed to delete chat");
}

export async function sendMessage(
  chatId: string,
  message: string
): Promise<MessageResponse> {
  const res = await fetch(`${config.apiUrl}/chats/${chatId}/messages`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message } as MessageBody),
  });
  if (res.status === 404) {
    const err = await res.json().catch(() => ({ detail: "" }));
    if (err.detail === "chat_expired") {
      throw new ChatExpiredError();
    }
    throw new Error(err.detail || "Chat not found");
  }
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: "" }));
    throw new Error(err.detail || "Message failed");
  }
  return (await res.json()) as MessageResponse;
}

export async function getChatHistory(
  chatId: string
): Promise<ChatHistoryResponse> {
  const res = await fetch(`${config.apiUrl}/chats/${chatId}/history`);
  if (!res.ok) {
    const body = (await res.json().catch(() => ({}))) as { detail?: string };
    if (res.status === 404 && body.detail === "chat_expired") {
      throw new ChatExpiredError();
    }
    throw new Error(body.detail || "Failed to load chat history");
  }
  return (await res.json()) as ChatHistoryResponse;
}

export async function getOtpLine(chatId: string): Promise<string> {
  const res = await fetch(`${config.apiUrl}/chats/${chatId}/dev-otp`);
  if (res.status === 404) {
    const body = (await res.json().catch(() => ({}))) as { detail?: string };
    if (body.detail === "chat_expired") throw new ChatExpiredError();
    throw new Error(body.detail || "OTP unavailable");
  }
  if (!res.ok) throw new Error("OTP unavailable");
  const data = (await res.json()) as OtpResponse;
  return data.otp_line;
}

export class ChatExpiredError extends Error {
  constructor() {
    super("chat_expired");
  }
}
