# Exact-scope reported-spend rule experiment - 2026-10-22

## User agreement and scope

The user agreed to PREPARATION of one separate spend-only test. No advertising
POST was authorized. Existing strict financial rules and their saved results
remain unchanged. This implementation uses the existing experimental pilot;
there is no new dispatcher, provider HTTP contract, scheduler or global switch.

Policy: CREO03_REPORTED_SPEND15_V1.
Preparation acknowledgment:
PREPARE_ONE_CREO03_SPEND_TEST_WITHOUT_FINANCIAL_CERTIFICATION.
Future authorization statement (not supplied by this agreement):
AUTHORIZE_ONE_EXPERIMENTAL_REPORTED_SPEND_PAUSE_WITH_UNVERIFIED_ID.

Only default workspace; MetricFlow account act_1047962734516123;
AD 120247730105960571; adset 120247730105950571;
campaign 120247730079240571. Both parents must be configured PAUSED according
to the existing fresh experimental catalog baseline. Own AD must be ACTIVE.
Operation only PAUSE_AD. No parent change, ENABLE, budget or bid operation.

Exact rule: disabled SMART_DRY_RUN, no scheduled evaluation, reenable forbidden,
one explicit AD target (no account/campaign/group/broad filters), one AND leaf:
actual reported USD SPEND_THRESHOLD >= 15, custom limit, multiplier 1.
Period exactly 2026-09-28, profile/account America/Los_Angeles, currency USD.
Other condition types, amounts, currencies, periods, calendars or targets are held.

## Evidence policy

Normal simulation remains REVIEW when attribution is unknown. Its strict
eligible_for_rule_evaluation and safe_to_consider_for_future_action fields are
not promoted. The private preparation recomputes the same saved decision key
and adds a separate reported_spend_test_eligible result only for this experiment.
No attribution, approval or revenue value is fabricated, even transiently.

The policy accepts absent attribution/approved-sale certification ONLY for this
one spend-only experiment. It does not certify profitability or CPL/ROI/CPS.
Fresh complete scoped facts, correct currency/calendar, positive condition,
fresh saved entity observation, no manual block/unresolved command, current rule
revision, routing, credentials and exact identity are still required. Effective
parent-paused status is accepted as an analytic context only; configured ACTIVE
of the AD must separately pass the existing catalog baseline. The rule_source
records that baseline status for preflight, not a claim that a stored effective
status is configured status.

The special policy is present in both source and frozen RulePilotBinding, covered
by the existing source/evidence hashes. Missing/changed policy, source or binding
holds authorization/execution. Manual and strict-rule authorization statements
are rejected. It is revalidated before authorization, execution, catalog reads
and POST using the existing provider contract. An earlier authorized request
using this policy prevents another request, including after a timeout/cancel.
The request itself remains revalidatable after its durable claim; only that
validated request is excluded from conflict checks.

This experiment is deliberately stricter than normal peer arbitration: any other
enabled nonarchived rule in the workspace blocks it. Opposite-action cooldown,
emergency-stop generation, unique pending claim, one physical POST maximum,
no resend, <=600-second permit and all existing transport/credential guards remain.

## Preparation path

ExperimentalPrepareInput accepts rule_evidence_policy (STRICT_FINANCIAL default)
and the explicit reported_spend_acknowledgement. The special policy requires
simulation_id and PAUSE_AD. The ordinary public manual-draft schema has no new
policy input. Existing private experimental preparation is used. Config/identity
are checked before unsealing credentials. Local draft and proof remain atomic.
The private endpoint retains its existing documented GET /me credential check;
that READ does not prove object-level permission. Stored READ and WRITE keys
remain independent and encrypted. No real WRITE key is created or replaced.

Before a real card, use existing bounded SyncEngine READ for the selected account
and historical day, with no other insights scope/backfill. Refresh cap 6 attempts,
max 6 pages / 5000 rows / 600 seconds; normal provider quota and revision guards
apply. Conditional card preparation adds one GET /me and at most 3 existing
catalog GETs (total preparation-stage cap 10 physical attempts). If refreshed
parent catalog already reports an enabled parent, stop before credential/card
READs and request manual correction/verification. No advertising mutation is
performed to satisfy a precondition. Execution would separately require 3 bounded
pre-POST catalog GETs and one separately authorized POST, no retries.

HTTP 200 is acknowledgment only. Manual readback must inspect own AD and both
parent switches by exact IDs. Timeout/ambiguous result stays UNKNOWN; no retry
or automatic ownership. Restoring the AD needs separate permission.

## Validation evidence

