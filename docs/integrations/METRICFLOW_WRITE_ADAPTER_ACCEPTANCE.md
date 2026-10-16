# MetricFlow WRITE adapter acceptance

Report date: 2026-10-16, Europe/Moscow. Public documentation snapshot uses UTC timestamps.
Baseline: 72ee5f5. Phase 4B: PARTIAL. LIVE advertising WRITE: BLOCKED.

Historical stage report. Subsequent [encrypted handoff/mock rehearsal](CONTROLLED_WRITE_REHEARSAL_REPORT.md) replaces the plaintext factory and accepts durable mock claims/job correlation. Its LIVE authorization/observation/readback boundaries remain blocked; the test counts and runtime snapshot below belong to this earlier stage.

## Official evidence

- [API reference](https://metricflowit.click/api/v1/docs).
- [OpenAPI JSON](https://metricflowit.click/api/v1/openapi.json?lang=en).
- [Unmodified selected operations and referenced schemas](METRICFLOW_WRITE_OPENAPI_2026-10-15.json).
- OpenAPI 3.1.0; MetricFlow Public API version 1.0.0.
- Retrieved: 2026-10-15T20:54:10.331003+00:00. Full source SHA256: 12cf5cc017e36ba54add51cb10eb2e625607f60bd55b7fa79f2cee5467d35077.

Only public documentation was fetched, without credentials. The first request with
Python's default User-Agent returned 403; a normal browser User-Agent returned the
public schema. No protected endpoint was probed. Context7 documents Pydantic 2 and
HTTPX 0.28.1 usage; it is not a substitute for MetricFlow's own contract.
Installed Pydantic 2.13.5 and HTTPX 0.28.1 are unchanged; no dependencies added.

## Contract matrix

| Part | Confirmed | Remaining boundary |
| --- | --- | --- |
| Scope | entities:write in the specific OpenAPI description | No campaigns:write alias inferred; per-object permissions unknown |
| Authentication | X-API-Key or Authorization: Bearer | Existing Bearer transport retained; no real token used |
| PAUSE | POST /api/v1/entities/{entity_id}/pause | AD/account ID binding not confirmed |
| ENABLE | POST /api/v1/entities/{entity_id}/enable | Existing ownership/reenable/parent/freshness gates remain |
| Body | Required EntityActionRequest.level; ad is documented | Local adapter supports AD only; no campaign/adset operations added |
| Sync response | HTTP 200, success:boolean, entity_id:string, message:string, optional nullable job_id:integer | Acknowledgement is not configured/effective readback |
| Async | async=true, description promises 202 + job_id | Formal responses only list 200 and 422; exact 202 envelope unresolved |
| Job observation | GET /api/v1/jobs/{job_id}; pending/running/success/partial/failed/expired and per-entity results | Decoder only; no live GET poller or executor integration |
| READ state | status and effective_status fields, ApiMeta.data_updated_at in READ schema | Configured semantics and post-WRITE cache/consistency deadline not proven |
| Errors | Global 400/401/402/403/404/429 meanings; 422 validation schema | Full action error bodies/partial application semantics unknown |
| Idempotency | No PAUSE/ENABLE idempotency contract found | No guessed Idempotency-Key header, automatic retries or resend |

The older general /docs page's campaigns:write requirement is superseded for this
adapter by the specific OpenAPI entities:write statement. Earlier dated audit
reports remain historical evidence, not the current required-scope policy.

## Implementation in existing components

- Existing MetricFlowActionConnector now serializes the fixed {"level":"ad"} body.
  pause_entity/enable_entity keep their compatible call form; optional asynchronous
  requests serialize async=true. No endpoint guessing or alternate transport.
- Numeric provider-ID inference removed. ID validation only enforces a local safe
  opaque ASCII path segment, at most 128 characters. This is an injection policy,
  not a guarantee of valid WRITE namespace or AD/account ownership.
- Strict frozen Pydantic acknowledgement and job models live in writer.py.
  Additive unknown response fields are dropped, types are not coerced. Entity ID,
  positive integer job ID and single-AD job counts/results must correlate. Provider
  messages/errors are omitted from model repr; exceptions never include raw bodies
  or Pydantic input dumps. The code does not log response payloads.
- PAUSE/ENABLE accept sync HTTP 200. Async mock acceptance allows 200 or 202 only
  with the full correlated acknowledgement and non-null job_id. Applying the 200
  model as a strict minimum to 202 is a LOCAL conservative hold policy, not proof
  of the provider's missing 202 schema. Missing envelope fields remain UNKNOWN.
- HTTP 204/other undocumented success, malformed or false acknowledgement, wrong ID,
  missing job, timeout, 408/5xx -> unknown; exactly one physical mock POST attempt.
  Existing sanitized 400/401/402/403/404/422/429 handling and Retry-After preserved.
- Job decoding is pure: it makes no HTTP request, schedules no job and marks no
  ActionRequest verified. Terminal success still requires authoritative fresh READ.
- Existing transport has one optional accepted-status set; READ callers use the
  unchanged default. Reader, quota/cadence, shared ActionEngine and ActionSafetyGate
  implementations were not changed. No new executor, runtime module, queue or table.
- Credential Manager and settings UI require entities:write. Cached scope metadata
  is reclassified on read only; encrypted bytes/revision/checked_at/audits unchanged.
  Object permissions remain PERMISSIONS_UNVERIFIED, LIVE_ACTIONS_BLOCKED remains.
  The existing check button still uses GET /me with zero retries; it was exercised
  only by mock fixtures here. No extra working connection check was performed.
- Budget/bid contracts, actual job polling, durable job correlation and a controlled
  LIVE permit/executor are not enabled by this change. Legacy action/budget paths
  remain behind the unchanged hard gate, including when environment flags are permissive.
  The legacy action factory still expects METRICFLOW_WRITE_KEY_FILE; it is not
  wired to the encrypted Credential Manager record. No plaintext WRITE file was
  created. A purpose/workspace/revision-bound credential handoff into the existing
  private action process is another required integration before any controlled test.

## Verification

- Focused backend: 157 PASS, 23 subtests PASS; all wire calls use httpx.MockTransport.
- New contract suite: 57 cases, plus one cached credential non-mutation regression.
- Full backend: 687 PASS, 1 SKIP, 78 subtests PASS in 768.21 seconds.
- Frontend: 36 unit PASS, TypeScript PASS, production Docker frontend build PASS.
- Playwright: 9/9 PASS on a fresh integration-ui-* workspace in a restored
  mcc_integrations_* PostgreSQL database, private mock Credential Manager only.
  Save/check/replace/delete, encrypted READ independence, revision/CSRF/RBAC,
  responsive views and absence of Meta LIVE were verified. Synthetic Meta attempts
  exist only in the isolated mock fixture journal; working Meta attempts remain zero.
- Ruff and format checks passed for five changed clean Python modules/tests.
  Existing terse transport/connector-test files were changed surgically; no claim
  that repository-wide formatting/lint is clean. Basic secret scan and diff checks PASS.
- Docker images and Compose configuration PASS. No schema change or migration needed.

## Working runtime and preservation

Backend/worker/scheduler/credential-manager/frontend updated with WRITE disabled.
Four changed Python modules match disk across all four Python runtime containers.
PostgreSQL, Redis, volumes and credentials were not recreated or rewritten.
Counts and digests match for 21 protected tables before/after; .env hash is unchanged.
PostgreSQL remains 0016_smart_control. Health/live/ready and frontend login return 200.

Cached WRITE revision: 1; original checked_at: 2026-10-12T22:04:27.534223+00:00.
Scope projection: SCOPES_VERIFIED / scope_verified=true, based ONLY on that saved
check and the corrected documented scope. Stored credential status itself is unchanged.
It is not a fresh key/plan/object permission verification.
MetricFlow READ healthy; last normal success: 2026-10-15 21:10:01.200913+00:00 UTC.
Meta disconnected; credentials absent, active Meta jobs 0, physical Meta attempts 0.
Pilot authorization/version gates remain empty; global Meta floor remains 1800 seconds.

ACTIONS_ENABLED=false
LOCAL_READ_ONLY=true
AI_ENABLED=false
AI_AUTOPILOT_ALLOWED=false

## Remaining blockers for one controlled test

1. Provider confirmation of WRITE entity_id namespace and exact AD/account/READ binding.
2. Exact 202 envelope, full denial/error/partial-application contract, job ownership,
   scope and team/acting-as permissions; non-mutating object permission validation.
3. Idempotency or an explicit safe no-resend strategy; operation lookup/reconciliation
   when timeout loses job_id. A timeout never grants permission to retry.
4. Authoritative configured/effective/parent status semantics, cache freshness and
   bounded post-WRITE readback/consistency deadline. Job success is not proof alone.
5. Integrate the independent encrypted credential handoff (purpose/workspace/revision),
   confirmed bounded observation and durable one-attempt/correlation in the existing
   shared executor, with isolated PostgreSQL races/restart tests. No READ-key fallback.
6. Select exactly one AD; obtain separate explicit authorization for one operation,
   credential/permission revision, attempt limit and time window. Any restoration
   requires a second separate authorization. No broad scheduler/action queue activation.

A focused provider support request is prepared in
[the current roadmap](../roadmap/FINAL_MCC_ROADMAP.md), not sent.

DOCUMENTED PAUSE/ENABLE WIRE SUBSET: READY MOCK
METRICFLOW WRITE SCOPE POLICY: entities:write
PHASE 4B: PARTIAL
METRICFLOW LIVE WRITE: BLOCKED
METRICFLOW READ: PRESERVED
META LIVE REQUESTS DURING THIS TASK: 0
ADVERTISING WRITE REQUESTS DURING THIS TASK: 0

Private raw logs, rollback image IDs and integrity evidence: .tools/write-openapi/.
User-owned docs/roadmap.md and prior untracked reports are excluded from this stage.

## Changed files

- `README.md`
- `docs/metricflow-contract.md`
- `docs/phase4/BUSINESS_WRITE_READINESS_2026-10-12.md`
- `docs/roadmap/FINAL_MCC_ROADMAP.md`
- `docs/integrations/METRICFLOW_WRITE_OPENAPI_2026-10-15.json`
- `docs/integrations/METRICFLOW_WRITE_ADAPTER_ACCEPTANCE.md`
- `frontend/components/MetricFlowWriteSettings.tsx`
- `frontend/e2e/integration-settings.spec.mjs`
- `services/actions/credential_service.py`
- `services/actions/write_settings.py`
- `services/metricflow/transport.py`
- `services/metricflow/writer.py`
- `tests/test_connector.py`
- `tests/test_integration_settings.py`
- `tests/test_metricflow_write_contract.py`
