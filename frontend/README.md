# AI Stylist — Frontend

Next.js 14 (App Router) + TypeScript + Tailwind CSS.
First UI for the AI Stylist backend that lives in `../ai-stylist-starter`.

## Stack

- **Next.js 14** (App Router, RSC where useful, client components for forms)
- **TypeScript** (strict)
- **Tailwind CSS** (custom tokens in `tailwind.config.ts`)
- **@tanstack/react-query** for server state
- **Zod** for response validation

## Setup

```bash
cd frontend
cp .env.local.example .env.local      # set NEXT_PUBLIC_API_URL if not localhost
npm install
npm run dev                           # http://localhost:3000
```

The backend is expected on `http://localhost:8000` by default.

## Routes

| Path        | Screen              | Backend                       |
|-------------|---------------------|-------------------------------|
| `/`         | Landing             | —                             |
| `/sign-in`  | Local-session view  | (no backend call yet)         |
| `/analyze`  | 3-photo upload      | `POST /user/analyze`          |
| `/wardrobe` | List + upload       | `GET /wardrobe/items`, `POST /wardrobe/upload` |
| `/outfits`  | Outfit feed         | `POST /outfits/generate`      |
| `/today`    | Daily 3 cards       | `GET /today`                  |
| `/insights` | Weekly insights     | `GET /insights/weekly`        |
| `/tryon`    | Try-on MVP          | `POST /tryon/generate`        |

## Auth (placeholder)

The backend currently identifies users via the `X-User-Id` header (see
`ai-stylist-starter/app/api/deps.py`). The frontend mints a stable UUID
on first visit, persists it in `localStorage`, and sends it on every
request. Real JWT auth replaces this when sign-in lands.

## Folder layout

```
src/
├── app/                # routes (App Router)
│   ├── (auth)/         # public auth screens
│   └── (app)/          # signed-in shell with nav
├── components/
│   ├── ui/             # primitives (Button, Card, Input, …)
│   ├── layout/         # AppShell, NavBar, MobileNav, PageHeader
│   └── <feature>/      # feature-scoped presentational components
├── lib/
│   ├── api/            # one file per backend resource
│   ├── schemas/        # Zod schemas mirroring backend responses
│   ├── user-id.ts      # local-session UUID helper (sent as X-User-Id)
│   ├── local-store.ts  # localStorage cache for cross-screen state
│   └── cn.ts
└── providers/          # React Query provider
```

## Conventions

- Pages stay thin: data fetching + composition. No business logic.
- All API calls go through `lib/api/client.ts` (`apiRequest`) so the auth
  header, base URL, and error mapping live in one place.
- Responses are parsed through Zod schemas with `.passthrough()` so the UI
  doesn't break when the backend adds fields.
- Loading / error / empty states use the shared `<QueryState />` helper.
