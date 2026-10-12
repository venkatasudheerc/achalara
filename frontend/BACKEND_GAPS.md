# Backend Gaps

This file documents data the frontend needs that the current backend API does not expose.
Each entry includes: what the UI needs, the suggested endpoint + response shape, and which screen is blocked.

---

## 1. Sync log filtering by sleeve

**UI need:** The Imports page would benefit from filtering sync logs by sleeve, not just client.
**Suggested endpoint extension:**
```
GET /api/v1/admin/sync-logs?client_id=&sleeve_id=&skip=&limit=
```
**Blocked screen:** `ImportsPage` — currently shows all logs for a client.
