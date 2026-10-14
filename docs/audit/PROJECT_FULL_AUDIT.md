# Metric Control Center full audit

Audit started 2026-10-13 UTC, continued 2026-10-14 (Europe/Moscow).
Status: PARTIAL. No Meta LIVE or advertising WRITE performed.
This report supersedes historical readiness claims only for the audited scope.

## Baseline and evidence
Branch main, baseline commit ed65582. User changes in docs/roadmap.md and old
untracked phase4 reports are excluded from this work.
- PostgreSQL: 70 public tables, Alembic 0015_meta_pilot; no schema changes required.
- Frontend: 9 page routes; 8 primary links plus Settings before simplification.
- Backend: 113 HTTP method/path operations on 100 paths (OpenAPI).
  The initial app.routes top-level count of 10 excluded lazily included routers
  and is NOT the endpoint count.
- Services: 99 Python files including package initializers.
- Environment: 45 distinct literal os.environ/getenv keys in backend/services/workers.
  This excludes secrets' values, third-party keys and dynamically generated names.
- Runtime beat: 6 entries (today, yesterday, last7, breakdowns, frequency,
  provider dispatcher). Actions/AI/rules held by deployment safety flags.
- Seven long-running project containers; migrate is a successful exited(0) job.
- Original backend source drift: services/meta/pilot.py differed from working image.
- Fresh baseline full suite: 604 passed, 1 skipped, 78 subtests.
- Initial production MetricFlow healthy, revision 1; latest success at baseline
  2026-10-13T20:40:01Z. Meta disconnected revision 4, no credential, no active jobs.
- WRITE credential independently stored encrypted, revision 1; cached access state
  active_paid, PERMISSIONS_PARTIAL. No credential check was sent during this audit.

Evidence lives in ignored .tools/full-audit; backups contain private data and are
ACL restricted. Production cleanup verified all retained rows inside one locked
transaction. Rehearsal and restored-copy testing are not LIVE provider acceptance.

## Architecture and dependency map
Browser -> Next.js same-origin proxy -> FastAPI session/RBAC/CSRF ->
PostgreSQL analytics, economics and smart rules.
MetricFlow scheduler -> providers.manager -> providers.sync/SyncEngine ->
quota/leases -> MetricFlow READ adapter -> atomic PostgreSQL publication.
SmartRule -> target resolution -> economics adapter -> pure smart_core decision ->
immutable RuleSimulation -> explicit from-rule ManualDraft -> ActionEngine
preflight/confirmation/simulation -> ActionRequest/ActionLog.
Future WRITE path is fail-closed. Credential Manager alone decrypts the independent
WRITE key; it does not execute advertising mutations.
Redis supports Celery/auth limits; PostgreSQL owns durable data and provider jobs.

## Findings and disposition
| Area | Finding | Disposition |
|---|---|---|
| providers.manager / providers.router | Lifecycle vs source selection, different responsibilities | KEEP, not duplicate connectors |
| sync.engine / providers.sync | Atomic ingestion vs orchestration | KEEP shared MetricFlow path |
| legacy automation.rules vs smart_* | Legacy executable rules vs current economics DRY RUN | KEEP compatibility; legacy held by LOCAL_READ_ONLY; do not claim automatic Smart Rules execution |
| actions.engine / actions.manual | Shared request/log model with local lifecycle extension | KEEP; from-rule uses same preparation and gates |
| actions credential_service | Security boundary isolating WRITE secret | KEEP separate container |
| meta telemetry/jobs/pilot | Optional READ safety machinery | KEEP safety and tests; retire active pilot UI and periodic Meta entries |
| AI/Telegram | Non-core, no active workers or scheduled actions | KEEP historical contracts, disabled; no new surfaces |
| provider health vs API health | Provider probe vs service liveness | KEEP distinct, never probe disconnected provider |
| navigation / settings | Eight primary links; technical panels expanded; repeated routing button | Simplify existing registry and single routing editor |
| Meta rate state | Per-App ID/10s policy | Replace with shared meta-global/1800s, DB clock/lock/fencing |
| Profile timezone | No profile timezone setting; smart period fixed Europe/Moscow | OPEN functional gap; no invented timezone behavior |
| ENABLE automation | Smart Rules currently produces WOULD_PAUSE, not auto-enable | OPEN functional gap; no unsupported live claim |
| Multi-hour Meta sync | Current jobs cannot resume at arbitrary next page after pacing wait | BLOCKED optional integration; no automatic restart/backfill |
| WRITE API | Scope and request/response/readback contract incomplete | BLOCKED |

