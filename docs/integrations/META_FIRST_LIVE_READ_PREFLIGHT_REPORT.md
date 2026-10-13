# META FIRST LIVE READ PREFLIGHT REPORT

As of 2026-10-13, UTC. Scope: local inspection and public documentation only.

META LIVE READ PREFLIGHT: BLOCKED
META LIVE READ EXECUTED: NO
ADVERTISING WRITE REQUESTS: 0

## Official documentation and version evidence

Configured version v26.0 was NOT changed. Version confirmation and session
authorization environment variables remain empty.

Meta's official Business SDK configuration explicitly uses API_VERSION=v26.0:
https://raw.githubusercontent.com/facebook/facebook-python-business-sdk/26.0.2/facebook_business/apiconfig.py

The official repository latest release resolves to SDK26.0.2:
https://github.com/facebook/facebook-python-business-sdk/releases/tag/26.0.2
The initial SDK26 release references Graph API26 and lists known changes:
https://github.com/facebook/facebook-python-business-sdk/releases/tag/26.0.0

This is first-party SDK evidence for existence/support in SDK26.0.2. It is not
a complete confirmation of the Graph API lifecycle/latest-version schedule or
every runtime entitlement for the stored app/token.

The following Meta Developers pages were attempted but unavailable/429:
https://developers.facebook.com/docs/graph-api/changelog/version26.0/
https://developers.facebook.com/docs/graph-api/changelog/versions/
https://developers.facebook.com/docs/marketing-api/changelog/
https://developers.facebook.com/docs/marketing-api/reference/ads-insights/
https://developers.facebook.com/docs/marketing-api/reference/ad-creative/

Context7 retrieved official reference snippets for versioned Marketing paths,
campaigns/adsets/ads and Insights. Those examples primarily reference v25.0;
they must not be represented as explicit v26.0 lifecycle confirmation:
https://developers.facebook.com/docs/marketing-api/overview/versioning
https://developers.facebook.com/docs/marketing-api/reference/ad-account/campaigns
https://developers.facebook.com/docs/marketing-api/reference/ad-account/adsets
https://developers.facebook.com/docs/marketing-api/reference/ad-account/insights

## Static Connector contract audit

Compared existing requested fields to official generated SDK26.0.0 Field enums:
- Account6 fields: no missing names.
- Campaign9 fields: no missing names.
- Adset12 fields: no missing names.
- Ad9 top-level fields: no missing names.
- Creative5 fields: no missing names.
- Insights23 fields: no missing names.
Nested creative expansion uses id/name/thumbnail_url, all present in AdCreative.
This checks field existence, not guaranteed combinations/permission/availability.

SDK26.0.2 AdAccount declares GET account, campaigns, adsets, ads, adcreatives
and synchronous insights. Its Insights parameter schema includes time_range(map),
time_increment(string), action_attribution_windows(list), action_report_time(enum),
level(enum), use_unified_attribution_setting(bool). Existing URL serialization
uses explicit date range, daily increment1, ad level, 7d_click/1d_view,
impression report time and false unified attribution. No contract was rewritten.

Sources:
https://raw.githubusercontent.com/facebook/facebook-python-business-sdk/26.0.0/facebook_business/adobjects/campaign.py
https://raw.githubusercontent.com/facebook/facebook-python-business-sdk/26.0.0/facebook_business/adobjects/adset.py
https://raw.githubusercontent.com/facebook/facebook-python-business-sdk/26.0.0/facebook_business/adobjects/ad.py
https://raw.githubusercontent.com/facebook/facebook-python-business-sdk/26.0.0/facebook_business/adobjects/adcreative.py
https://raw.githubusercontent.com/facebook/facebook-python-business-sdk/26.0.0/facebook_business/adobjects/adsinsights.py
https://raw.githubusercontent.com/facebook/facebook-python-business-sdk/26.0.2/facebook_business/adobjects/adaccount.py

SDK26 release notes report Commerce Order Management endpoint removal and
placement changes (Instagram Explore/Messenger Stories/WhatsApp Status).
The pilot does not use those removed commerce endpoints or placement WRITE.
No specific failure of this pilot was established from these notes; that does
not certify absence of all breaking changes in inaccessible developer changelogs.
Token verifier debug_token/me/permissions is existing code, not LIVE verified here.

## Local connection and safety

