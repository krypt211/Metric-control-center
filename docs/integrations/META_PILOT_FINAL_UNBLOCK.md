# META PILOT FINAL UNBLOCK

Date:2026-10-13 UTC. Scope: existing user-selected controlled READ session only.

META PILOT: READY FOR EXPLICIT AUTHORIZATION
META LIVE REQUESTS:0
ADVERTISING WRITE REQUESTS:0

This readiness is for a bounded diagnostic READ, not unrestricted Meta access.
This document does not grant permission. Both deployment gates remain empty.
No session, token, connection, runtime configuration or advertising data was changed.

## Decision and evidence boundary

Official SDK26.0.2 pins Graph APIv26.0 and defines the exact GET operations,
field names and Insights parameters used by this pilot. Official Graph API
reference retrieved via Context7 also explicitly documents v26.0/debug_token
and v26.0 user permissions. Local source comparison found no incompatible
requested field, unsupported attribution enum or method mismatch.

Under the user's explicit final-unblock criterion, this evidence is sufficient
to request permission for these bounded GET operations. The unavailable general
Meta Developers changelog is no longer treated as an independent blocker.
This is not certification of all APIv26 behavior, every field combination,
Meta's entire version lifecycle, app entitlement or actual token validity.

## First-party sources

- [SDK configuration26.0.2](https://raw.githubusercontent.com/facebook/facebook-python-business-sdk/26.0.2/facebook_business/apiconfig.py): API_VERSION=v26.0.
- [Official release26.0.2](https://github.com/facebook/facebook-python-business-sdk/releases/tag/26.0.2).
- [v26 release notes](https://github.com/facebook/facebook-python-business-sdk/releases/tag/26.0.0).
- [AdAccount generated GET definitions](https://raw.githubusercontent.com/facebook/facebook-python-business-sdk/26.0.2/facebook_business/adobjects/adaccount.py).
- [Campaign fields](https://raw.githubusercontent.com/facebook/facebook-python-business-sdk/26.0.2/facebook_business/adobjects/campaign.py).
- [Adset fields](https://raw.githubusercontent.com/facebook/facebook-python-business-sdk/26.0.2/facebook_business/adobjects/adset.py).
- [Ad fields](https://raw.githubusercontent.com/facebook/facebook-python-business-sdk/26.0.2/facebook_business/adobjects/ad.py).
- [Creative fields](https://raw.githubusercontent.com/facebook/facebook-python-business-sdk/26.0.2/facebook_business/adobjects/adcreative.py).
- [Insights fields and enums](https://raw.githubusercontent.com/facebook/facebook-python-business-sdk/26.0.2/facebook_business/adobjects/adsinsights.py).
- [User permissions GET definition](https://raw.githubusercontent.com/facebook/facebook-python-business-sdk/26.0.2/facebook_business/adobjects/user.py).
- [Permission fields/statuses](https://raw.githubusercontent.com/facebook/facebook-python-business-sdk/26.0.2/facebook_business/adobjects/permission.py).
- [Debug token reference](https://developers.facebook.com/docs/graph-api/reference/debug_token): Context7 retrieved explicit GET/v26.0 contract.
- [User permissions reference](https://developers.facebook.com/docs/graph-api/reference/user/permissions): Context7 retrieved explicit v26.0 GET and statuses.
- [Request signing](https://developers.facebook.com/docs/graph-api/guides/secure-requests): HMAC-SHA256 appsecret_proof.
- [Archived official app-token construction](https://raw.githubusercontent.com/facebookarchive/php-graph-sdk/5.x/src/Facebook/FacebookApp.php): app-ID pipe app-secret construction. Historical auth-format evidence only, not a current-version lifecycle source.

## Contract comparison

|Operation|Evidence / existing behavior|Result|
|---|---|---|
|debug_token|GET/v26.0, input_token, app access token; data.is_valid/app_id/scopes/expiry checks|Documented contract matches|
|me/permissions|SDK User GET/permissions; permission/status, granted/declined/expired; require ads_read|Matches; runtime token type/access unknown|
|One ad account|SDK AdAccount GET node,6 requested fields|No missing fields|
|campaigns|SDK GET/campaigns,9 fields|No missing fields|
|adsets|SDK GET/adsets,12 fields|No missing fields|
|ads|SDK GET/ads,9 top-level fields plus nested creative identity/thumbnail|No missing fields|
|adcreatives|SDK GET/adcreatives,5 fields|No missing fields|
|insights|SDK synchronous GET/insights,23 fields, explicit date range and attribution|No missing fields/enum/type mismatch|

SDK checks were repeated on26.0.2, not merely reused from26.0.0.
Nested creative id/name/thumbnail_url all declared by AdCreative.
Explicit parameters: time_range JSON map, time_increment1 serialized as string,
level=ad, action_attribution_windows JSON list[7d_click,1d_view],
action_report_time=impression, use_unified_attribution_setting=false.
Generated Insights parameter types and enums were checked with AST assertions.
A locally constructed example.invalid request verified serialization without
sending any HTTP. No batch, async Insights job, roster discovery or per-AD fan-out.

Response assumptions remain fail-closed: dict/list/schema checks, pagination
origin/path/cursor checks, duplicate/account binding validation, bounded pages
and rows. Runtime empty/partial/unsupported responses can stop the pilot safely;
static schemas cannot guarantee successful reporting for the stored app/account.

## Known v26 changes and impact

Official v26 SDK release notes describe removal of Commerce Order Management
endpoints and Instagram Explore placement, Messenger Stories placement behavior
and WhatsApp Status capabilities. This pilot uses no commerce route and performs
no placement creation/editing. None of those listed changes removes its selected
GET definitions or requested fields in SDK26.0.2.

Complete runtime semantics and future all-version changes are not certified.
No statement that v26.0 is the latest Graph API or universally usable is made.
No API version was changed; no fallback/downshift was invented.

## Existing session / local runtime

Fresh READ ONLY PostgreSQL verification at2026-10-13T18:42:18Z:
- Exactly one existing PREPARED session; UUID/account/day match the user's scope.
- Chosen completed day2026-10-12, America/Los_Angeles.
- Credential fencing revision3 equals current connection revision3.
- Versionv26.0 matches stored encrypted credential/config.
- Cap20, used0, timeout600; job_id/deadlineNULL (start has not occurred).
- Encrypted credential present/decryptable; configured app ID matches envelope.
- Meta connection disabled/disconnected. No queued/running Meta jobs.
- Local Meta quota0/5000, no blocked_until or app cooldown.
- Minimum interval10s; production app concurrency1 retained.
- Actual scheduler controlled mode=true, no Meta beat entries.
- MetricFlow READ enabled/healthy, revision1, last successful sync18:40:04Z.
- Stored MetricFlow WRITE revision1, untouched.
- ACTIONS_ENABLED=false, LOCAL_READ_ONLY=true, AI_ENABLED=false,
  AI_AUTOPILOT_ALLOWED=false, META_CONTROLLED_READ_PILOT=true.
- META_PILOT_AUTHORIZED_SESSION_ID and META_PILOT_CONFIRMED_GRAPH_VERSION empty.
- Meta attempt meter0; advertising executions0.

Account identity and exact session UUID are in the user-facing final card and
ignored .tools/meta-pilot-final-authorization-review.json; real advertising
account identifiers/names are not committed to Git. No new session was created.
The conversation contains account selection and preparation/review requests,
not separate consent to launch this session.

## Future execution after separate explicit permission only

1. Present the exact existing UUID/account/day,20-attempt cap,600s timeout,
   unknown token/asset/tier risks and this narrow contract evidence to the user.
   Obtain explicit consent for that session; readiness itself is not consent.
2. Revalidate unchanged PREPARED scope/revision,0 attempts, queue, quota/cooldown,
   safe flags and controlled mode. Any drift requires renewed review.
3. Only after consent, the server operator configures the existing exact UUID
   in META_PILOT_AUTHORIZED_SESSION_ID and v26.0 in
   META_PILOT_CONFIRMED_GRAPH_VERSION for backend and READ worker, using the
   existing deployment procedure. Do not set these variables during this audit.
   Recreate only the required services; do not enable Meta connection/scheduler.
   In the existing local deployment, edit only the two approval entries in the
   local .env after consent, then recreate backend/worker with this future command
   (NOT executed by this audit):
   ```powershell
   Set-Location 'E:\Creative_Factory\metric-control-center'
   $pilotDocker = Join-Path $env:LOCALAPPDATA 'Programs/DockerDesktop/resources/bin/docker.exe'
   & $pilotDocker compose --env-file .env -f docker-compose.yml -p metric-control-center --profile web up -d --no-deps backend worker
   ```
4. Logged-in ADMIN obtains local CSRF token and invokes exactly once:
   POST /api/admin/providers/meta/pilot/{existing-session-uuid}/start
   This is the local application route, not an advertising/provider WRITE.
   Do not invoke generic Meta check/sync, create another session or call the
   Graph API directly. Existing ProviderJob dispatcher performs the approved run.
5. The maximum physical request sequence, with versioned GET paths:
   debug_token; me/permissions; act_SELECTED_ID; act_SELECTED_ID/campaigns;
   act_SELECTED_ID/adsets; act_SELECTED_ID/ads; act_SELECTED_ID/adcreatives;
   act_SELECTED_ID/insights. Minimum8 when all edges fit one page and no retry.
   All pages/retries/timeouts share the same immutable20-attempt budget.
6. Before catalog/Insights, token validity/app binding/ads_read and chosen account
   binding/status must pass. Failure stops; never replace credentials or expand
   scope to make the test succeed.

## Observation, rate limits and termination

Use Settings > Connections > Meta API > controlled READ pilot and existing
request journal, filtered by source pilot:SESSION_UUID. Refresh via local GET:
GET /api/admin/providers/meta/pilot
GET /api/admin/providers/meta/usage
GET /api/admin/providers/meta/requests
These are local diagnostics, not extra provider GETs. Avoid rapid refresh floods.

Observe used/cap, status/reason, attempt/page/retry, endpoint, response status,
latency, error code, sanitized headers and cooldown. Headers retained include
x-app-usage, x-ad-account-usage, x-business-use-case-usage and
x-fb-ads-insights-throttle. Access Tier is unknown unless actually reported;
header utilization is not remaining request quota. Local cap5000 is not a
confirmed provider entitlement.

Existing controller sets cooldown on429/provider rate codes and high utilization
(max reported utilization85% or higher). Retry-after is honored conservatively;
unknown regain-access units are not treated as invented resume times.
One request per app, interval>=10s; Insights local pacing weight2 remains.
Transient failures have at most2 retries; token/permission/rate errors do not
auto-retry. Error/cooldown prevents subsequent eligible HTTP attempts.

Stop on cap20,600s durable deadline,429/cooldown, permission/token invalid or
expired, binding/schema/critical response failure, queue timeout/saturation,
cancellation, credential/config drift, revoked grant or worker-owner loss.
An HTTP attempt already in flight has the existing bounded35s timeout; no new
attempt starts after deadline/cancellation. No guarantee that delivered GET can
be recalled. If the complete result needs more than20, stop and explain; no
automatic increase, continuation, backfill or session restart.

For manual cancellation as ADMIN with CSRF:
POST /api/admin/providers/meta/pilot/{existing-session-uuid}/cancel

After terminal SUCCEEDED/STOPPED/CANCELLED:
- Verify final attempts match the durable journal; inspect cooldown and reason.
- Export safe evidence/counts/errors. Pilot validates mappings but publishes no
  replacement advertising facts and performs no advertising mutations.
- Remove the session authorization grant via the established deployment procedure;
  keep both grant/confirmation empty when returning to preparation-only posture.
- Verify Meta disabled, scheduler held, four flags unchanged, MetricFlow healthy.
- Do not auto-restart or enable standard Meta sync. New run/scope needs new consent.

## Remaining uncertainties (bounded pilot acceptance risks)

Actual token type/validity, app-review/ads_read, selected-account permission/status,
catalogue size, reporting availability, response latency, Access Tier and actual
throttling remain unverified until the separately authorized pilot.
SDK field presence does not guarantee entitlement, all field combinations or
equality with Ads Manager/MetricFlow attribution. Those risks are bounded by
early validation, fail-closed errors, no publication and request/time budgets.

No technically critical static incompatibility or missing local safety gate was
found for this narrowly scoped diagnostic READ. Execution is still intentionally
blocked by empty server-side gates and absence of explicit user consent.

## Audit artifacts

Ignored .tools/meta-pilot-final-sdk-fields.json retains26.0.2 field/method/enum
and serialization assertions; .tools/meta-final-sdk26 contains public SDK source.
.tools/meta-pilot-final-authorization-review.json retains fresh local checks.
No application code or runtime state was modified. No full test suite rerun was
needed for this audit-only documentation change; static assertions passed.
This report supersedes the earlier broad-documentation blocker only for the
explicit existing controlled READ pilot, not for general Meta or WRITE readiness.
