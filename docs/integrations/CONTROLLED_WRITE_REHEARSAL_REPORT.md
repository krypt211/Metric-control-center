# Encrypted WRITE handoff and durable mock rehearsal

Report date: 2026-10-17, Europe/Moscow. Baseline: 4430ab7.
Phase 4B: PARTIAL. Encrypted handoff / one-attempt rehearsal: READY MOCK.
LIVE advertising WRITE: BLOCKED. This report does not authorize a provider call.

## Accepted local behavior

- The existing factory loads only the separately encrypted PostgreSQL WRITE record,
  explicitly bound to workspace and credential revision. Purpose binding is checked
  by the existing WriteCredentialVault. READ credentials and plaintext key files
  are never fallback sources. The unconditional LIVE contract gate runs before DB
  credential access or decryption. Backend/READ workers still lack the WRITE cipher.
- Cached entities:write / active_paid evidence must be no older than 900 seconds
  (future clock tolerance 60 seconds). This is a conservative LOCAL freshness policy,
  not a documented provider permission TTL or proof of object permissions. There is
  no automatic GET /me, token rotation or revision refresh. Deletion, revision or
  ciphertext changes are checked again around the final pre-HTTP guard.
- Existing ActionEngine gains internal prepare_rehearsal/execute_rehearsal methods.
  These admit only SQLite test fixtures or mcc_integrations_* PostgreSQL databases
  AND write-rehearsal-* workspaces. Execution requires explicit httpx.MockTransport.
  No public route, LIVE permit, CLI dispatcher, new engine, queue, table or migration.
- A confirmed single-AD manual request is bound to actor, workspace, account,
  internal/external AD IDs, operation, confirmation, full existing snapshot,
  encrypted credential revision/digest and a deadline of at most 10 minutes,
  bounded further by the original manual draft window. Local confirmation is not
  LIVE user authorization. Production permits cannot be created with this method.
- Existing workspace/user/entity/request locks and unique ActionExecution commit
  one claim before vault access or HTTP. A second process/restart cannot consume it
  again. Final permission, identity, snapshot, expiry and key checks precede the
  explicit mock HTTP attempt. A consumed permit is never rearmed automatically.
- The typed PAUSE/ENABLE adapter sends one async mock POST with level=ad; correlated
  job_id is persisted. Timeout, denied response, malformed success and interruption
  retain a spent attempt/UNKNOWN. An already-started ACK is recorded even if local
  permissions expire or are revoked while the request is in flight.
- An interrupted executing claim becomes UNKNOWN after the existing 120-second
  recovery threshold. There is no resend. A mock ACK is never promoted to verified
  by the legacy effective-status reconciler, and creates no real MCC pause ownership.
- Legacy unbound Celery dispatch is fail-closed. The optional action-worker Compose
  definition now uses only the separate encryption key/SQL envelope namespace; its
  plaintext WRITE key and obsolete file-vault mounts are removed. It is not started.
- Manual Control capability metadata now reports the confirmed entities:write
  requirement and only the encrypted Credential Manager record as configured. A
  legacy plaintext file cannot make the connection appear configured; cached scope
  presence still leaves object permissions and LIVE status unverified/blocked.

The provider wire subset remains the pinned [OpenAPI audit](METRICFLOW_WRITE_ADAPTER_ACCEPTANCE.md).
No undocumented HTTP contract, Idempotency-Key behavior or job polling was invented.
SQLAlchemy 2 transaction/row-lock handling was checked with Context7 official docs.

## Verification

- New encrypted/durable rehearsal suite: 26 PASS. Final dependent manual-control,
  Phase 4B safety and Credential Manager regression: 158 PASS in 297.55 seconds.
- Full backend core regression: 713 PASS, 1 SKIP, 78 subtests PASS in 897.92 seconds. It started before the last
  capability-metadata correction; the final focused 158-case run above covers that
  correction and dependent manual/settings paths. Subsequent engine edits only
  normalized imports and documented the intentionally sanitizing exception boundary.