PostgreSQL head0015_meta_pilot.
Stored Meta envelope present and decryptable. Configured app ID is present
and matches encrypted credentials; actual app ID is only in the local evidence.
Graph version matches both config and encrypted credentials: v26.0.
ProviderConnection fencing revision3; ProviderCredential has updated_at but no
separate revision column. Envelope updated2026-10-09T08:07:31Z.
Meta disabled/disconnected; last recorded check2026-10-09T08:31:55Z.
Current token validity, ads_read/app review and selected-object permissions UNKNOWN.

ACTIONS_ENABLED=false; LOCAL_READ_ONLY=true; AI_ENABLED=false;
AI_AUTOPILOT_ALLOWED=false; META_CONTROLLED_READ_PILOT=true.
META_PILOT_AUTHORIZED_SESSION_ID empty.
META_PILOT_CONFIRMED_GRAPH_VERSION empty.
No standard Meta beat entries; no active queued/running Meta jobs; no pilot sessions.
Meter records in working workspace:0. Advertising executions:0.
Meta quota on UTC2026-10-13:0/5000; blocked_until absent; cooldown absent.
Pacing minimum10 seconds, concurrency1 remain in the existing controller.
5000 is a local cap, not a confirmed Meta entitlement or Access Tier.

MetricFlow READ enabled/healthy, revision1, last successful existing sync
2026-10-13T15:50:01Z. Stored WRITE revision1; not accessed or checked.
Routing remains MetricFlow primary, no fallback, actions disabled.
No MetricFlow configuration, credentials, tasks or connections were changed.

## Accounts and mapping

Eight unique Meta IDs in local PostgreSQL (12 source account rows).
All eight have Meta catalogue records observed2026-10-09.
Four additionally have fresh MetricFlow imports2026-10-13.
Mapping proof is catalog_meta_id, with no recorded explicit user confirmation.
This is source-ID evidence, not proof of current stored-token asset permission.
One account has catalogue only and no completed Meta statistics import.

The complete user-requested names/IDs/import dates are displayed in the chat and
retained in ignored .tools/meta-first-read-preflight-local.json. They are not
committed to Git as real advertising-account data. No account has been selected.
A user-input request is pending; no account is chosen by the agent.

## Planned session (NOT CREATED)

Session ID: NONE / WAITING_FOR_USER_ACCOUNT_CHOICE.
One chosen account, one completed calendar day2026-10-12 in its stored timezone.
Hard cap20 physical attempts, concurrency1, minimum interval10s, timeout600s.
Only the existing controlled pilot mechanism will be used. No backfill.
Preparation will keep Meta disabled and is not permission to start.

Minimum future HTTP:8 GET, assuming single pages and no retries:
1. /v26.0/debug_token (existing app-auth verifier)
2. /v26.0/me/permissions
3. /v26.0/act_SELECTED_ID
4. /v26.0/act_SELECTED_ID/campaigns
5. /v26.0/act_SELECTED_ID/adsets
6. /v26.0/act_SELECTED_ID/ads
7. /v26.0/act_SELECTED_ID/adcreatives
8. /v26.0/act_SELECTED_ID/insights

Every page/retry shares the20-attempt session cap. Usage headers are observed
on these responses; they add no requests. The configured fields and attributes
remain those of MetaMarketingProvider. Actual catalogue size/pagination unknown.

Stop on cap, deadline,429/cooldown, permission/token invalid or expired,
binding mismatch, critical response/schema error, HTTP queue timeout, cancellation,
credential/config revision change, revoked grant or lost worker owner.
No quota expansion, standard scheduler activation, auto backfill or WRITE.

## Missing conditions

1. User selects exactly one local account before a session can be prepared.
2. Complete/review official Meta Developers v26.0 lifecycle and breaking-change
   evidence, including any limits on the requested field/attribution combinations.
   SDK evidence is useful but its scope is explicitly narrower.
3. Review entitlement/token type/app review and ads_read/object-access evidence.
   Actual token/permissions verification is deferred to the separately authorized
   bounded pilot; no GET is made to establish them in this task.
4. After account selection create a PREPARED session with the existing service,
   report its immutable UUID/date/scope/revision/budget, and recheck queue/quota.
5. Obtain separate explicit LIVE permission for that exact session. Only then
   may a server operator configure its authorization UUID and reviewed version.
   This report is not authorization; neither gate has been populated.

This phase is read-only audit: no application code, API version, database state
or runtime configuration was changed. Backend/Playwright were not rerun because
no implementation was modified. Prior597/9 test results remain prior-phase evidence.
Local evidence: ignored .tools/meta-first-read-preflight-local.json and
.tools/meta-first-read-sdk-contract.json; public SDK source copies under
.tools/meta-v26-sdk. No secrets or credential material are included in this report.