## Tables
Before/after row counts below are from the locked production cleanup transaction;
size measurements are from the earlier baseline. Ongoing MetricFlow READ can add
facts between these two observations.

Empty tables are not automatically unused: migrations, auth, audit and future
fail-closed contracts reference them. No DROP is justified now.

- action_executions: 0 -> 0 rows; 16384 baseline bytes; KEEP; shared contract, retained data or historical evidence.
- action_logs: 0 -> 0 rows; 65536 baseline bytes; KEEP; shared contract, retained data or historical evidence.
- action_requests: 0 -> 0 rows; 221184 baseline bytes; KEEP; shared contract, retained data or historical evidence.
- ad_accounts: 12 -> 9 rows; 131072 baseline bytes; CLEAN DATA; confirmed Meta-only rows archived and removed.
- ads: 314 -> 151 rows; 163840 baseline bytes; CLEAN DATA; confirmed Meta-only rows archived and removed.
- adsets: 284 -> 136 rows; 139264 baseline bytes; CLEAN DATA; confirmed Meta-only rows archived and removed.
- agent_messages: 0 -> 0 rows; 40960 baseline bytes; KEEP; disabled feature; retained schema for compatibility.
- ai_actions: 0 -> 0 rows; 24576 baseline bytes; KEEP; disabled feature; retained schema for compatibility.
- ai_decisions: 0 -> 0 rows; 24576 baseline bytes; KEEP; disabled feature; retained schema for compatibility.
- ai_quotas: 0 -> 0 rows; 8192 baseline bytes; KEEP; disabled feature; retained schema for compatibility.
- ai_settings: 0 -> 0 rows; 16384 baseline bytes; KEEP; disabled feature; retained schema for compatibility.
- alembic_version: 1 -> 1 rows; 24576 baseline bytes; KEEP; shared contract, retained data or historical evidence.
- api_quotas: 9 -> 8 rows; 57344 baseline bytes; CLEAN DATA; confirmed Meta-only rows archived and removed.
- approval_observations: 0 -> 0 rows; 65536 baseline bytes; KEEP; shared contract, retained data or historical evidence.
- automation_control: 0 -> 0 rows; 8192 baseline bytes; KEEP; shared contract, retained data or historical evidence.
- automation_events: 0 -> 0 rows; 24576 baseline bytes; KEEP; shared contract, retained data or historical evidence.
- batch_actions: 0 -> 0 rows; 32768 baseline bytes; KEEP; shared contract, retained data or historical evidence.
- batch_items: 0 -> 0 rows; 16384 baseline bytes; KEEP; shared contract, retained data or historical evidence.
- breakdowns: 0 -> 0 rows; 16384 baseline bytes; KEEP; shared contract, retained data or historical evidence.
- campaigns: 112 -> 59 rows; 24576 baseline bytes; CLEAN DATA; confirmed Meta-only rows archived and removed.
- creatives: 958 -> 31 rows; 1351680 baseline bytes; CLEAN DATA; confirmed Meta-only rows archived and removed.
- daily_metrics: 538 -> 533 rows; 1679360 baseline bytes; CLEAN DATA; confirmed Meta-only rows archived and removed.
- economics_assignments: 0 -> 0 rows; 40960 baseline bytes; KEEP; shared contract, retained data or historical evidence.
- economics_audit_log: 1 -> 1 rows; 155648 baseline bytes; KEEP; shared contract, retained data or historical evidence.
- economics_evaluations: 8 -> 8 rows; 327680 baseline bytes; KEEP; shared contract, retained data or historical evidence.
- economics_grants: 0 -> 0 rows; 24576 baseline bytes; KEEP; shared contract, retained data or historical evidence.
- economics_profiles: 1 -> 1 rows; 81920 baseline bytes; KEEP; shared contract, retained data or historical evidence.
- entities: 1668 -> 377 rows; 1204224 baseline bytes; CLEAN DATA; confirmed Meta-only rows archived and removed.
- entity_current_state: 710 -> 346 rows; 917504 baseline bytes; CLEAN DATA; confirmed Meta-only rows archived and removed.
- hourly_metrics: 0 -> 0 rows; 16384 baseline bytes; KEEP; shared contract, retained data or historical evidence.
- manual_action_grants: 0 -> 0 rows; 24576 baseline bytes; KEEP; shared contract, retained data or historical evidence.
- manual_grant_audit: 0 -> 0 rows; 49152 baseline bytes; KEEP; shared contract, retained data or historical evidence.
- media_buyer_cooldowns: 0 -> 0 rows; 8192 baseline bytes; KEEP; disabled feature; retained schema for compatibility.
- media_buyer_profiles: 0 -> 0 rows; 32768 baseline bytes; KEEP; disabled feature; retained schema for compatibility.
- meta_operations: 0 -> 0 rows; 16384 baseline bytes; KEEP; shared contract, retained data or historical evidence.
- meta_pilot_sessions: 1 -> 0 rows; 65536 baseline bytes; CLEAN DATA; confirmed Meta-only rows archived and removed.
- meta_rate_states: 0 -> 0 rows; 16384 baseline bytes; KEEP; shared contract, retained data or historical evidence.
- meta_request_attempts: 0 -> 0 rows; 24576 baseline bytes; KEEP; shared contract, retained data or historical evidence.
- meta_request_queue: 0 -> 0 rows; 16384 baseline bytes; KEEP; shared contract, retained data or historical evidence.
- provider_account_mappings: 12 -> 9 rows; 57344 baseline bytes; CLEAN DATA; confirmed Meta-only rows archived and removed.
- provider_catalog: 1336 -> 45 rows; 4104192 baseline bytes; CLEAN DATA; confirmed Meta-only rows archived and removed.
- provider_connections: 2 -> 2 rows; 65536 baseline bytes; SIMPLIFY; minimal disconnected Meta configuration; MetricFlow preserved.
- provider_credentials: 0 -> 0 rows; 32768 baseline bytes; KEEP; shared contract, retained data or historical evidence.
- provider_job_audit: 0 -> 0 rows; 24576 baseline bytes; KEEP; shared contract, retained data or historical evidence.
- provider_jobs: 13 -> 12 rows; 90112 baseline bytes; CLEAN DATA; confirmed Meta-only rows archived and removed.
- provider_routing_settings: 1 -> 1 rows; 24576 baseline bytes; KEEP; shared contract, retained data or historical evidence.
- provider_switch_events: 30 -> 27 rows; 40960 baseline bytes; CLEAN DATA; confirmed Meta-only rows archived and removed.
- provider_windows: 51 -> 49 rows; 65536 baseline bytes; CLEAN DATA; confirmed Meta-only rows archived and removed.
- raw_snapshots: 2194 -> 2194 rows; 13262848 baseline bytes; KEEP; shared contract, retained data or historical evidence.
- read_statistics: 1040 -> 1040 rows; 2367488 baseline bytes; KEEP; shared contract, retained data or historical evidence.
- recommendation_settings: 0 -> 0 rows; 16384 baseline bytes; KEEP; shared contract, retained data or historical evidence.
- rule_audit_log: 0 -> 0 rows; 155648 baseline bytes; KEEP; shared contract, retained data or historical evidence.
- rule_cooldowns: 0 -> 0 rows; 8192 baseline bytes; KEEP; shared contract, retained data or historical evidence.
- rule_grants: 0 -> 0 rows; 24576 baseline bytes; KEEP; shared contract, retained data or historical evidence.
- rule_runs: 0 -> 0 rows; 32768 baseline bytes; KEEP; shared contract, retained data or historical evidence.
- rule_simulations: 0 -> 0 rows; 131072 baseline bytes; KEEP; shared contract, retained data or historical evidence.
- rule_versions: 0 -> 0 rows; 155648 baseline bytes; KEEP; shared contract, retained data or historical evidence.
- rules: 0 -> 0 rows; 147456 baseline bytes; KEEP; shared contract, retained data or historical evidence.
- sync_leases: 0 -> 0 rows; 40960 baseline bytes; KEEP; shared contract, retained data or historical evidence.
- sync_runs: 860 -> 860 rows; 286720 baseline bytes; KEEP; shared contract, retained data or historical evidence.
- telegram_commands: 0 -> 0 rows; 24576 baseline bytes; KEEP; disabled feature; retained schema for compatibility.
- telegram_cursors: 0 -> 0 rows; 8192 baseline bytes; KEEP; disabled feature; retained schema for compatibility.
- telegram_users: 0 -> 0 rows; 24576 baseline bytes; KEEP; disabled feature; retained schema for compatibility.
- tracker_metrics: 0 -> 0 rows; 16384 baseline bytes; KEEP; shared contract, retained data or historical evidence.
- user_column_presets: 1 -> 1 rows; 81920 baseline bytes; KEEP; shared contract, retained data or historical evidence.
- user_sessions: 1 -> 1 rows; 98304 baseline bytes; KEEP; shared contract, retained data or historical evidence.
- user_table_preferences: 3 -> 3 rows; 90112 baseline bytes; KEEP; shared contract, retained data or historical evidence.
- users: 1 -> 1 rows; 98304 baseline bytes; KEEP; shared contract, retained data or historical evidence.
- write_credential_audit: 5 -> 5 rows; 40960 baseline bytes; KEEP; shared contract, retained data or historical evidence.
- write_credential_states: 1 -> 1 rows; 32768 baseline bytes; KEEP; shared contract, retained data or historical evidence.