- Isolated PostgreSQL: 8 independent processes, exactly 1 claim and 1 physical mock
  POST for the raced request, job_id=41 durably saved. Repeated process: no resend.
  Separate process exited abruptly with code 17 after its mock HTTP attempt; restart
  recovered UNKNOWN with no resend. Total physical mock attempts for two requests: 2;
  verified events: 0. Final schema: controlled_rehearsal_3c027831442e4d35bbc3577346abb0f5
  in the previously restored mcc_integrations_audit_20261014_165636 database.
- Frontend: 36 unit PASS, TypeScript PASS. UI source unchanged; existing frontend
  production image retained. Final Playwright: 9/9 PASS in 16.9 seconds against the
  final backend/private mock Credential Manager, workspace integration-ui-controlled-c9d66d6c02
  in fresh restored database mcc_integrations_controlled_20261016_211626.
- Reusing the earlier browser DB correctly hit its durable global Meta cooldown.
  It was not reset or bypassed. A fresh DB was restored from the hash-verified backup
  and migrated separately for the final browser run. The fixture now explicitly
  refuses a working database. Initial fixture/setup failures are not counted as PASS.
- Both Compose files validate; production validation uses dummy required domain/email
  values only, without changing .env or deploying production Compose. Final four
  Python images built. Ruff/format PASS for eight clean changed Python files; the
  legacy ActionEngine has the same five pre-existing findings and zero introduced
  findings. Basic secret scan and staged diff checks PASS. No dependency change.
- Legacy action task: three isolated states (disabled, unverified contract, missing
  controlled binding) all held; factory/vault opens 0, advertising HTTP attempts 0.
- SQLAlchemy locking/race semantics are measured in PostgreSQL, not inferred solely
  from SQLite. None of these fixtures proves LIVE provider behavior.

## READ connection baseline and preservation

Before this stage, MetricFlow READ was already enabled at revision 1 but degraded:
PROVIDER_READ_FAILED, with the two latest normal syncs returning TransportUnavailable
(3 attempts, 0 pages each at 2026-10-16 02:40 and 02:50 UTC). Last successful normal
sync was 2026-10-16 02:30:00.987143 UTC. Local Oct16 quota was 71/800, cooldown absent.
The existing normal scheduler recovered READ at 2026-10-16 21:03:05.121656 UTC
(2026-10-17 00:03:05 Europe/Moscow), before deployment: connection healthy, revision 1.
No manual retry or health-status rewrite was used.
This does not prove a token, scope or subscription error; the underlying provider
network failure is not established. No diagnostic provider request, token replacement,
status clearing or cadence/quota change is part of this stage. Final runtime after deployment: MetricFlow READ healthy at revision 1, latest
normal sync success 2026-10-16 21:10:02.335048 UTC. READ connection configuration
and encrypted bytes are preserved; no additional provider probe was sent.

The stored real WRITE revision remains 1, with the historical scope check at
2026-10-12T22:04:27.534223Z. That stale check intentionally cannot satisfy the new
15-minute local handoff prerequisite. The real WRITE token was not decrypted or used.
All successful handoff tests use synthetic keys and synthetic cached scope evidence.
Meta remains disconnected; no Meta authorization/version gate is populated.

## Working deployment and data preservation

Backend, ingestion worker, scheduler and private Credential Manager were updated
with all safety flags unchanged. Five changed runtime modules match disk in all
four Python containers. Frontend image, PostgreSQL/Redis services and volumes were
retained. The opt-in action-worker is not running; legacy dispatch remains blocked.

Counts and digests match the pre-work baseline for 21 protected tables, including
users/settings/economics/rules/manual actions, WRITE credential bytes/revision/audit,
READ credentials and routing. .env SHA256 is unchanged. Working PostgreSQL remains
0016_smart_control with 70 public tables; no working migration or DDL was run.
Stopped working migration container has exit 0. Backend/live/ready, PostgreSQL,
Redis and Credential Manager are healthy; frontend login returns 200. No active
Meta jobs or Meta credentials exist in working storage; Meta revision 4 disconnected.

