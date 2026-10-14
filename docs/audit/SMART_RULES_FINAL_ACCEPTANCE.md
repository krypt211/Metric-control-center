# SMART RULES FINAL ACCEPTANCE

Report date: 2026-10-15, Europe/Moscow. Evidence timestamps and backups use UTC.
Baseline commit: f82af98. Acceptance is LOCAL/MOCK and DRY RUN; not PRODUCTION READY for advertising control.

## Completed core functionality

The existing flow now supports Account / Campaign / AdSet / Ad selection -> inherited,
deduplicated AD targets -> economics -> PAUSE_AD / ENABLE_AD / NOTIFY_ONLY decision ->
explicit local ActionRequest preparation -> the existing ActionEngine preflight,
confirmation and simulation -> ActionLog and rule history.
Campaign/AdSet selection expands to eligible Ads; no campaign/adset mutation was added.
Existing dynamic target resolution includes new catalog Ads on the next evaluation.

- SmartRule: action, enabled checks, integer priority, cooldown, explicit reenable policy.
  Existing definitions retain PAUSE/default-disabled semantics when new fields are absent.
  Enabling a rule only enables scheduled DRY RUN checks; mode remains DRY_RUN.
- Economic profile: validated IANA timezone, default Europe/Moscow for existing profiles.
  Closed seven-day ranges and Today use calendar dates in the profile zone. Spring
  23-hour and autumn 25-hour days are tested. Age/maturation guards use UTC elapsed time.
  Assigned profiles use their own calendar as well. Inherited scopes reuse the same
  adapter for at most eight profile zones; per-AD periods and decision keys remain
  separate. Date-dependent ambiguous assignments hold with PROFILE_PERIOD_AMBIGUOUS.
  Larger zone sets require an explicit profile.
  Daily facts are never guessed into another timezone: profile/source zone mismatch
  produces a safety hold. Today/incomplete or stale windows cannot authorize action.
- Existing Decimal payout, approval, ROI, CPL, CPS, minimum lead/sale calculations reused.
  No economic formula was changed; profile timezone is additive metadata.
- PAUSE: current AD status and fresh READ facts, threshold gates, duplicate target state,
  manual hold, conflicts and opposite-action cooldown checked before preparation.
- ENABLE: separate explicit positive conditions (ROI at/above target; CPL/CPS at/below
  a selected limit), positive spend, fresh evidence, rule allowance AND explicit
  per-rule/AD user allowance, current PAUSED state, fresh ACTIVE Campaign and AdSet,
  and the last verified MCC PAUSE history. SIMULATED never proves PAUSE ownership.
  Cost-only recovery requires a completed cohort ending before the verified pause;
  otherwise mature confirmed approval/revenue evidence is required. Zero spend or
  moving an expensive day out of a rolling window does not itself trigger ENABLE.
  Permissions, unknown outcome, external/unverified pause or parent pause -> REVIEW.
- Conflict order: explicit manual hold -> unknown/stale/insufficient/review evidence ->
  active PAUSE -> ENABLE -> KEEP. Within the same action tier: higher integer priority,
  then lexical rule ID. An active PAUSE condition also blocks ENABLE when already PAUSED.
  At most one actionable candidate survives for an AD; losing/uncertain candidates
  record hold reasons. No AI arbitration, extra weights or executor was added.
- Anti-loop: persisted ActionRequest history across rules and restarts; opposing action
  interval respects the larger current/previous recorded cooldown. Default 3600 seconds,
  configurable 1800..604800. Unknown execution outcomes hold new actions. Stable decision
  keys and the existing idempotency/pending-request gates prevent repeated preparation.
- Manual override: explicit AD hold across rules, persisted in existing cooldown rows.
  Clearing it clears the workspace's holds on that AD under the same lock and audit.
  Reenable allowance is per rule/AD until revoked; grants require both rule editing
  and existing Manual Control permission plus revision/CAS checks.
- NOTIFY_ONLY: existing RuleAuditLog stores object, rule, measured values, thresholds,
  decision, time and local history URL; the existing history UI displays them.
  Unchanged truth/threshold state is deduplicated even as source timestamps refresh.
  External channels remain disabled/unconfigured; no Telegram bot or external send.
