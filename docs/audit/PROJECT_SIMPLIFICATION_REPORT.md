# Project simplification

Status: verified simplification scope; overall project PARTIAL.

## Measured changes
- Primary navigation: 8 -> 4 links plus Settings. Overview / Ads / Rules / History.
- Page routes: 9 -> 9. Existing deep links, columns, selectors and presets retained.
- Unused frontend module removed: components/MetaReadPilot.tsx (no remaining consumer).
- Standard Meta periodic definitions: 3 -> 0. Existing queued periodic tasks return
  disabled without constructing a provider. Actual working beat was already held,
  so its active entry count is 6 -> 6; no fabricated runtime savings.
- Meta interval edit controls: 1 -> 0. Effective interval is the server constant
  1800 seconds; pacing compatibility endpoint accepts only 1800, stores only scope.
- Duplicate 'choose primary' button removed; advanced routing editor remains.
- Two redundant configuration controls removed (interval override and routing shortcut).
- Pilot preparation panel removed. Meta usage and provider comparison/routing
  placed in ADMIN technical details. Read-only status displays are not duplicate settings.
- Production DB rows removed: 4256; tables 70 -> 70; no volumes deleted.
- Core service architecture unchanged: shared ingestion, shared executor/request
  model, independent credential service, PostgreSQL + Redis. No new queue or connector.

## Global Meta policy
One meta-global PostgreSQL state across App IDs/workspaces/accounts/processes.
Atomic permit and ownership fence, PostgreSQL clock, persistent next_start/cooldown,
one concurrent lease, 1800-second floor immediately before recording a physical
attempt. Existing per-app cooldown is preserved on first global-state creation.
Pagination/retries/auth/health use the same client/meter. Only httpx.MockTransport
may use a shorter test interval. Rate errors never trigger an automatic retry.
Pacing rejects early with META_PACING_WAIT instead of sleeping a worker for 30 minutes.
Disconnected provider checks and the existing pilot authorization gates remain.

Current optional full Meta sync is BLOCKED until durable continuation is designed:
a multi-request workflow cannot complete inside a 600-second pilot at 1800s spacing.
No TTL/limits were increased; no existing pilot was started. This is a transport
safety guarantee, not a claim that direct Meta synchronization is usable.

## Source of truth
Secrets: private stores, independent READ/WRITE revisions.
Deployment flags: environment, effective status read-only in UI.
Business rules/economics: existing PostgreSQL definitions.
Column presets: existing user preference tables.
Meta pacing: one code constant; no independent UI/DB/env override.
Routing: one PostgreSQL setting editor, advanced ADMIN section.

## Retained modules
Auth, CSRF, RBAC, action gates, durable jobs, audit and encryption are required
boundaries. Legacy rules/AI routes are held by existing runtime gates; removal
would break stored contracts and compatibility without completing LIVE support.
No unsupported WRITE transport was added.


## Acceptance
Backend 609 PASS, 1 SKIP, 78 subtests PASS. Frontend 36 PASS, typecheck/build PASS.
Playwright 35 distinct scenarios passed in partitioned runs; the initial combined
command failed, as detailed in PROJECT_FULL_AUDIT.md. All six PostgreSQL checks
and migration rehearsal passed. Limiter/API/new-test Ruff and format checks passed.

A browser regression exposed that Manual Control requested canonical rule-account
IDs while its API expects source-account IDs. The account picker now uses its
existing settings.accounts options. The shared searchable selector and Phase 3.1
selection/targeting were not redesigned; all seven targeting checks passed.

Remaining duplicate controls removed: 2. HTTP endpoints removed: 0 (compatibility
and security retained); backend service modules removed: 0; frontend modules
removed: 1. Environment name count remains 45; no secret configuration removed.
Forecast for the optional Meta connector: no scheduled jobs; at most 48 physical
attempts per 24-hour calendar window under the 1800-second policy. A workflow of
N attempts needs at least (N-1)*1800 seconds before the last attempt. This is a
policy calculation, not measured provider quota or LIVE throughput.


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
