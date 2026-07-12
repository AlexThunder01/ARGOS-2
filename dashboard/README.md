# ARGOS-2 Dashboard

React 19 + Vite frontend for ARGOS-2's web dashboard: a real-time chat terminal (SSE streaming) with multi-chat support, live Docker container monitoring, CPU/RAM telemetry, and a security audit log.

See the main [README](../README.md#web-dashboard) for deployment instructions, and [docs/DEVELOPMENT.md](../docs/DEVELOPMENT.md#4-dashboard-development) for the project structure and frontend conventions (CSS Modules, component layout).

## Local development

```bash
npm install
npm run dev
```

Starts Vite on `localhost:5173`, proxying `/api`, `/run`, `/chat`, and `/status` to the FastAPI backend on `localhost:8000` (see `vite.config.js`).

## Production build

```bash
npm run build
```

Outputs to `dist/`, served automatically by FastAPI's `StaticFiles` — no separate deployment step needed.