The final browser database also has revision 0016_smart_control / 70 public tables.
Its migration/role grants and all fixture data were confined to that restored DB.
The isolated browser stack is stopped; restored DBs/schemas are retained for evidence,
without deleting volumes. Rollback image IDs and integrity snapshots are private.

## Exact blockers before a first controlled LIVE operation

1. Provider confirmation of entity_id namespace and authoritative READ-to-WRITE
   AD/account mapping. Local path-segment validation and fixture IDs are not proof.
2. Formal HTTP 202 response/error/partial-application semantics, including job
   ownership, scope and team/acting-as permissions. The OpenAPI description promises
   202 while formal responses omit its schema; mock acceptance is a local policy.
3. Confirmed non-mutating permission check for the particular advertising object;
   a current independent WRITE scope/subscription check via Credential Manager and
   healthy, sufficiently fresh READ facts. Stored scope evidence alone is stale.
4. Documented idempotency or safe operation lookup after a lost job_id. Local
   no-resend is implemented; it does not recover a provider outcome by itself.
5. Configured/effective/parent status meaning, authoritative READ freshness/cache
   behavior and consistency deadline; bounded job observation and readback handling.
   Job success and an effective-only status change do not establish MCC ownership.
6. Actual production one-action authorization/dispatch wiring in the existing
   ActionEngine after those contracts are accepted. MOCK_ONLY permits cannot be
   promoted. Reaccept that exact path with permission/rotation/race/crash fixtures.
7. Separate explicit user authorization identifying one AD, one PAUSE or ENABLE,
   credential/permission revision, window and one-attempt limit. Restoration is
   another operation requiring separate authorization. No broad scheduler enablement.

Next user action: obtain the focused provider clarifications in the
[current roadmap](../roadmap/FINAL_MCC_ROADMAP.md). No new WRITE key is required.
A real key recheck should be performed only when preparing an authorized controlled
phase; no provider support message or advertising operation was sent here.

ACTIONS_ENABLED=false
LOCAL_READ_ONLY=true
AI_ENABLED=false
AI_AUTOPILOT_ALLOWED=false

META LIVE REQUESTS DURING THIS STAGE: 0
ADVERTISING WRITE REQUESTS DURING THIS STAGE: 0

Private evidence and rollback IDs: .tools/control-rehearsal/ (excluded from Git).
User-owned docs/roadmap.md and earlier untracked reports are excluded from this stage.


## Changed components

- services/actions/{factory,engine,capabilities}.py; workers/actions.py.
- services/metricflow/writer.py: optional pre-request guard, existing wire contract.
- docker-compose.yml and .env.example: encrypted namespace, no plaintext mounts.
- tests/test_controlled_rehearsal.py; scripts/check_controlled_rehearsal_postgres.py.
- Existing connector/foundation/Phase 4B regressions and browser fixture DB guard.
- README, architecture/sync notes, current roadmap and historical-report pointer.

PHASE 4B: PARTIAL
ENCRYPTED HANDOFF / DURABLE ONE-ATTEMPT REHEARSAL: READY MOCK
CONTROLLED PRODUCTION AUTHORIZATION / DISPATCH: NOT IMPLEMENTED
METRICFLOW LIVE WRITE: BLOCKED
METRICFLOW READ: HEALTHY / PRESERVED
META LIVE REQUESTS: 0
ADVERTISING WRITE REQUESTS: 0


Subsequent stage (2026-10-18): [bounded mock job observation](METRICFLOW_JOB_OBSERVER_ACCEPTANCE.md)
adds durable GET steps and deadline recovery in isolated rehearsals. It supersedes
the earlier absence of observation in this dated report. LIVE authorization,
dispatch and authoritative readback remain blocked; no working deployment was made.