Foreign keys: all validated; deletion order respects dependencies, no CASCADE.
Indexes and module imports are inventoried in .tools/full-audit/baseline.json and dependencies.json.


## Final validation (2026-10-14)
- Backend full suite: 609 passed, 1 skipped, 78 subtests passed (782.61 seconds).
- Frontend: 36 unit tests passed; TypeScript and production build passed.
- Playwright: 35 distinct scenarios passed across partitioned runs: economics 4,
  selection/targeting 7, navigation 7, rules 3, manual control 5, integrations 9.
  The first combined run had 3 failures and 6 unexecuted tests. Investigation found
  stale restored facts, eight fixture cookies exhausted by combined suites, a
  source-account/canonical-account mismatch, and API 429 under burst test load.
  Manual Control now uses its existing source-account options. Only existing
  MetricFlow states were copied into the isolated DB, preserving observed_at.
  Navigation and rule permissions passed independently without raising limits,
  disabling assertions, or fabricating advertising facts. This is partitioned
  acceptance, not a claim that the original combined command passed.
- PostgreSQL: six isolated concurrency/CAS/budget checks passed.
- Global Meta gate: 8 processes, 1 permit, 7 denied; restart denied; 1800-second
  persistent spacing; zero external HTTP. Pilot journal/budget race: 20 reserved,
  20 logged, 12 denied, zero external HTTP.
