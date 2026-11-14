---
name: check-impact
description: Check what a change touches before it is called done. Use for every backend change, enhancement or bug fix (models, migrations, services, routes, access rules, jobs, readers, settings) and before committing or opening a pull request: it finds the backend's cross impacts, and carries every backend change through to the frontend (types, hooks, screens, roles, states), with the checks that prove both.
---

# Check the impact of a change

A change is not done when the line you meant to change works. It is done when everything that
reads, writes or shows what you changed still works, and the screens people use show it
correctly. Two guardrails, both always:

1. **Every change or bug fix is checked for cross impacts across the backend.**
2. **Every backend change is carried through to the frontend**: validated there, and enhanced
   where the screens need it.

Run this before `update-docs` and before any commit. Write what you found in the pull request
description under "Impact" (and tell Sai when something could not be checked).

## 1. Say what changed

```sh
git fetch mine main 2>/dev/null; git diff --stat mine/main...HEAD; git status --short
```

Read the diff, not just the names. List each change in **behaviour**: a column added or its
meaning changed, a rule (who sees what, what counts as a gain, what is a duplicate), a route's
request or response, a job's time or effect, a reader's mapping, a setting.

## 2. Backend: find everything it touches

For each change, find its readers and writers and decide, one by one, whether each still holds.
Search, do not remember:

```sh
grep -rn "<column|function|constant|route path>" backend/app backend/tests
```

| When this changes | Check these |
|---|---|
| A model, column or migration | Every query on the table (`grep -rn "Model\.\|<table>" backend/app`); services that build from it (rebuild, ledger, health, status, portal); the fresh-start and earlier migrations' assumptions; `upgrade` **and** `downgrade` run on a copy of the local database; tests that build the table by hand |
| Who may see or do what (`deps.py`, `AuthService`, guardrails, roles) | Every router's mount and route that bypasses the path rule (portal, `/trades/*`, `/auth/*`); admin, advisor and client each, and a staff preview (`as_client`); that a client never reaches another client's data; `tests/test_roles.py`, `test_auth.py`, `test_portal*.py` |
| A rule in a calculation (performance, opening position, cash, health, tax lots) | Every caller of the function and every screen figure built on it; observed days stay fact; opening trades stay derived and out of activity, matching and dedup (`NOT_OPENING`); the money-weighted and time-weighted returns, the summaries' opening value, monthly periods; a rebuild of the local accounts compared before and after (counts and since-inception figures), and why each difference is right |
| A feed or file reader (Plaid, the custodian's report) | Ingestion's dedup (`_ID_AUTHORITATIVE_SOURCES`, report keys), the cash ledger (`cash_amount`, `is_external_flow`), routing to sleeves, skipped rows counted, the record's health; a payload recorded from a real response where one exists |
| A route or its request/response | `openapi.yaml` (the contract test fails otherwise), every caller in `frontend/src/api/`, the access rule for it |
| A job or its schedule | `scheduler.py`, `status_service.JOBS` and System status, what it writes and what reads that, a server that was down at that time |
| A setting | `config.py`, `deploy/.env.example`, `docker-compose.yml`, what happens when it is empty |
| Deleting anything (data, a column, a route, a feature) | Everything that referenced it (backend, frontend, tests, docs, `openapi.yaml`); production data the deploy will touch, with a dry run against a copy of the local database inside a rolled-back transaction |

Then prove it:

- `backend/venv/bin/pytest backend/tests -q` — the **whole** suite, never only the file you
  touched.
- A test for the new behaviour and one for the case that must not change, each failing without
  the change (check that once).
- `backend/venv/bin/python -m flake8 --select=F <changed files>`.
- Where a change moves figures, run it on the local data and compare before and after.

## 3. Frontend: carry every backend change through

A backend change is not finished until the frontend has been checked against it. For each
change to a route, response field, rule or role:

1. **Find the consumers.** `grep -rn "<route|field>" frontend/src` — the endpoint wrapper
   (`src/api/endpoints/`), the hand-written type (`src/api/types.ts`), the hook
   (`src/hooks/`), and every screen that reads it.
2. **Regenerate and align types.** `cd frontend && npm run gen:api`, then make `types.ts` match
   `openapi.yaml` exactly (field names, nullability, enums such as roles).
3. **Decide what the screens need**, and do it in the same change:
   - a new field the person should see or act on (show it where it belongs, in plain words);
   - a removed or renamed field or route (nothing may still call it);
   - a new rule or refusal (the button is hidden where the API refuses it, and a refusal's
     message is shown, not swallowed);
   - every role that can reach the screen: admin, advisor, client, and an admin or advisor
     previewing a client (`?as=`); the preview must show exactly what the client sees;
   - every state: loading, empty, error, incomplete or provisional records, and none of the
     figures shown where the record is not trusted.
4. **Prove it.** `cd frontend && npm run build`; screenshots of each changed screen at 390 and
   1440, light and dark (`ACHALARA_SESSION=<token> node scripts/screens.mjs <out> <route…>`),
   looked at as the family member who will read it (`feedback` memory: the UX bar).

If a backend change needs no frontend change, say why in the Impact notes (for example, an
internal refactor with identical responses).

## 4. Report

In the pull request (and to Sai):

- **Impact**: what else the change touched, backend and frontend, and how each was checked.
- **Not checked**: anything that could not be, and why (no real data, needs the server).
- **Changed on purpose**: figures or behaviour that differ afterwards, with the reason.

Then run `update-docs`.
