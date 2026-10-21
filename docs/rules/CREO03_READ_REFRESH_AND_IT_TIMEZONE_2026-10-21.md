# Creo 03 — READ refresh and isolated IT calendar — 2026-10-21

## Result

Existing rule TEST - Creo 03 - PAUSE - IT is now revision 2, disabled DRY_RUN,
allow_reenable=false, next_evaluation_at=null. Only its explicit profile reference
changed. Target remains AD 120247730105960571 in act_1047962734516123.
New simulation: 500366ca-94d1-407d-bc81-b0945f08e448,
created 2026-10-21T17:06:58.943259+00:00 (20:06:58 Moscow).
Decision KEEP; condition is false: actual CPL 5.38333333 USD is below maximum
8.81355932 USD. window_complete=true, source_window_status=complete,
status_fresh=true, saved effective status CAMPAIGN_PAUSED.
Remaining reason ATTRIBUTION_UNVERIFIED; action_eligibility=false.
KEEP is a local analytical result, not permission to execute.

## Cause and READ evidence

The ordinary MetricFlow scheduler successfully imports recent dates. Its successful
runs did not revisit 28 September. The old single-day AD fact and status therefore
remained observed on 8 October. Separate pilot catalog GETs were not ingestion runs.
Before refresh, account windows for recent dates were complete; this did not prove
completeness of the selected 28 September historical window.

Docker daemon was unavailable at the initial check. Docker Desktop was started
normally; existing containers and volumes were not recreated. PostgreSQL became
available. No migrations, database restore, image deployment or scheduler settings
were changed. Existing MetricFlow scheduling was not newly enabled.

The official public OpenAPI was fetched successfully through direct HTTPS from the
backend after desktop urllib and the web reader failed. No credential was used for
this public fetch. SHA256:
f52bc8ca0691fa0e2f2b5a5de06aa74a897546b88705ee16851859138a2f3327.
Source: https://metricflowit.click/api/v1/openapi.json?lang=en.
GET /api/v1/insights documents ad_account_ids, from/to, level and cursor pagination.
Context7 returned unrelated products, which were not used as contract evidence.

A single bounded invocation reused existing SyncEngine, schema normalization,
lease, shared persistent quota, cursor checks and atomic publication. Query:
from=2026-09-28, to=2026-09-28, level=ad, limit=100,
ad_account_ids=act_1047962734516123. Additional row validation rejects any other
account before publication. Limits: 10 physical HTTP attempts, 8 pages, 5000 rows,
600 seconds. Existing READ credentials only; no WRITE credentials were unsealed.

Measured run e60c3912-5f5e-4025-8349-94d94b72b137: succeeded, 4 physical GETs,
7 ad/day rows, all for the selected account. Requests: account catalog, insights,
campaign catalog, adset catalog. Account catalog contained 4 accounts; their usual
metadata was refreshed by the existing importer. Facts for other accounts were not
requested by this manual run. No deletion or fabricated zero rows.
Source snapshot 2026-10-21T17:06:33.658705+00:00.
ProviderWindow was finalized only for the selected account and date after successful
complete import and credential revision recheck. No other account received a manual
window completeness assertion. Attribution remains null, consistent with the
existing MetricFlow adapter and absent attribution fields in InsightRow/InsightsResponse.
No assumed Meta attribution defaults were substituted.

A PostgreSQL custom dump and SHA256 were saved before import in ignored evidence.
This stage did not restore that dump or claim a new restoration test.

## Isolated profile

Created TEST - Creo 03 - IT - Los Angeles,
UUID 1149520b-deb4-4257-a306-c1249a195487, version 1,
timezone America/Los_Angeles. Financial inputs and safeguards copy the existing
IT profile 3f5e842d-4f14-4646-af7f-79538cf00d2f: payout 52 USD,
planned approval 20%, minimum ROI 18%, target ROI 50%; inherited sample and maturity
thresholds retained. Original profile, other profiles and other rules are unchanged.
No general assignment to the account/campaign/AD was created. The test rule alone
references the copy. Original rule revision 1 remains in version history.
Using IT economics here is the user's diagnostic choice, not a factual claim that
this ES-named campaign uses those commercial terms.

## Safety and remaining work

Before/after ActionRequest=9, ActionExecution=3. New advertising POST=0.
Backend and Credential Manager: ACTIONS_ENABLED=false, LOCAL_READ_ONLY=true,
AI_ENABLED=false, AI_AUTOPILOT_ALLOWED=false, gate WRITE_DISABLED,
global live_status BLOCKED. MetricFlow READ revision 1 remains healthy;
WRITE credential unchanged. Meta disabled/disconnected revision 4.
The group pilot's late manual readback remains UNKNOWN and was not rewritten.
Production source code, dependencies, frontend and database schema did not change.

Manual UI check: open /rules, TEST - Creo 03 - PAUSE - IT, revision 2.
Verify profile TEST - Creo 03 - IT - Los Angeles, date 28 September,
calendar America/Los_Angeles, KEEP, complete window, fresh status, and remaining
attribution warning. Keep rule disabled; do not enable advertising or its parents.

A future live rule test needs documented/proven attribution, rule-bound permission
and bounded readback. Current numerical condition is false; executing PAUSE as if
this rule had triggered would be incorrect. Synthetic threshold tests remain
separate from production facts. Global automation is not authorized.

Ignored evidence: .tools/rules-read-refresh-20261021/ (result.json,
read-contract.json, refresh-and-profile.py, backup.json, runtime-after-*.json).

## Validation

Executed in this stage: tests/test_sync.py, tests/test_economics.py,
tests/test_economics_core.py, tests/test_controlled_sync_status.py.
82 tests PASS, 2 subtests PASS, 67.28 seconds; local fixtures/mock transports.
Basic source secret scan PASS. The production configuration/import assertions
passed against PostgreSQL. No new Playwright/frontend run was performed in this
configuration-only stage. Manual UI verification is the next checkpoint.
