# METRICFLOW WRITE API AUDIT & INTEGRATION READINESS

Audit date: 2026-10-11. Scope: local implementation, public provider documentation,
mock transports, isolated databases and browser acceptance. No authenticated
provider probe or advertising WRITE was performed by this audit. Existing READ
workers continued normal synchronization except during integrity-controlled E2E.

## 1. Executive Summary

```text
PHASE 4A MANUAL CONTROL: READY
METRICFLOW WRITE API: UNVERIFIED
METRICFLOW WRITE PERMISSIONS: UNVERIFIED
PHASE 4B LIVE TEST: BLOCKED
ADVERTISING WRITE REQUESTS: 0
```

Phase 4A is ready for preparation, preflight, confirmation and **local simulation**
of PAUSE_AD / ENABLE_AD. It is not a LIVE executor. Public documentation lists
WRITE endpoints, but does not establish an accepted, operation-specific contract.
The Action Engine is ready for its existing local/mock workflows; LIVE dispatch,
credential permission verification and single-use authorization are incomplete.
No real or fake runtime WRITE key was created or connected. Meta, AI and automatic
advertising control remain disabled. No production AD was selected for a LIVE test.

## 2. Existing Architecture

- `services/actions/manual.py`, `manual_models.py`, `manual_schema.py`: durable
  drafts, captured identity/revisions, preflight, role/grant checks, CSRF-protected
  confirmation, expiry and local simulation. No manual execution HTTP endpoint.
- `services/actions/engine.py`: legacy queue, policy, durable attempts and bounded
  unknown-outcome READ reconciliation; it is not an authorized LIVE entry point.
- `services/actions/capabilities.py`, `safety.py`, `providers.py`: capability
  reasons, environment gates and disabled provider implementations.
- `services/providers/contracts.py`: action routing fails closed; READ provider
  management and READ fallback are independent of advertising actions.
- `services/metricflow/writer.py` and transport: legacy mock-tested WRITE connector;
  no accepted typed LIVE adapter. Provider calls cannot bypass the hard gate.
- `services/providers/credentials.py`: authenticated encryption and workspace/provider
  isolation exist. The current `(workspace_id, provider)` credential slot is used
  by READ and does not support independent READ/WRITE purposes and revisions.

The Rule Engine integration resolves a canonical eligible WOULD_PAUSE candidate
into a DRAFT with rule provenance. It does not execute the rule's advertising action.
Stale or insufficiently attributed candidates remain blocked. A mocked eligible
browser candidate is not proof that a production candidate is currently eligible.

## 3. MetricFlow WRITE API Documentation