- ActionEngine: both PAUSE and ENABLE use the existing manual lifecycle. Current rule
  revision, facts, permission, controls and peer conflicts are recomputed before draft
  and preflight/confirmation. Stale stored simulations cannot bypass current guards.
  Local success is SIMULATED / LOCAL_SIMULATION_ONLY, never a successful LIVE mutation.

## Scheduler

One existing Celery ingestion queue; smart_rules.evaluate every 1800 seconds,
message expiry 1700 seconds. It reads PostgreSQL and never constructs a provider,
uses a MetricFlow key, starts Meta, or requests an advertising mutation.
Existing legacy evaluator is not expanded or periodically scheduled.
The PostgreSQL workspace transaction lock prevents overlap with another evaluation
and configuration edits. next_evaluation_at survives worker restart and suppresses
repeated due-slot evaluation. Inactive/archived rules and revoked owners are held.
Bounds: 200 rules, 500 Ads/evaluation, 10-second elapsed evaluation guard, 60-second
scheduler work budget; no unbounded backfill or per-rule recurring job queues.
Existing MetricFlow sync cadence and quotas are unchanged.

## Components reused and additions

Reused: SmartRuleInput/Rule versions; smart_targets resolution/search; economics_adapter
and calculate; RuleSimulation; RuleCooldown; RuleAuditLog; shared ActionRequest,
ActionEngine and ActionLog; existing RBAC/CSRF; existing Celery worker/queue/pages.
New runtime modules/services/queues/engines/tables: **0**.
One additive column: rule_cooldowns.smart_state (JSON), migration 0016_smart_control.
One local authenticated control endpoint in the existing Smart Rules router.
One new scheduler task in the existing workers/rules.py, replacing the periodic
legacy rule entry. One backend acceptance test file, one PostgreSQL acceptance
script and one Playwright spec; these are test artifacts, not runtime subsystems.

## Verification

- Final full backend: **629 passed, 1 skipped, 78 subtests passed**, 784.38 seconds.
- New completion suite: **20 passed**, including inherited profile timezone; related Smart Rules/targeting regression: **87 passed**.
- Frontend: **36 unit tests passed**; TypeScript and production Next.js build passed.
- Playwright: **37 distinct scenarios passed**: final **28/28** core/action/targeting/
  permission/timezone scenarios, plus **9/9** integration/credential/Meta-safety
  scenarios. An earlier run had one accessible-label locator failure; corrected to
  the exact combobox role. The final complete core run is clean; no assertions or
  server limits were weakened.
- Smart Rules fixture browser traffic paced at 500 ms; local auth/API limit unchanged. Additional
  synthetic fixture cookies only apply to mcc_integrations_* restored test databases.
  Existing real READ states were copied to the isolated DB with observed_at unchanged.
- Seven PostgreSQL acceptance checks passed: economics/rule/target/manual CAS,
  global Meta permit, pilot attempt budget, new Smart Rules scheduler race/restart.
  New race: 8 processes -> 1 evaluation, 1 notification, no duplicate; new process held.
  Global Meta floor remains 1800 seconds; all transport acceptance is mock/no-network.
- Isolated migration upgraded 0015 -> 0016; 69 business-table counts/digests unchanged,
  all 70 tables retained. A second run returned ALREADY_CURRENT. No destructive migration.
- Ruff check and formatter check passed for 17 changed clean Python modules/harnesses.
  Existing terse storage/ingestion files were changed surgically and regression tested.
  No whole-repository lint claim. Basic secret/frontend-token scan and diff checks passed;
  only the 36 owned files are staged, excluding user edits and prior reports.

## Working deployment and data preservation

Fresh pre-deployment backup was restored and verified across all 70 tables.
Backup: E:\Creative_Factory\metric-control-center\backups\smart-rules-predeploy-20261014T212445Z\database.dump
SHA256: 79e385c43aa81146e791eedd328e5e8eeae35ae066a0d9b24a23a7d91a5b4fcb
Restore: mcc_integrations_audit_20261014_212445; owner + SYSTEM archive ACL.


