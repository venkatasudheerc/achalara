# Backend Gaps

This file documents data the frontend needs that the current backend API does not expose.
Each entry includes: what the UI needs, the suggested endpoint + response shape, and which screen is blocked.

---

## 1. Authentication / multi-user

**UI need:** Login, session management, user accounts.
**Current workaround:** Single-user mode. The Axios client has an interceptor seam at `src/api/client.ts` (commented out) where a bearer token can be injected.
**Suggested:** OAuth2 / JWT via a `/api/v1/auth/` namespace.
**Blocked screen:** `SettingsPage` — placeholder shown.

---

## 2. Sync log filtering by sleeve

**UI need:** The Imports page would benefit from filtering sync logs by sleeve, not just client.
**Suggested endpoint extension:**
```
GET /api/v1/admin/sync-logs?client_id=&sleeve_id=&skip=&limit=
```
**Blocked screen:** `ImportsPage` — currently shows all logs for a client.
