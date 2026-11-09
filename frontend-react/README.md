# The app (frontend-react)

React, TypeScript, Vite, Tailwind and shadcn. The backend serves the built
files from `dist/`; `../run.sh` and the `Dockerfile` build them.

```bash
npm install
npm run dev      # Vite on :5173, /api proxied to the backend on :8000 (CFO_API to change it)
npm run build    # type-check, then build to dist/
npm run lint     # oxlint
```

| Path | What it is |
|---|---|
| `src/App.tsx` | The login gate, the shell and the hash routes (`#`, `#ny`, `#c/<id>`, `#saker`, `#selskapet`, `#helsesjekk`, `#maling`, `#godkjenn/<token>`) |
| `src/pages/` | One file per page; `brief.tsx` is the front page |
| `src/components/` | The page's own parts; `ui/` is shadcn's, added with `npx shadcn add` |
| `src/lib/api.ts` | Every `/api` route the pages read, with its type |
| `src/lib/auth.ts` | Supabase sign-in and `authFetch`: the one file that knows the provider |
| `src/store/conversations.tsx` | The chats, kept in the browser, and the stream that fills them |