Working migrate container applied 0016 once. Backend/worker/scheduler/frontend updated;
PostgreSQL, Redis and Credential Manager were not recreated. Existing credentials,
users, economics, rules, statistics, presets and history preserved. Counts/digests of
21 protected tables/old columns matched before/after migration and deployment;
new cooldown column is additive. The final source refresh performs no migration
reapplication. .env digest and WRITE state remained unchanged.
Twelve changed source files matched across backend/worker/scheduler. Health/readiness
and working frontend login returned 200. Seven long-running services retained;
working migrate exited successfully. No Docker volume deleted.

MetricFlow READ remains healthy; latest success observed at 2026-10-14 21:50:01.826918+00:00 (UTC).
WRITE scope verification was not repeated LIVE in this phase. The independent stored
WRITE credential is unchanged; cached entities:write does not prove campaigns:write,
object permission or a usable advertising wire contract. Meta is disconnected, no
credential restored, no active Meta jobs or physical HTTP attempts. Its standard
scheduler remains absent. Pilot authorization/version gates remain blank.

ACTIONS_ENABLED=false
LOCAL_READ_ONLY=true
AI_ENABLED=false
AI_AUTOPILOT_ALLOWED=false

## Remaining before one real WRITE

1. Obtain authoritative MetricFlow Business WRITE specification: scopes, entity_id
   namespace/binding, PAUSE/ENABLE method/path/body, responses/errors, object-level
   permissions, configured/effective statuses, idempotency, timeout/unknown-outcome
   recovery and bounded READ readback.
2. Implement only the confirmed adapter in the existing shared executor; mock all
   success/denial/rate-limit/timeout/readback and duplicate outcomes. No guessed HTTP.
3. Choose one AD and obtain separate explicit user authorization for one operation.
   Execute one bounded PAUSE only after those checks, verify READ readback, audit,
   restore safety flags. ENABLE then additionally needs verified ownership, explicit
   allowance, active parents and fresh positive evidence. Broader automation follows
   a separately accepted single-AD pilot, not this local readiness report.

SMART RULES: READY LOCAL
PAUSE: READY LOCAL
ENABLE: READY LOCAL (conditional ownership/permission/evidence gates)
NOTIFY: READY LOCAL (MCC journal)
RULE SCHEDULER: READY DRY RUN
METRICFLOW READ: PRESERVED
METRICFLOW LIVE WRITE: BLOCKED
META LIVE REQUESTS DURING THIS PHASE: 0
ADVERTISING WRITE REQUESTS DURING THIS PHASE: 0

## Changed files

- `README.md`
- `backend/manual_control_api.py`
- `backend/smart_rules_api.py`
- `docs/audit/RULE_ENGINE_END_TO_END.md`
- `docs/audit/SMART_RULES_FINAL_ACCEPTANCE.md`
- `docs/roadmap/FINAL_MCC_ROADMAP.md`
- `frontend/components/EconomicProfiles.tsx`
- `frontend/components/RuleDecisionDetails.tsx`
- `frontend/components/RuleExpression.tsx`
- `frontend/components/SmartRules.tsx`
- `frontend/e2e/accounts.py`
- `frontend/e2e/economics_accounts.py`
- `frontend/e2e/provider_accounts.py`
- `frontend/e2e/rules-fixtures.mjs`
- `frontend/e2e/rules_accounts.py`
- `frontend/e2e/session-fixture.py`
- `frontend/e2e/smart-controls.spec.mjs`
- `frontend/lib/economics.ts`
- `frontend/lib/smart-rules.ts`
- `migrations/versions/0016_smart_control.py`
- `scripts/check_rule_targets_postgres.py`
- `scripts/check_rules_postgres.py`
- `scripts/check_smart_control_postgres.py`
- `scripts/prepare_integration_acceptance.py`
- `services/actions/manual.py`
- `services/automation/smart_core.py`
- `services/automation/smart_schema.py`
- `services/automation/smart_simulation.py`
- `services/automation/smart_store.py`
- `services/economics/schema.py`
- `services/economics/store.py`
- `services/storage/models.py`
- `tests/test_manual_actions.py`
- `tests/test_smart_completion.py`
- `workers/ingestion.py`
- `workers/rules.py`

Private raw evidence and rollback image IDs: .tools/smart-rules/.
User-owned docs/roadmap.md and prior untracked reports are excluded from this stage.
