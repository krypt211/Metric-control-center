# Creo 06 DRY RUN checkpoint ? 2026-10-17

All times below are Europe/Moscow (UTC+03:00).

## Scope and current outcome

Account: Valya Sergeeva / act_1047962734516123.
AD: #70495691_EGR_Creo 06 / 120247747556780571.
Rule: 9cf962b0-a2ed-4b87-9e74-7695aedb8efd, revision 2,
TEST ? Creo 06 ? PAUSE. Profile: MX AD, revision 1.
Period: 2026-10-10 through 2026-10-16, America/Los_Angeles.
Scheduler remains disabled for this rule. No new rule simulation was executed by
this maintenance step; the user's last recorded simulation remains DATA_STALE.

## Why the user's first rule check held

Simulation 0da8f2c2-3d7c-4d8f-b6d2-b9717627047f completed at 22:21:12.
It selected exactly one AD, with no target issues and no missing profile.
Spend was 612.28 USD; leads 215; actual CPL 2.84781395 USD;
maximum CPL from the profile 7.11864407 USD.
The condition was UNKNOWN, not FALSE, because SOURCE_STALE prevented evaluation.
The full historical window was last imported at 04:07:08; later normal syncs
refreshed recent days and AD status but not the complete requested period.
The existing source router requires every selected coverage window to have been
imported within 1800 seconds. The normal last7 job runs daily at 04:07 Moscow.
Consequently a healthy connection does not establish freshness for seven days.
ATTRIBUTION_UNVERIFIED is a separate remaining action blocker.

## One existing READ sync, measured

The existing services.providers.sync.metricflow_sync path was invoked once for
2026-10-10..2026-10-16 with job=manual, the existing READ credential, quota and lease,
and a 180-second outer timeout. This existing import is cross-account: the rule's
single-AD scope does not scope ingestion. No new ingestion mechanism was added.

Run: 96fa2abc-2f2b-46f2-b5fa-bf5cc47203b1.
Started 22:26:09; finished 22:26:18; succeeded; error_code null.
Physical provider READ attempts: 9; pages: 9; imported daily rows: 186.
Local daily quota: 106 -> 115 out of 800; cooldown absent.
The existing importer reported 4 accounts, 31 campaigns, 62 adsets and 62 ads.
The selected AD now has all seven daily rows observed at 22:26:09, with unchanged
aggregate spend/leads. The selected ProviderWindow is complete at credential
revision 1, imported 22:26:18; source timestamp 22:25:02; attribution remains null.

A subsequent existing DataSourceRouter check in a PostgreSQL READ ONLY transaction
returned mode=primary, stale=false, reason=null, facts_readable=true,
window_status=complete and connection=healthy. No new simulation history was made.
This source freshness result is point-in-time and expires under the unchanged
30-minute coverage policy (approximately 22:56:18 for the imported window).

The first launch stopped at a local assertion BEFORE creating a sync run or HTTP:
the worker has unset AI_ENABLED/AI_AUTOPILOT_ALLOWED and defaults them to false.
The successful one-off process explicitly set both to false using docker exec -e;
Compose, existing containers and .env were not changed. A first local router
inspection used the wrong session context; it made no changes and was corrected
before recording the successful read-only result above. No provider retry was
used to correct either local invocation issue.

## Official attribution evidence and remaining boundary

Official public source (fetched without credentials):
https://metricflowit.click/api/v1/openapi.json?lang=en
SHA256: f52bc8ca0691fa0e2f2b5a5de06aa74a897546b88705ee16851859138a2f3327
334703 bytes, MetricFlow Public API version 1.0.0.

GET /api/v1/insights documents from/to, level, ad_account_ids, fields, currency,
limit and cursor and an InsightsResponse schema. The examined specification does
not provide an attribution window/reporting-basis response contract for this
endpoint. Its attribution_spec property belongs to AdsetSpec creation input;
it is not evidence of the attribution used by these historical insight rows.
The local MetricFlow insight importer intentionally stores attribution=None.
No parameter, permission or attribution value was invented or written locally.
POST /api/v1/sync was not called: it would trigger provider-side synchronization.

Context7 resolution did not return this MetricFlow product; unrelated dbt,
Sitejabber and TikTok documentation was not substituted. The web reader could
not access these pages, so the public official OpenAPI was retrieved directly.

With fresh evidence, a false CPL condition may yield KEEP without authorizing an
action; a true condition with missing attribution must remain held/reviewed.
A positive production-evidence WOULD_PAUSE -> manual preparation path remains
blocked until provider-authored attribution semantics and remaining evidence
requirements are satisfied. These are not bypassed by a local test threshold.

## Preservation and verification

Before/after comparisons confirmed unchanged rule/profile/selected-AD commands,
encrypted READ credential records and .env bytes. No actual WRITE credential was
used. The only AD command remains the earlier SIMULATED manual PAUSE request;
ActionExecution rows for this AD remain zero. No Meta live request was sent.
ACTIONS_ENABLED=false, LOCAL_READ_ONLY=true, AI_ENABLED=false and
AI_AUTOPILOT_ALLOWED=false remain preserved in the configured environment.

Existing focused mock/fixture regression: 20 PASS, 32 deselected in 2.56 seconds:

    python -m pytest tests/test_smart_rules.py tests/test_smart_completion.py \
      -k 'truth_tables or forecast_signal_and_simulation_policy or unknown_actual_and_three_value_expression or currency_and_incomplete_guard or missing_stale_never_actions or profile_timezone_calendar_dst_and_validation' \
      -q -p no:cacheprovider

No product source, dependency, migration, frontend or safety gate was changed.
No broader backend/frontend/Playwright claim is made for this maintenance step.
Advertising WRITE requests in this step: 0. MetricFlow READ attempts: 9.

## Next user step

Keep rule revision 2/profile revision 1, one AD, the same period and schedule off.
While the imported coverage remains fresh, use the existing authenticated UI
Check Rules action once, then inspect its persisted simulation. Do not assert a
KEEP or WOULD_PAUSE result before that run. If freshness has expired, inspect the
current coverage first rather than repeatedly scheduling historical refreshes.
Before any positive actionable acceptance, obtain documented historical insight
attribution semantics from MetricFlow; do not treat creation-input examples as
read evidence or lower safeguards. LIVE dispatch remains blocked separately.
