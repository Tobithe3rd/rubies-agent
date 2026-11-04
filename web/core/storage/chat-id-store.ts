const CHAT_ID_KEY = "rubies.chatId";

function storage(): Storage | null {
  if (typeof window === "undefined") return null;
  try {
    return window.sessionStorage;
  } catch {
    return null;
  }
}

export function get(): string | null {
  try {
    return storage()?.getItem(CHAT_ID_KEY) ?? null;
  } catch {
    return null;
  }
}

export function set(id: string): void {
  try {
    storage()?.setItem(CHAT_ID_KEY, id);
  } catch {
    // Storage can be blocked; the chat still works for this page load.
  }
}

export function clear(): void {
  try {
    storage()?.removeItem(CHAT_ID_KEY);
  } catch {
    // Storage can be blocked; nothing to clear.
  }
}
