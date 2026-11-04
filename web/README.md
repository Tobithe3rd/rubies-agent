# Rubies MFB Web Frontend

A minimal Next.js chat UI for the Rubies MFB support agent web adapter.

## Versions

- Next.js 16
- React 19
- Tailwind CSS 4
- lucide-react ^0.460.0
- react-markdown ^10.0.0 (renders agent markdown; raw HTML disabled by react-markdown default)
- AI Elements: vendored sources in `components/ai-elements`; do not edit them
- Vitest for unit tests

## Environment variables

Copy `.env.example` to `.env.local`:

```
NEXT_PUBLIC_API_URL=http://localhost:8002
NEXT_PUBLIC_DEMO_OTP=false
NEXT_PUBLIC_TRANSPORT=http
```

## Running

### Real backend (default)

Three servers needed simultaneously:

1. Bank API (mock): `python -m uvicorn bank_api.main:create_app --factory --host 127.0.0.1 --port 8001`
2. Web adapter: `python -m adapters.web_chat` (port 8002)
3. Frontend: `pnpm dev` inside `web/` (port 3000)

The default `NEXT_PUBLIC_TRANSPORT=http` uses the real adapter.

### Mock transport (no backend)

```bash
cd web
NEXT_PUBLIC_TRANSPORT=mock pnpm dev
```

The mock is scripted and never calls `fetch`. It covers a fee answer with
sources, a lost-card verification/awaiting/executed flow with a receipt, a
failing tool, a human handoff with a ticket, and an expired chat.

## Commands

```bash
cd web
pnpm install
pnpm dev
pnpm lint
pnpm build
pnpm test
```

## Architecture

```
web/
├── app/                 composition only; may import everything
│   ├── page.tsx         thin entry point
│   └── chat-app.tsx     wires chat + panel through props
├── core/                no React, no feature or app imports
│   ├── contract.ts      event, history, panel and receipt types + guards
│   ├── config/          brand, copy, prompts, tasks, env/feature flags
│   ├── reducer/         pure chat reducer + history-to-state mapping
│   ├── storage/         the one chat-id store
│   └── transport/       contract, http (fetch/SSE), mock, factory
├── features/
│   ├── chat/            chat screen, messages, steps, sources, composer
│   └── panel/           session panel shell and sections
├── components/ui/       generated shadcn primitives (exempt)
├── components/ai-elements/  generated/vendored sources (exempt)
└── lib/utils.ts         shadcn's cn helper
```

### Folder rules

- `core/` holds contract, transport, config, reducer and storage. It must not
  import React components, `features/` or `app/`.
- `features/chat/` and `features/panel/` may import `core/` and `components/ui/`
  but never each other. The panel receives `PanelState` and callbacks as props.
- `app/` is composition only and may import everything.
- The only place that calls `fetch` is `core/transport/http.ts`.
- The only place that touches browser storage is `core/storage/chat-id-store.ts`.
- Every web file stays at or under 250 lines of code (non-blank, non-comment).
  Generated `components/ui`, `components/ai-elements`, build output and the
  lockfile are exempt.

Check the line rule from the repo root:

```bash
python scripts/checks/check_web_file_size.py --scope all
```

## Contract and transport

`core/contract.ts` is the single source of truth for the payload shapes sent by
`adapters/web`: `step`, `text`, `done`, `panel`, `error`, the history payload,
`PanelState` and `Receipt`. Runtime guards parse every incoming stream event and
history payload.

`core/transport/types.ts` defines `ChatTransport`:

- `createChat()`
- `deleteChat(id)`
- `sendMessage(id, text, signal)` → async iterable of typed events
- `loadHistory(id)`
- `getDevOtp(id)`

Typed failures are `ChatExpiredError`, `ValidationError` and `NetworkError`.
`core/transport/index.ts` selects `http` by default or `mock` when
`NEXT_PUBLIC_TRANSPORT=mock`.

Fixtures shared with the backend live at the repo root in `contract/events.json`
and `contract/fixtures/`. A change to either side fails a Vitest or pytest.
The reducer's state holds messages (including their steps and citations), the
panel, status and notices. It applies the paragraph-break rule for text after a
step and maps history into the same message shape as live streaming.

## Storage

The browser stores exactly one thing: the current chat ID, in `sessionStorage`
under the key `rubies.chatId`. All access goes through
`core/storage/chat-id-store.ts` and is wrapped in `try/catch` because storage
can be blocked.

- Never stored in the browser: messages, text, phone numbers, panel data,
  credentials or anything else.
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
- No database, auth, analytics, or AI SDK transport added.
- State is managed by the pure reducer; the hook only wires reducer, transport
  and the chat-id store.
- Markdown rendered by `react-markdown` with custom mapping in
  `features/chat/markdown-renderer.tsx`.
- Tool names are never shown to the customer; steps use configured labels.
- The accent colour stays reserved for primary actions and the ruby identity.
