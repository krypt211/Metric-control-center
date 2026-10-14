# Rule Engine end-to-end acceptance

Status: LOCAL DRY RUN path implemented; automatic LIVE ON/OFF remains BLOCKED.

Existing path:
Account -> Campaign -> AdSet -> Ad -> target inheritance/deduplication ->
SmartRule (existing rule_versions) -> economics_adapter -> smart_core ->
RuleSimulation with facts/reasons -> explicit /manual-control/from-rule ->
ActionEngine manual draft/preflight/confirm/simulate -> ActionLog.
The rule bridge only accepts a matching WOULD_PAUSE result/revision and AD.
Manual ENABLE preparation exists; automatic ENABLE rule decisions do not.

The existing Decimal economic model is preserved: payout/approval/evidence,
CPL/CPS/ROI/profit and minimum data gates. No economic formula was changed.
Incomplete/stale/unknown or mismatched evidence cannot silently authorize WRITE.
Simulation and advertising action history remain distinct.
Current period function uses Europe/Moscow; an independently configured profile
timezone does not yet exist. Thus the requested arbitrary-profile-timezone
criterion is not accepted. Today remains subject to incomplete-window checks.

PostgreSQL CAS acceptance covers rule edits, target assignment, economics updates
and manual-action idempotency/concurrency. UI acceptance covers creation/editing,
selection/search/bulk assignment, calculation, simulation, persisted history and RBAC.
See final acceptance results in PROJECT_SIMPLIFICATION_REPORT.md.

Remaining local work before automatic actions:
1. Explicit pause/enable/notify-only action model for Smart Rules.
2. Per-profile evaluation timezone and tests for midnight/DST/mixed timezones.
3. Deterministic conflicting-rule resolution, cooldown/hysteresis preventing ON/OFF loops.
4. Bounded scheduled Smart Rules evaluation from fresh PostgreSQL statistics;
   current legacy scheduler task is held in LOCAL_READ_ONLY and is not this pipeline.
5. Confirmed provider contract -> one shared executor/readback/recovery path.
No claim of LIVE control follows from mock or local simulation acceptance.


## Measured local acceptance
Rules lifecycle, calculations, revision history, columns and RBAC: 3 distinct
Playwright scenarios passed (permissions rerun independently to respect local
API pacing). Selection/search/bulk assignment: 7 passed. Economics: 4 passed.
Manual draft/preflight/local-confirmation/simulation/audit: 5 passed, including
saved-rule eligibility and a separately labelled browser-only navigation mock.
PostgreSQL rule/economics/target/manual concurrency checks passed on an isolated
restored DB. Backend full suite: 609 passed, 1 skipped, 78 subtests passed.

The shared local bridge is accepted. Automatic ENABLE, configurable profile
timezone, conflict/hysteresis policy, scheduled Smart Rules execution and LIVE
transport are still incomplete. These gaps keep automatic management PARTIAL.