The official [API documentation](https://metricflowit.click/docs) describes Bearer
API keys, `campaigns:write`, GET `/api/v1/me` key metadata, nested account catalogs,
and generic POST `/api/v1/entities/{entity_id}/pause`, `/enable`, `/budget` routes.
It also documents daily plan quotas and 429 responses. These confirm endpoint
existence, not a complete AD-specific WRITE contract. Rules/bundle logs are not
confirmation of arbitrary manual action history.

Public HTML was retrieved without credentials on 2026-10-11T09:21:15.251352+00:00,
HTTP 200; SHA-256:
`a8d29a8e3daf30b80f2463ad106a67a4749c35023548a9ba67784bd04be5c0a3`.
Local evidence: `.tools/phase4b-documentation.json` and
`.tools/phase4b-public-docs.html` (ignored evidence, not committed).

No versioned OpenAPI/Swagger or official SDK link was found in the reviewed public
material. Context7's MetricFlow match concerned dbt metrics, not this advertising
provider, and was discarded. No guessed documentation or API endpoint was probed.

Unconfirmed: WRITE entity-ID namespace and accepted entity types; request/body
schemas and mandatory parameters; response/error schemas; synchronous versus
asynchronous completion; operation/asset permissions; configured/effective status
readback; no-op meaning; idempotency key support and retention; retry semantics;
consistency window; action correlation/result/history; operation-specific limits.
Unknowns remain UNVERIFIED, not UNSUPPORTED. No undocumented request is implemented.

## 4. Capability Matrix

Provider status is distinct from endpoint documentation and local implementation.
All WRITE execution is BLOCKED. Generic endpoint presence does not prove that AD,
AdSet or Campaign IDs from READ are accepted by its WRITE path.

| Operation | Published route evidence | Provider capability status | Local implementation / limitation |
| --- | --- | --- | --- |
| PAUSE_AD | POST entities/{entity_id}/pause | WRITE_UNVERIFIED | IMPLEMENTED_MOCK_ONLY legacy pause; manual DRAFT/preflight/simulation |
| ENABLE_AD | POST entities/{entity_id}/enable | WRITE_UNVERIFIED | IMPLEMENTED_MOCK_ONLY legacy enable; manual DRAFT/preflight/simulation |
| GET_AD_STATUS | GET ad-accounts/{ad_account_id}/ads; GET insights | DOCUMENTED | Catalog/READ exists; separate configured-status contract not verified |
| GET_EFFECTIVE_STATUS | GET insights through existing READ schema | LIVE_VERIFIED_READ | Existing READ synchronization maps effective_status; not post-WRITE causal proof or dedicated status endpoint |
| SET_ADSET_BUDGET | Generic POST entities/{entity_id}/budget | WRITE_UNVERIFIED | IMPLEMENTED_MOCK_ONLY generic payload; type, units, limits and schema unverified |
| SET_ADSET_BID | No bid route confirmed | WRITE_UNVERIFIED | No accepted operation contract or typed adapter |
| SET_CAMPAIGN_BUDGET | Generic POST entities/{entity_id}/budget | WRITE_UNVERIFIED | Generic stub cannot establish campaign support/schema |
| PAUSE_CAMPAIGN | Generic POST entities/{entity_id}/pause | WRITE_UNVERIFIED | No confirmed campaign binding or manual UI operation |
| ENABLE_CAMPAIGN | Generic POST entities/{entity_id}/enable | WRITE_UNVERIFIED | No confirmed campaign binding or manual UI operation |
| GET_ACTION_RESULT | No correlated manual-WRITE result route confirmed | WRITE_UNVERIFIED | Local request result is not provider execution proof |
| GET_ACTION_HISTORY | Rules/bundle logs exist; arbitrary manual-WRITE history unconfirmed | WRITE_UNVERIFIED | Local append-only audit is not provider action history |

For every WRITE row, auth/asset permissions, exact ID, required parameters,
request/response/error schema, limits, idempotency, timeout outcome, execution mode,
readback and no-op behavior need provider confirmation before adapter acceptance.
No row is classified UNSUPPORTED solely because its documentation is absent.
The runtime registry's existing five operations are not an implementation of this
full eleven-operation matrix.

## 5. Authentication & Permissions

The documented key flow is Settings -> API -> Create Key -> select scopes; the
secret is shown once. `/me` describes owner/team/role/scopes/access state, and
optional acting-as metadata. `campaigns:write` is the documented WRITE scope.
An active subscription and asset authorization still need separate verification.
[Official documentation](https://metricflowit.click/docs).

READ key presence, healthy READ synchronization, a secret-file boolean and a scope
label are not evidence of WRITE permission for a selected account/AD. This audit
performed no authenticated permission probe and stored no WRITE credential.

The encrypted credential primitive can be reused only after adding independent
purpose/revision/permission metadata. Putting WRITE credentials into the existing
READ connection form or replacing its one credential slot would be unsafe.
The existing isolated action-service secret path is `.secrets/metricflow_write_key`,
mounted as `/run/secrets/metricflow_write_key` via `METRICFLOW_WRITE_KEY_FILE`.
It is not created here and is not mounted into the working backend/READ workers.
File existence must never confer authorization.

## 6. MetricFlow Action Provider

The legacy connector assumes numeric IDs, bodyless pause/enable and a generic
budget body. Its mocked successes do not validate these assumptions against the
provider. There is deliberately no guessed production adapter or new execution
route. WRITE transport allows POST only, disables redirects/environment proxies,
and has one HTTP attempt; ambiguous failures become unknown in mocked tests.
READ and WRITE clients/credentials remain separate.

A future accepted adapter must validate typed payloads/results against a versioned
contract, preserve provider/account/entity binding and audit sanitized correlation.
Legacy 4xx/response interpretations and coincidental READ state are insufficient
without contract evidence. HTTP success alone must not establish SUCCEEDED.

## 7. Manual Control UI

Users can prepare PAUSE_AD / ENABLE_AD, review identity and blockers, run preflight,
confirm local simulation, cancel drafts and inspect local history. Prepared actions
and confirmations leave advertising facts unchanged. The Rule Engine preparation
path shares these controls and adds provenance.

Settings now explicitly show LIVE BLOCKED, WRITE UNVERIFIED, localized blockers
and activation requirements. Connections separately distinguish MetricFlow's
unverified WRITE from Meta's disconnected state. There is no LIVE enable button,
credential input or hidden execution authorization added by this change.

## 8. Safety Gate

Runtime remains `ACTIONS_ENABLED=false`, `LOCAL_READ_ONLY=true`, `AI_ENABLED=false`,
`AI_AUTOPILOT_ALLOWED=false`. Meta's stored connection is disabled/disconnected;
no Telegram advertising control was enabled. The action-worker is absent.

Audit fixes: `ActionSafetyGate.require_write()` now also rejects with
WRITE_CONTRACT_UNVERIFIED even if both environment switches are changed. The
legacy engine calls that full gate before creating an execution attempt. No
configuration flag, READ health, UI confirmation or router can grant a verified
contract. Acceptance of a future LIVE contract requires a separately reviewed
implementation, not an environment override.

Real-gate regressions cover all four flag combinations, no provider HTTP, no
execution record when globally enabled, unverified permissions despite key metadata,
and action routers rejecting both providers without fallback. Existing legacy
mock execution fixtures explicitly assume a synthetic accepted contract only inside
isolated tests so transport/queue behavior remains testable. This is not a runtime
bypass and the new safety regressions do not mock away the hard gate.

## 9. Action Preflight

Checks preserve canonical entity UUID, source provider, numeric external AD ID,
`act_` account, full campaign/adset hierarchy, workspace, actor role/grant, routing
and READ credential revisions, original state and freshness. No name-based entity
matching or cross-provider WRITE routing is accepted. Changed revision/routing,
stale facts, conflicts and already-target state block local readiness as applicable.

WRITE namespace remains unverified. In particular `config/metricflow-schema.json`
maps local `status` to `effective_status`, without a distinct configured-status
mapping. A parent-paused effective state cannot safely substitute for an AD's
configured state. Live preflight/readback needs independently confirmed configured
and effective states, parent identity and bounded freshness/consistency evidence.

## 10. Idempotency & Unknown Outcome

Local same-key/same-command replay returns the same draft; different input conflicts.
Entity locks and pending uniqueness serialize local preparation and confirmation.
The audit additionally blocks queued/executing/verifying/unknown and future
EXECUTING/OUTCOME_UNKNOWN/RECONCILIATION_REQUIRED requests before preparing a new
command. Unknown future states are never auto-expired into a new advertising attempt.

Mock timeout regression proves unknown outcome causes no second WRITE and only
bounded cached READ reconciliation. Router fallback cannot resend through Meta.
Future LIVE needs a durable one-use permit, atomic consumption/attempt creation,
crash recovery and DB constraints covering future execution states; the current
partial pending index alone is not that implementation. No migration is introduced
and future LIVE states were tested only in isolated fixtures.

## 11. Phase 4B Live Test Plan

This is a reviewable future plan, not authorization or an executable test today.

1. Obtain and accept a versioned provider contract for one PAUSE_AD or ENABLE_AD.
2. Implement and mock-test its typed adapter, errors, no-op and readback semantics.
3. Implement separate encrypted WRITE credential purpose/revision and permission
   evidence, durable one-use permit and atomic dispatch with isolated PostgreSQL tests.
4. Independently verify key owner/scope/subscription and selected asset permissions
   using documented non-mutating facilities; reserve READ quota.
5. Select one provider, workspace, account and AD; confirm WRITE-ID namespace and
   exact parent hierarchy. Do not infer this mapping from the READ ID alone.
6. Capture fresh configured/effective original state, parent state, timestamps,
   provider contract version/hash, routing and WRITE credential revisions.
7. Reject stale/revised/conflicting/unknown/already-target states; calculate the
   immutable preflight fingerprint and expected target/result.
8. Present exactly that object, operation, original/target state and expiry for
   separate explicit user authorization. Persist actor/workspace binding, maximum
   one HTTP attempt and short-lived permit. Local confirmation is not this permit.
9. Recheck identity, state, revisions, all gates and permit under locks; atomically
   consume it and persist the attempt before dispatch. Never reverse consumption
   after an ambiguous crash or network result.
10. Dispatch once through a dedicated permit-bound process. Keep the workspace flags
    and general action queue disabled. No transport, worker, proxy or provider retry.
11. Validate the response and perform bounded independent READ of the same object;
    verify configured/effective state, parents, freshness and correlation. Success
    requires contract-defined result evidence, not HTTP 200 or state coincidence.
12. Timeout/unrecognized response/crash/missing readback becomes OUTCOME_UNKNOWN /
    RECONCILIATION_REQUIRED; block further writes, reconcile with bounded READ and
    manual inspection. No cross-provider fallback or automatic resend.
13. Stop dispatch and preserve audit. Restoration requires fresh state, a separate
    explicit authorization and a new permit; resolve any unknown outcome first.

## 12. Docker & Database

Backend, PostgreSQL and Redis are healthy; frontend and READ worker/scheduler run.
Only backend/frontend were rebuilt to verify these changes. Action-worker remains
absent. Readiness returns HTTP 200 with database/migrations/schema/Redis ready.
Working Alembic head is `0012_manual_actions`; `alembic check` reports no new upgrade
operations. No working-database migration, reset, volume removal or data deletion.

`metric-control-center-migrate-1` remains stopped with exit 255, old image
`sha256:6a3bc9a5aeb36f4e199b61cf853798c863c563cbb879fca385c5a65a84e378ac`.
Logs show `Can't locate revision identified by '0010_economics'`. This is an obsolete
failed one-shot job, not a normal successful stopped migrator. It was neither
removed nor blindly rerun. Compose's completed-migration dependency is therefore
not proof of a clean future deployment. Build the current migration image and
verify startup against an isolated restored database before a separately authorized
deployment. Existing volumes and the stale container are preserved as evidence.

## 13. Tests

| Check | Actual result |
| --- | --- |
| Full backend | 445 passed, 1 skipped, 77 subtests passed (369.08 s) |
| Separate isolated PostgreSQL auth/schema case | PASS; covers PostgreSQL-dependent check skipped by the default backend run |
| New audit regressions | 18 passed; included in full backend suite |
| Focused actions/manual/connector/audit suite | 99 passed, 23 subtests passed |
| PostgreSQL manual concurrency | PASS: 8 same-key, 8 conflicting and 8 confirmation threads; provider HTTP 0 |
| Frontend unit tests | 33 passed |
| Frontend production build / TypeScript | PASS |
| Manual Control Playwright | 5 distinct scenarios passed |
| Navigation Playwright | 7 distinct scenarios passed, including separate final mobile-logout rerun |
| Browser console/page errors and advertising mutations | None observed by acceptance guards |
| Scoped Ruff check / format check | PASS: safety.py, manual.py, test_phase4b_audit.py |
| Scoped mypy | PASS: safety.py and capabilities.py |
| Alembic check / health ready | PASS / HTTP 200 |

The combined browser run passed 11 scenarios, then its final logout API assertion
hit the shared 240/minute rate limit (429). Logout itself redirected correctly.
After the minute window elapsed, that unchanged scenario passed separately with
its expected 401. Limits/assertions were not weakened. This is 12 distinct passing
scenarios across two runs, not a single entirely green combined run.

Security source/secret scan: PASS, including staged new files; staged diff whitespace check: PASS.
Local ignored evidence is under `.tools/phase4b-*` and
`.tools/navigation-phase4b-*`; test fixtures use mock transports/disposable data,
not runtime advertising credentials.

## 14. Data Integrity

Initial/final working-database snapshots contain 62 tables. **54 are byte-hash
unchanged**; eight changed while normal READ synchronization remained running:
`ad_accounts`, `api_quotas`, `daily_metrics`, `entity_current_state`,
`provider_connections`, `provider_windows`, `raw_snapshots`, `sync_runs`.
These are READ ingestion/health/quota tables; do not describe the entire audit as
62 unchanged tables. Other tables, including users, economics, rules and presets,
retain their original hashes. No READ schema/configuration was changed;
`metricflow-schema.json` SHA-256 remains
`57e0bb852aa4a321f1cbcab77c70ca8e625522e1584ca6de7c2cd03bb9d3eb94`.

Working action_requests/action_executions/action_logs were 0 before and 0 after.
Both browser integrity windows temporarily paused READ workers and compared all
62 table hashes: no changed tables, action execution delta 0. Browser fixtures
were cleaned and READ services resumed. Separate auth/concurrency checks used the
existing isolated restored database, not a production reset or schema modification.
No real advertising facts were changed by manual actions. Pre-existing user edits
and reports were not included in this change.

## 15. Remaining Blockers

- Accepted operation-specific WRITE contract, entity namespace, typed schemas,
  errors/no-op, limits, async/result/history and idempotency semantics.
- Separate WRITE credential storage/revision and verified owner/scope/subscription/
  selected-asset permissions; no connected WRITE key currently proves these.
- Distinct configured/effective status and trustworthy post-WRITE READ correlation,
  consistency window, quota reservation and ambiguous parent-state handling.
- Reviewed typed LIVE adapter and controlled entry point; current provider stubs
  and legacy mock connector do not implement the accepted contract.
- Durable single-use authorization, atomic consume/attempt, future-state database
  constraints and crash/concurrency evidence. Global flags cannot authorize LIVE.
- One explicit user-authorized object/operation after those prerequisites.
- Obsolete failed migration container must be resolved through isolated current-image
  deployment verification before relying on the general Compose startup path.

## 16. USER ACTION REQUIRED

First obtain versioned contract evidence from [MetricFlow support](https://telegram.me/metricflow_support):
exact AD pause/enable examples, ID namespaces, minimal scopes/asset permissions,
non-mutating permission verification, configured/effective readback, result/error/
no-op semantics, idempotency, timeout handling, consistency window and limits.
Request an official OpenAPI/SDK if available. No message was sent on your behalf.

Do not create/connect a WRITE key or authorize an AD yet: Phase 4B is BLOCKED.
After contract acceptance and safe credential/permit implementation, a separate
explicit task can provision the minimal WRITE key through the documented settings
flow and secure purpose-specific server storage. Never paste a key into chat, Git,
logs, browser code or the READ connection form. Later authorization must name one
AD and one operation; no bulk/rule/AI/budget/Meta activation is implied.
