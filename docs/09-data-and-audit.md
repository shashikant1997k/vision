# 09 — Data Persistence & Audit Trail

Implements decision [D-013](decisions/decision-log.md). Code in `src/vis/db/`.

## Engine & portability

- **PostgreSQL + JSONB** in production; **SQLite** for dev/tests (no driver needed → runs on macOS).
- DB chosen via `DATABASE_URL` (default `sqlite:///vis.db`). Access through **SQLAlchemy 2.0**.
- JSON columns use `JSON().with_variant(JSONB, "postgresql")` → JSONB on Postgres, JSON on SQLite.
- Schema: `init_db()` (`create_all`) for dev/tests; **Alembic** migrations for production (scaffolded in `alembic/`; generate the first migration against Postgres).

## Data model (implemented subset)

```
users, roles, user_roles                      access control
products, recipes(versioned), regions, tools  recipe config  (Recipe→Region→Tool, D-010)
batches                                        runtime context
inspection_results → tool_results             per-region results (one frame → N)
   tool_results → code_reads                  parsed GS1 AIs (gtin/batch/expiry/serial) ← serialization hook
   tool_results → grade_results               approximate grade, certified=False (D-012)
esignatures                                    two-meaning electronic signatures
audit_entries                                  append-only, hash-chained
model_versions                                 locked model registry
```

The full target model (Station/Camera/RejectOutput/CameraAssignment/FrameCapture) is in
[docs/04](04-system-architecture.md); those land as the runtime/hardware layer is built out.

## Audit trail — append-only & tamper-evident (`db/audit.py`)

`AuditService.record(...)` writes one entry per change (who / what / when / before → after),
each chained to the previous by hash:

```
entry_hash = sha256( canonical(ts, user, action, entity, before, after) + prev_hash )
```

- **Tamper-evident:** any edit, reorder, or deletion breaks the chain. `verify_chain()` returns
  `(ok, first_broken_id)`. (Demonstrated: editing a stored row → chain breaks at that entry.)
- **Append-only:** the app only inserts. On PostgreSQL, also `REVOKE UPDATE, DELETE` on
  `audit_entries` from the app role so the database enforces it too — not just the code.
- Satisfies the structure required by 21 CFR 11.10(e) (secure, time-stamped, no-delete audit trail).

## How results get persisted (`db/store.py`)

- `ResultStore.on_result` subscribes to the EventBus → writes `InspectionResult` + `ToolResult`
  rows, plus `CodeRead` (parsed GS1) and `GradeResult` where present. Fully decoupled from the engine.
- `RecipeRepository.save_draft` / `approve` — versioned recipes with change control, an
  e-signature on approval, and an audit entry for each action.

## Try it

```bash
# persist a simulated run, then inspect the SQLite file
.venv/bin/python -m vis.cli --source sim --frames 5 --db sqlite:///run.db
```

## Notes / later

- Timestamps are stored as ISO strings for cross-DB hash determinism; production also relies on
  NTP-synced host time. Postgres deployments may switch to `timestamptz` with adjusted hashing.
- Passwords: `password_hash` only (never plaintext); a real hashing/policy layer is still to come.
- Images are stored on the filesystem (path + checksum), never as DB blobs (D-013).
