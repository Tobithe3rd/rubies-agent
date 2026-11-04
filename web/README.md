# Rubies MFB Web Frontend

A minimal Next.js chat UI for the Rubies MFB support agent web adapter.

## Versions

- Next.js 16
- React 19
- Tailwind CSS 4
- lucide-react ^0.460.0
- react-markdown ^10.0.0 (renders agent markdown; raw HTML disabled by react-markdown default)
- AI Elements: skipped (deprecated Nov 2026; using shadcn/ui patterns directly)

## Environment variables

Copy `.env.example` to `.env.local`:

```
NEXT_PUBLIC_API_URL=http://localhost:8002
NEXT_PUBLIC_DEMO_OTP=false
```

## Running

The frontend runs independently. Three servers needed simultaneously:

1. Bank API (mock): `python -m uvicorn bank_api.main:create_app --factory --host 127.0.0.1 --port 8001`
2. Web adapter: `python -m adapters.web_chat` (port 8002)
3. Frontend: `pnpm dev` inside `web/` (port 3000)

## Commands

```bash
# Install
cd web
pnpm install

# Development
pnpm dev

# Lint
pnpm lint

# Build
pnpm build
```

## Storage

The browser stores exactly one thing: the current chat ID, in
`sessionStorage` under the key `rubies.chatId`. All access goes through
`lib/chat-id-store.ts` and is wrapped in `try/catch` because storage can be
blocked.

- Never stored in the browser: messages, text, phone numbers, panel data,
  tokens or anything else.
- No `localStorage`, cookies or IndexedDB.
- On load the stored ID is used to restore the chat from
  `GET /chats/{id}/history`. If the chat has expired (404 `chat_expired`), the
  stored ID is cleared, a new chat is created and the notice "Your session
  ended. Started a new chat." is shown. On a network error the stored ID is
  kept and the UI offers Retry instead of creating a new chat.
- "New chat" and "End chat and clear" delete the server chat, clear the stored
  ID and create a new one.

## Design notes

- No AI Elements CLI used (deprecated; moving to shadcn/ui at end of Nov 2026).
- No database, auth, analytics, or AI SDK `useChat` transport added.
- State managed manually (`useChat` hook in `lib/use-chat.ts`) calling our web adapter JSON endpoints (`lib/api.ts`).
- Markdown rendered by `react-markdown` (with custom component mapping in `components/markdown-renderer.tsx`).
- Component approach mimics the Vercel AI Chatbot structure: message list (`page.tsx`), prompt input (`page.tsx` form), loader dots, header with demo-OTP toggle, new-chat button, error/retry banners.
