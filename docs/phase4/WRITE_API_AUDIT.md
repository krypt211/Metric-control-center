# MetricFlow WRITE API audit — 2026-10-10

This is a documentary audit, not a WRITE capability test. No modifying HTTP
request was sent. Existing READ credentials were not used for WRITE.

Source: [official MetricFlow documentation](https://metricflowit.click/docs).
Context7 did not return a matching MetricFlow library; unrelated libraries were
discarded. Local reader, writer, transport, provider registry, saved mappings
and Action Engine were inspected. A route name or an existing connector method
does not establish a complete, usable operation contract.

| Operation | Endpoint / method | Request and response | Authentication / permission | Identity and verification | Status |
| --- | --- | --- | --- | --- | --- |
| PAUSE_AD | `POST /api/v1/entities/{entity_id}/pause` listed | Exact body and response schema unconfirmed; local no-body call is an assumption | Bearer, `campaigns:write`; separate WRITE credential; actual permission unverified | Numeric provider AD ID; compare account and parents; future fresh READ readback | UNVERIFIED |
| ENABLE_AD | `POST /api/v1/entities/{entity_id}/enable` listed | Exact body and response schema unconfirmed | Same as pause | Same AD; configured ACTIVE does not prove delivery if parents are paused | UNVERIFIED |
| GET_AD_STATUS | `GET /api/v1/ad-accounts/{ad_account_id}/ads` | Existing READ catalog mapping accepts provider AD ID and observed status; date parameters used by local connector | Bearer, `campaigns:read`; existing READ credential | `act_<numeric_id>` account plus numeric AD; hierarchy from catalog. No separately confirmed single-AD status endpoint | Existing READ supported; operation-specific fresh LIVE verification not accepted yet |
| SET_CAMPAIGN_BUDGET | `POST /api/v1/entities/{entity_id}/budget` listed | Budget field names, units, daily/lifetime semantics and response unconfirmed | Bearer, `campaigns:write`; permission unverified | Numeric campaign ID and confirmed account; future READ readback | UNVERIFIED |
| SET_ADSET_BUDGET | Same generic budget route | Same schema gaps; campaign budget ownership must be established | Same as campaign budget | Numeric adset ID plus parents; future READ readback | UNVERIFIED |
| SET_BID | No confirmed public endpoint | No confirmed request or response | No confirmed operation-specific permission | Bid strategy and entity contract absent | UNVERIFIED, never inferred from MetricFlow UI |

General API errors documented include 401/402/403/429. Exact operation error
bodies, whether an error can follow a partial change, operation rate limits,
idempotency header semantics, dedicated operation-result endpoint and
eventual-consistency deadlines remain unconfirmed. They must be obtained from
the provider; sending WRITE to discover them is prohibited.

Local READ budget remains **800 requests/day**. The normal scheduled worker
continues READ; acceptance uses local DB/API, mocks and restored PostgreSQL.
No WRITE quota or permissions are inferred from the READ connection's quota.

## Required contract evidence before Phase 4B

Obtain provider-authored examples or schema covering one chosen operation:
exact request, response, errors, IDs, permission validation, retry/idempotency,
timeouts, rate limits and readback. Record source/version/date. Test the adapter
against those examples with MockTransport. Only then may its capability become
contract-verified; credential and object permission remain separate gates.

## Meta alternative

Context7 official Marketing API documentation confirms AD status mutation using
`POST /{version}/{ad_id}` and `status=PAUSED|ACTIVE`, with an access token and a
success boolean example. [Official status documentation](https://developers.facebook.com/docs/marketing-api/best-practices/manage-your-ad-object-status).
This does not confirm access or version support for this workspace. Meta remains
disconnected. Verify the configured API version, `ads_management`, asset access,
parent states and fresh readback before a separate Meta implementation/test.
No automatic WRITE failover is allowed.

**METRICFLOW WRITE API: UNVERIFIED**
