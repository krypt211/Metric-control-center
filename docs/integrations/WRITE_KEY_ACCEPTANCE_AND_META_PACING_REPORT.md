# WRITE KEY ACCEPTANCE AND META PACING REPORT

Verification date: 2026-10-13 Europe/Moscow. Evidence timestamps below use UTC.
Repository baseline: 191aa8a; PostgreSQL revision: 0013_integrations.

## Status summary

| Area | Result |
|---|---|
| WRITE credential | CONFIGURED, encrypted, revision 1 |
| Credential Manager / UI | READY for storage and GET-only verification |
| campaigns:read | PRESENT, observed in live GET /me |
| campaigns:write | ABSENT in observed response; NOT CONFIRMED |
| entities:write | PRESENT; equivalence to campaigns:write UNVERIFIED |
| access_state | active_paid |
| Subscription | Active paid access confirmed; exact plan/expiry not audited |
| Asset-specific permissions | UNVERIFIED |
| READ after WRITE | PASS: independent READ GET /me |
| Meta HTTP controller | PASS LOCAL/MOCK |
| Full Meta job lifecycle acceptance | PARTIAL: stale durable manual jobs lack TTL |
| MetricFlow LIVE advertising control | BLOCKED |
| Advertising WRITE requests | 0 |

ACTIONS_ENABLED=false, LOCAL_READ_ONLY=true, AI_ENABLED=false,
AI_AUTOPILOT_ALLOWED=false verified on the working backend and private service.
Meta remains disconnected/disabled. Action Engine was not activated.
Existing user changes in docs/roadmap.md and docs/phase4/* excluded.

## 1. Measured WRITE acceptance

The user's separate WRITE credential is present in write_credential_states.
Fernet envelope decrypts with the private WRITE vault; stored text does not
contain the plaintext token. Token equality was compared privately using
nonce-bound HMAC: READ and WRITE are DIFFERENT. No tokens/hashes/ciphertexts
are included in this report or command output.

Credential Manager performed two documented GET /api/v1/me checks:
first diagnostic, then acceptance after the scope-parser fix.
Both returned HTTP200 and access_state=active_paid.
The final check was 2026-10-12T22:04:27.534223Z, WRITE revision remained1.
The temporary ADMIN session was removed; no existing user/session was altered.

Observed relevant scopes: campaigns:read, entities:write, ad_accounts:write.
There is no exact campaigns:write. Other reported scopes include
accounts:connect, team:impersonate and team:manage. These are NOT evidence
of ownership or mutability of any particular AD.

A real response exposed a metadata-parser defect: verbs other than read/write
caused the entire scope list to be dropped. The parser now accepts bounded
safe scope syntax for metadata, while authorization still requires the exact
campaigns:write string. Regression tests cover ai:use/seeding:* and ensure
entities:write never becomes campaigns:write implicitly. Final stored status:
PERMISSIONS_PARTIAL, scope_verified=false, asset permissions UNVERIFIED.

[Official MetricFlow API docs](https://metricflowit.click/docs) document GET/me
for scopes/access_state and name campaigns:write for advertising management.
The actual key reports entities:write instead. Provider clarification is required;
do not assume the key is unusable, interchangeable, or sufficient for a live AD.

## 2. READ independence and revisions

A separate READ GET/me after WRITE acceptance succeeded:
READ-only scopes confirmed; access_state=active_paid.
READ connection remains healthy/enabled, credential_source remains independent.
READ connection revision1 unchanged; WRITE credential revision1 unchanged.
WRITE ciphertext unchanged by verification. Existing scheduled READ syncs
also completed successfully after the user added WRITE.

WRITE cipher is mounted only in private credential-manager, not backend or
READ workers. The private service has no public port and a restricted DB role.
The checks use the existing shared local 800/day MetricFlow budget/cooldown,
no retries, and no scope/asset probing via advertising POSTs.
Quota observed before the final checks:333/800 UTC2026-10-12, not exhausted.
Two WRITE GETs and one explicit READ GET were made by this acceptance;
ordinary scheduled READ traffic continues separately.

UI mock acceptance after the fix:7/7 Chromium tests, including independent
encrypted lifecycle, roles and widths1440/1024/768/390. Working provider key
was never entered into test fixtures. Private service rebuilt/recreated healthy.
No READ worker/backend restart was needed for the parser fix.

## 3. Calculated logical task volume

Actual worker schedule was inspected, not inferred from provider tariffs.
Meta today: every10min =>144/day.
Meta yesterday: minute5 each hour =>24/day.
Meta last7:04:09 scheduler timezone =>1/day.
Total:169 logical scheduled Meta tasks/day, not169 HTTP requests.

With Meta disabled these tasks return disabled and send0 Meta HTTP requests.
The shared ingestion schedule additionally has171 MetricFlow sync tasks/day
and2880 provider-dispatch ticks/day:340 sync +2880 dispatch=3220 scheduled
task opportunities, excluding any manual tasks. Rules/actions/AI schedules
are absent in current READ-only mode.

Meta task expiry: today540s, yesterday3300s, reconciliation82800s.
Dispatcher messages expire25s; dispatched manual messages expire55s.
These message deadlines do not imply expiration of the durable DB job.

## 4. Forecast HTTP load with pagination

FORECAST, not measured Meta LIVE traffic. Local saved catalogue has8 reference
accounts; rounded per-account average:7 campaigns,20 adsets,22 ads,120 creatives.
Pages are100 rows. Four catalogues need5 pages/account; AD-level Insights
assumes one row per AD/day. Auth/permissions/full account roster need3 requests
while the8-account roster fits one page. Selection does not shrink that roster.

Actual schedule windows include +/-1day:
today and yesterday use3 dates, last7 uses9 dates.
One-page theoretical minimum is3+5N; the catalogue-based estimates follow:

| Selected accounts | today/yesterday HTTP | last7 HTTP | HTTP/day no retries | Today pacing slots | Slots/day |
|---:|---:|---:|---:|---:|---:|
|1|9|10|1522|100s|16920s (19.6% of day)|
|3|21|24|3552|240s|40620s (47.0% of day)|
|max allowed:3|21|24|3552|240s|40620s (47.0% of day)|

Formula:168*HTTP(today)+HTTP(last7). Insights have local pacing weight2;
other requests weight1; interval10s. Weight is not a Meta complexity score.
Slots include the tail pacing interval and omit HTTP/DB latency.
Retry upper bound3x gives4566/10656 requests; this is a bound, not expected
traffic. The three-account bound exceeds the existing local Meta cap5000/day,
so quota would stop further requests. Limits were not increased.

A deterministic single-server full-day forecast at the actual schedule:
169 jobs complete with0 expired, maximum queue waits60s/240s for1/3 accounts.
This model is deliberately conservative about serial service but excludes
MetricFlow contention, manual work, latency, retries and cooldown.
It demonstrates stable baseline capacity, not a guarantee for large catalogues.
If most 10-minute jobs require >=600s, backlog/expiration becomes expected.
Live tier/header limits remain UNKNOWN; a10s interval is not proof of provider safety.

## 5. Measured and simulated queue tests

New isolated virtual-clock tests use the actual meter:
1 account =>8 minimum mock attempts;3/max3=>18; pacing slots>=10s
and>=20s after Insights; queue empty and owner released.
Expired HTTP tickets are removed without sending HTTP.
Cancelling an acquire waiter removes its ticket and sends0 HTTP attempts.

On independently restored PostgreSQL, three concurrent mock clients produced
HTTP attempt timestamps22:05:03.000182,22:05:12.993707,22:05:22.996187 UTC:
gaps9.994s/10.002s (actual dispatch includes small preflight jitter).
The expired queue ticket was cleared. A fourth mock attempt returned
429/code80004/subcode42 with99% utilization; cooldown persisted until
22:20:33.008365 UTC (minimum900s, not the unknown regain-access units).

A fresh container/process then read the same4 attempts and99% usage and
rejected another request during cooldown:0 new HTTP attempts.
Local journal rows retained GET method, category/page/attempt/status/duration,
code/subcode/usage/source and logical operation attribution.
No raw URL/token/response body was journalled.
Working workspace has0 new Meta HTTP attempts; all these attempts belong
to isolated restored DB fixtures.

Celery Request test on memory broker: expired message REVOKED, task body
executed0 times. Working Redis snapshot: ingestion ready0, unacked0.

## 6. Stale and duplicate READ jobs: exact acceptance gap

PASS: simultaneous identical GETs coalesce within the same client; existing
pagination/retry tests prove the journal counts actual attempts.
PASS: manual enqueue rejects a second active job for the provider with409.
PASS: concurrent Meta syncs use a renewable180s sync lease and skip overlap.
The lease is renewed before each reserved HTTP attempt.
PASS: expired periodic messages are revoked when a worker receives them.

PARTIAL: a synthetic180-day-old queued ProviderJob was still selected by
dispatch in a restored DB. Dispatch was intercepted with a mock, so no real
broker message/provider request occurred. There is no durable created_at TTL.
Manual batches may contain multiple date slices; stopping one duplicate
enqueue does not discard already queued obsolete slices.

PARTIAL: HTTP coalescing is per-client/inflight, not cross-process logical-job
deduplication. Sequential duplicates may consume requests. Cancelling a
caller does not necessarily terminate a shielded in-flight shared GET.
Celery message expiration is applied when consumed; it is not a hard bound
on broker storage during a worker outage.

Therefore uncontrolled accumulation is NOT proven impossible for every
job type/catalogue/outage. Current disabled Meta has no live backlog, and the
baseline forecast is stable. Before Meta LIVE, define/test durable job TTL,
semantic dedup keys, cancellation/recovery policy and queue size/SLO alerts.
No speculative cleanup of existing user jobs or limit increase was performed.

## 7. Validation and data preservation

Current run:55 integration/security tests passed;4 final pacing/scope tests
passed;7 UI checks passed. PostgreSQL mock concurrency/restart/cooldown and
Celery memory expiry passed separately. Ruff and format checks passed.
No schema migration needed; revision0013 retained. No volumes removed.
READ and WRITE secret contents/revisions were not replaced; only WRITE
verification metadata/audit was refreshed. No ActionExecution increase.
Backup/restored DB retained for inspection; UI mock stack stopped without -v.
Evidence is in ignored .tools/write-key-acceptance*, meta-pacing* files.

## 8. Precise LIVE contract blockers

| Item | Missing confirmed evidence |
|---|---|
|entity_id namespace|Whether pause/enable takes MetricFlow UUID, Meta ID, another ID, kind discriminator, and mapping to one chosen AD/account; act_ account IDs do not establish entity namespace.|
|PAUSE_AD/ENABLE_AD request|Exact URL/version/method/body, required vs optional fields, validation and content type; empty body must not be assumed.|
|Response/error schema|Success indicator, sync/async acknowledgement, resulting configured/effective state, operation ID, all errors and partial/unknown outcomes.|
|Permissions|Meaning of entities:write vs documented campaigns:write; actor/team/owner context and object-specific permission verification endpoint.|
|Configured/effective status|Authoritative fields/enums, parent campaign/adset effects, mapping of PAUSED/ACTIVE and freshness semantics.|
|Idempotency|Header/key support, scope/retention, replay behavior and collision rules. Local dedup is not provider idempotency.|
|Timeout handling|Provider deadlines, accepted-but-response-lost handling, reconciliation before retry and bounded retry policy.|
|Readback verification|Confirmed READ endpoint/ID/fields, freshness, consistency delay, polling bounds and comparison with requested/configured/effective status.|

Public docs list pause/enable/budget routes but do not supply these complete
operation contracts. No wire adapter was implemented from guesses.
Active paid access and entities:write alone do not close the LIVE gates.

## 9. Next user actions

1. Ask MetricFlow support for dated/versioned pause/enable schemas and clarify
   why GET/me reports entities:write while public docs name campaigns:write.
   Do not replace a working key solely to manufacture a missing scope label.
2. Obtain object-permission and entity namespace evidence for one selected AD.
3. Confirm readback/idempotency/timeout/error contracts; then run mock acceptance.
4. For Meta, address durable job TTL/dedup/cancellation gaps before any separate
   connection test; verify live tier/headers only under separately authorized READ.
5. A controlled advertising WRITE still needs separate explicit authorization,
   one agreed object, one bounded action and a recovery/reconciliation plan.

Final: WRITE credential acceptance is PARTIAL (credential/payment/independence
PASS, exact advertising scope and assets UNVERIFIED). UI/Manager READY.
Meta HTTP pacing LOCAL/MOCK PASS, full job lifecycle PARTIAL.
MetricFlow LIVE actions BLOCKED. Advertising WRITE requests=0.
