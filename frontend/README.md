# Learning section (frontend)

Vite + React 19 + TypeScript. It builds two outputs:

- A **standalone app** in `dist/app`.
- An **embeddable library** `@minicode/learning-section` in `dist/lib`, which exports `<LearningSection basePath apiBaseUrl msalInstance? />`.

See [../docs/week4-frontend.md](../docs/week4-frontend.md) for the local full-stack demo, the env settings, the portal integration contract and the open questions.

```powershell
npm ci
npm run dev          # http://localhost:5173, /api proxied to the backend on :7071 (AUTH_MODE=dev)
npm run lint; npm run typecheck; npm test
npm run build        # dist/app + dist/lib
```
