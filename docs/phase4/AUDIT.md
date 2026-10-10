# Phase 4A: existing system audit (2026-10-10)

Audit completed before implementation. Git started clean at `970db6c`.
Database revision: `0011_smart_rules`, 60 public tables. Backend/frontend,
PostgreSQL, Redis, worker and scheduler are available. Safety remains:
`ACTIONS_ENABLED=false`, `LOCAL_READ_ONLY=true`, `AI_ENABLED=false`,
`AI_AUTOPILOT_ALLOWED=false`; Meta disconnected, MetricFlow READ enabled.

## Existing Action Engine Audit

- `services/actions/engine.py`: implemented durable queue, actor/workspace,
  state freshness and baseline checks, idempotency, pending entity uniqueness,
  quota reservation, audit, no automatic retry after uncertain outcome, READ
  verification. Legacy statuses are lowercase. No manual draft lifecycle yet.
- `action_requests`, `action_executions`, `action_logs`: implemented. Requests
  already support JSON provenance. Reuse them; simulations must not create
  executions or change advertising facts.
- `services/providers/contracts.py::ActionProviderRouter`: disabled contract
  only. No WRITE routing/failover. READ routing is separately implemented.
- `services/metricflow/writer.py`: POST-only, separate write key, no retry.
  Budget body requires a verified contract. Transport currently lacks an
  environment safety check immediately before HTTP; harden this boundary.
- `services/actions/providers.py`: static endpoint assumptions are not runtime
  verification. Do not present them as available LIVE capabilities.
- `services/meta/provider.py`: implemented READ provider, disabled WRITE contract.
  No Meta LIVE credentials. Provider connections, health, quotas, revisions and
  encrypted READ credentials already exist and must remain independent.
- Auth: session/workspace/CSRF and Redis rate limits implemented; authenticated
  legacy actions are blocked. Add only a narrow local manual-control namespace.
  Operators need a separate manual grant, not the existing rule/economics grant.
- Smart Rule Engine: immutable local DRY RUNs; no advertising queue. Reuse their
  saved IDs/version/reasons to prepare an explicit user-requested AD draft only.

## MetricFlow WRITE Capabilities

[Public documentation](https://metricflowit.click/docs), retrieved 2026-10-10,
lists `POST /api/v1/entities/{entity_id}/pause`, `/enable`, `/budget`, Bearer
authentication and `campaigns:write`. Exact WRITE entity-ID namespace is not
specified; the local writer assumes numeric IDs observed by READ. GET account
ads catalog is available for status discovery with `campaigns:read`.

| Operation | Documented route | Phase 4A capability |
| --- | --- | --- |
| Pause Ad | POST /api/v1/entities/{entity_id}/pause | UNVERIFIED; LIVE BLOCKED |
| Enable Ad | POST /api/v1/entities/{entity_id}/enable | UNVERIFIED; LIVE BLOCKED |
| Get Ad Status | GET /api/v1/ad-accounts/{ad_account_id}/ads | Existing verified READ mapping |
| Set AdSet/Campaign Budget | POST /api/v1/entities/{entity_id}/budget | UNVERIFIED, future only |
| Set Bid | No confirmed public route | UNVERIFIED, future only |
| Get Operation Result | No confirmed dedicated route | UNVERIFIED; future READ reconciliation |

Pause/enable bodies, exact response schema, operation errors, idempotency support
and operation-specific limits are not sufficiently documented. Public docs
explicitly mention 402/429; the local transport also handles 401/403, whose exact
provider operation schemas remain unconfirmed. READ quota
stays 800/day locally. No WRITE probe was made; READ key is never a WRITE key.
Context7 had no matching MetricFlow library; unrelated matches were not used.

## Meta WRITE Capabilities

Context7 official `/websites/developers_facebook_marketing-api` confirms
`POST https://graph.facebook.com/{version}/{ad_id}` with status PAUSED/ACTIVE,
access token and a success boolean example. Configured/effective state must be
read back; enabling an AD does not prove delivery while parents are paused.
Runtime permission, version, access and limits are unverified in this workspace;
Meta remains DISCONNECTED and LIVE BLOCKED. Budgets/bids are future only.
[Official status documentation](https://developers.facebook.com/docs/marketing-api/best-practices/manage-your-ad-object-status).

## Database Migration

Verified backup BEFORE project changes:
`backups/phase4-20261010T044239Z.dump`.
SHA256 `130e6e15597b44fa0d83e6e66eae5e2f967a1833e3c558d85b11257c5223fe2f`.
Restored to isolated `mcc_phase4_20261010_044239`; all 60 table counts and full
row hashes matched. Existing action rows and fact hashes are included in the
private checkpoint `.tools/phase4-20261010T044239Z/before.json`.

## Implementation decisions

Extend ActionEngine with local draft methods backed by existing request/log
tables. Store immutable captured provider/identity/revisions/confirmation and
preflight evidence in provenance; add a request revision and separate grants.
Entity row locks plus a unique pending index protect concurrency. Credentials
are never read by local simulations. Missing WRITE availability allows only
explicitly confirmed LOCAL simulation; identity/freshness failures block it.
All execution paths require a central environment gate before provider HTTP.
No real execution implementation is enabled in Phase 4A.