New mock suite: 22 PASS. It covers separate authorization, no resend on timeout,
strict result preservation, changed condition/scope/period/currency/calendar,
source freshness, manual block, parent baseline, enabled peers, previous policy
authorization, and changed spend after catalog reads. Restricted-role isolated
PostgreSQL checks PASS for both special and strict paths, actual read-only
financial evaluation, no residual draft on refusal, and denied financial writes.
No real provider HTTP in these tests. Full compatibility regression and local
rollout/preparation results are recorded below when completed.

No dependencies, frontend or database schema changes. Existing role SELECT grants
suffice. All four global safety flags remain closed; Meta remains disabled.
Ignored evidence: .tools/reported-spend-20261022/.


## Completed validation and rollout

Compatibility regression: 371 tests and 14 subtests PASS in 448.27 seconds.
Two additional effective-parent-status cases PASS (22 deselected); the special
suite now contains 24 cases, with overlap in the larger regression run. All three
restricted PostgreSQL harness runs PASS. Ruff formatting/lint and secret scan PASS.
Frontend did not change; no new Playwright run is claimed.

Deployed backend and Credential Manager image:
metric-control-center-reported-spend-20261022:prepared. Readiness, source hashes,
closed flags and restricted roles verified. Deployment preserved all 14 protected
table digests and other five service identities. No new grants/migrations were
needed. A fresh custom-format database backup was saved before rollout.

## Actual local test card and manual checkpoint

Existing SyncEngine performed 4 physical GETs, capped at 6, for the selected
account/day. Its scoped run cf80c033-cad9-4a54-a24e-21b43671fdf2 succeeded with 7
insight rows. The normal account catalog GET returned metadata for 4 accounts;
insights were explicitly filtered/validated to act_1047962734516123. No other
account's insight window or backfill was requested. Source timestamp:
2026-10-22T14:22:24.931821+00:00. No Meta API request was made.

New separate disabled rule: f0fc9bf5-d00c-4462-bd0e-9576a0288a6d, revision 1,
TEST - Creo 03 - SPEND15 - ONE POST.
Saved simulation: 0c60015a-1d94-487d-b6da-26856ee4a384.
Reported spend 16.15000000 USD; condition TRUE; private reported-spend eligibility
true. Strict simulation stays REVIEW, both strict financial eligibility fields
false, source_attribution null. It is not a financial certification.

Fresh parent catalog returned:
- Campaign 120247730079240571: status PAUSED / effective_status PAUSED.
- Adset 120247730105950571: status ACTIVE / effective_status CAMPAIGN_PAUSED.

The group is still ON, so the existing both-parents-PAUSED baseline is not met.
Private advertising-command preparation was deliberately not called. No GET /me
or extra catalog GETs were spent on a card that cannot pass this baseline. No
ActionRequest, advertising authorization or POST was created. Final request/
execution counts stay 9 / 3, all 3 executions historical. A scope check and fresh
baseline will still run via the existing mechanism after manual prerequisites
are satisfied; current private analytical eligibility is not a LIVE permit.

Required manual step, by exact IDs:
1. Open account 1047962734516123 and verify campaign 120247730079240571 is OFF.
   Do not enable it.
2. Open group 120247730105950571 (group 3). Turn its own switch OFF if still ON.
3. Open AD 120247730105960571 (#71012012_EGR_Creo 03). Leave its own switch ON
   for the PAUSE experiment; do not change the AD switch manually.
4. Confirm campaign OFF, group OFF, AD ON and the verification time.

This instruction is a manual prerequisite, not permission for the agent to send
PAUSE_ADSET. No such provider operation was sent or added to this pilot. After
manual confirmation, refresh/verify baseline, prepare a new request card, and
request separate explicit permission for one PAUSE_AD. No old permit is reusable.

Post-preparation integrity: ten other protected table digests unchanged (users,
profiles/assignments/approval observations, action requests/executions/logs,
READ/WRITE credential records and manual grants). Original rules and profiles
were checked individually unchanged; only the new rule/version/simulation/cooldown
and normal rule audit/evaluation records were added. Environment hash unchanged.
All four flags remain ACTIONS_ENABLED=false, LOCAL_READ_ONLY=true, AI_ENABLED=false,
AI_AUTOPILOT_ALLOWED=false. Advertising WRITE requests this stage: 0.

FINAL STATUS: DEPLOYED / MOCK AND POSTGRESQL VALIDATED;
LOCAL RULE REVIEW READY; BLOCKED ON MANUAL PARENT SWITCH CHECK;
LIVE RULE EXECUTION NOT AUTHORIZED / NOT EXECUTED.
