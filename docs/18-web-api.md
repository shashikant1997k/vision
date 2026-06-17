# Read-only monitoring REST API + web dashboard

Legacy GMP vision software is desktop-only. This exposes the line over HTTP for
remote monitoring (QA/MES dashboards, a phone on the floor) WITHOUT widening the
Part-11 surface — it is **strictly read-only**, so no GxP record is created over
the web and the validation footprint stays minimal. Stdlib only (no new deps).

Enable in **Comms… → Read-only web monitoring**: tick enable, set a port (default
9480) and a bearer token. Open `http://<line-pc>:9480/` for the dashboard.

## Security model
- **GET-only** — every write verb returns `405` (the handlers don't exist).
- **Bearer token** required on every `/api/*` route (constant-time compare); the
  dashboard HTML page itself is served without a token, then prompts for it.
- Runs on its own threads; reads thread-safe snapshots / the DB, so a slow client
  never stalls inspection.
- Production: put it behind TLS and bind to localhost / the plant VLAN — never a
  routable internet path. Access is counted/auditable.

## Endpoints (all GET, JSON)
| Endpoint | Returns |
|---|---|
| `GET /` | the live dashboard (HTML/JS, polls the API) |
| `GET /api/status` | running state, batch, recipe, alarm + server UTC |
| `GET /api/counters` | total / passed / failed / yield |
| `GET /api/batches` | recent batches (summary) |
| `GET /api/batch/{id}` | full batch report incl. reconciliation |
| `GET /api/oee/{id}` | OEE = availability × performance × quality |
| `GET /api/reconciliation/{id}` | reconciliation figures + verdict |
| `GET /api/events` | recent operational events |
| `GET /api/audit` | read-only audit-trail projection |

Example: `curl -H "Authorization: Bearer <token>" http://line-pc:9480/api/counters`
