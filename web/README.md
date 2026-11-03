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

## Design notes

- No AI Elements CLI used (deprecated; moving to shadcn/ui at end of Nov 2026).
- No database, auth, analytics, or AI SDK `useChat` transport added.
- State managed manually (`useChat` hook in `lib/use-chat.ts`) calling our web adapter JSON endpoints (`lib/api.ts`).
- Markdown rendered by `react-markdown` (with custom component mapping in `components/markdown-renderer.tsx`).
- Component approach mimics the Vercel AI Chatbot structure: message list (`page.tsx`), prompt input (`page.tsx` form), loader dots, header with demo-OTP toggle, new-chat button, error/retry banners.