- Fresh migration image: isolated restored database remained at 0015_meta_pilot,
  all 70 table digests unchanged; no working migration or volume deletion.
- Ruff and format checks passed for the seven changed limiter/API/new-test files.
  Existing terse legacy files were reviewed; no whole-repository lint claim.
- Production READ observed after cleanup: MetricFlow success 2026-10-14T16:10:01Z;
  32 existing AD states fresher than 12 minutes. No new credential probe performed.

The completed scope is audit, approved cleanup, navigation simplification,
global Meta safety and local/manual acceptance. Overall project remains PARTIAL:
local Smart Rules automation gaps and the external WRITE contract are listed in
RULE_ENGINE_END_TO_END.md and the roadmap. They are not passed criteria.


## Working deployment and integrity
Verified backend/worker/scheduler/frontend images deployed with --no-deps. PostgreSQL,
Redis and Credential Manager were not recreated; working migrate was not rerun.
Seven working services running; backend, Credential Manager, PostgreSQL and Redis
healthy; migrate exited 0. Backend /health/live and /health/ready returned 200.
Eight changed runtime source files matched across backend/worker/scheduler.

All 20 protected user/preferences/economics/rules/actions/credential/routing table
counts and digests matched before/after deployment. .env SHA256 unchanged. The
four safety flags remain false/true/false/false. Authorization session/version
gates remain empty. Meta disconnected revision 4, no credential, no active jobs,
no pilot sessions, no physical HTTP journal attempts; five protected Meta account
identities retained. Standard Meta beat entries: 0. MetricFlow READ revision 1
healthy, last success observed at 2026-10-14T16:20:01Z. The observed READ history
is real production evidence; all action and Meta transport acceptance is local/mock.

Previous image IDs and integrity evidence are retained privately in
.tools/full-audit/deployment-initial.json and deployment.json. Isolated acceptance containers stopped after
testing; restored database, encrypted fixtures and verified backup retained.
No volumes deleted. No secrets included in tracked reports.

PROJECT STATUS: PARTIAL
METRICFLOW READ: PRODUCTION READ VERIFIED
RULE ENGINE: LOCAL DRY RUN VERIFIED / AUTOMATION PARTIAL
SELECTION & TARGETING: READY LOCAL
MANUAL CONTROL: READY LOCAL PREPARATION/SIMULATION
METRICFLOW LIVE WRITE: BLOCKED
META API: DISCONNECTED (optional transport safety LOCAL/MOCK VERIFIED)
DATABASE CLEANUP: 4256 APPROVED ROWS REMOVED / PROTECTED DATA PRESERVED
DUPLICATE SETTINGS: 2 REMOVED
ADVERTISING WRITE DURING WORK: 0
META LIVE REQUESTS DURING WORK: 0

Final import cleanup: 8 worker/global-gate regression tests passed; final images
rebuilt and rechecked against all eight changed files in three services. Backend
health endpoints and working frontend login returned 200. Secret scan and staged
diff checks passed; user-owned roadmap and historical reports excluded from commit.
