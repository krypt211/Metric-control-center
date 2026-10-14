# Rule Engine end-to-end acceptance

Current acceptance: 2026-10-15. [Detailed core report](SMART_RULES_FINAL_ACCEPTANCE.md).
SMART RULES READY LOCAL; LIVE advertising WRITE remains BLOCKED.

Account -> Campaign -> AdSet -> Ad -> inherited/deduplicated target -> existing
SmartRule -> economics -> deterministic PAUSE/ENABLE/NOTIFY decision -> explicit
local ActionRequest -> shared ActionEngine preflight/confirmation/simulation ->
ActionLog. Automatic checks are DRY RUN every 30 minutes, PostgreSQL only.

Profile IANA timezone, completed calendar periods/DST, current status, ownership,
explicit permission, parent state, cross-rule conflicts, manual holds, cooldown,
idempotency, immutable explanation and notifications are locally tested.
Missing/stale/insufficient evidence never produces a LIVE action. Simulated pause
never proves ownership. Daily facts from a different timezone are held, not rebucketed.
Existing Decimal economics and Phase 3.1 targeting are reused.

Final backend 629 PASS, 1 SKIP, 78 subtests PASS; new core 20 PASS; frontend 36 PASS;
TypeScript/build PASS; 37 distinct Playwright scenarios passed (final core 28/28 plus integrations 9/9); seven PostgreSQL checks and migration/restart/data integrity PASS.

Before real control: authoritative MetricFlow WRITE contract and scopes/object
permission, exact adapter/mock timeout/idempotency/readback acceptance, one selected
AD, separate explicit user authorization and verified first controlled operation.
No second Rule Engine/Action Executor was created. Advertising WRITE in this phase: 0.
