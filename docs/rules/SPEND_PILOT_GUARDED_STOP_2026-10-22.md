# Spend pilot: guarded stop and unresolved group review - 2026-10-22

## Authorized operation did not reach the provider

User explicitly permitted one experimental PAUSE_AD for AD 120247730105960571,
request e8804322-74a9-4ef9-9589-22974e3aefdb, accepting the unverified WRITE ID.
Authorization receipt recorded at 21:13:41 MSK; baseline deadline 21:14:44.545293.

The one-off process used ACTIONS_ENABLED=true / LOCAL_READ_ONLY=false only in
that process, following the existing scoped-pilot procedure. Global .env and
backend/Credential Manager service flags stayed closed. Its limited transport
allowed only the 3 exact catalog GET paths and 1 exact AD pause POST with
{level: ad}; no retries. Local preflight/confirmation succeeded at 21:14:15,
but the server permit preparation raised ActionRejected before HTTP.

Physical GET attempts: 0. Physical POST attempts: 0. ActionExecution count stayed
3 historical. No new controlled permit, claim, wire spend or execution row was
created. The process exited; both services were checked with WRITE_DISABLED and
all four original safety flags. The original exception logger omitted the
ActionRejected message; the failing guard was diagnosed from persisted state
and its exact admission predicate, not from a logged error code.

The old group request 39836b5b-296f-4896-917c-3ae2b48eb536 is still unknown,
ENABLE_ADSET for group 120247730105950571 in act_1047962734516123, revision 10.
Its mode LIVE_SINGLE_OPERATION and unknown status trigger PILOT_WORKSPACE_CONFLICT
in durable admission. The new request's local preflight had no blocking reasons.
The preceding read-only contract review had failed to check this workspace gate;
therefore the earlier ready-for-authorization card was incomplete. This is fixed
below. No force, timestamp extension or post-expiry retry was performed.

The unspent request was subsequently closed through the normal manual transition:
EXPIRED, revision 10. It has no controlled authorization and no ActionExecution.
The old group UNKNOWN record was left untouched.

## Corrections

- require_workspace_available is shared by durable LIVE admission and read-only
  contract review. Experimental spend preparation also checks it before GETs.
- Other in-flight/unknown and confirmed LIVE permits block the workspace; own
  request and isolated MOCK_ONLY records retain their existing treatment.
- Cancelled/expired rule drafts can be prepared anew only if they have no prior
  authorization and no ActionExecution. Old history remains intact. Spent or
  authorized requests are not exempted; the once-only spend policy remains.
- No workspace guard was weakened or removed. No provider HTTP contract changed.

## Concrete administrative review proposal, not yet applied

The old group POST started on 2026-10-21 at 18:30:44 MSK and returned HTTP 200
(completed at 18:30:46). Manual
confirmation of its ACTIVE switch was recorded at 18:48:35, after its 18:40:04
window. API execution outcome is live_unknown, error_code null; attempts=1,
wire_spent=true, http_started=true, SYNC_200, no job. A controlled_live_acknowledged
log and matching late manual readback remain stored. This is late observation,
not authoritative API verification or pause ownership. The later 21:00 group-OFF
attestation is a separate current state, not proof of historical causality.

New private local helper review_spent_adset_enable previews the review with no
mutation. Applying it requires the exact separate acknowledgment:
ACKNOWLEDGE_SPENT_ADSET_ENABLE_UNKNOWN_NO_RESEND.
It validates admin/owner/workspace, revision, same group/account/hierarchy/routing,
expired SYNC_200 single spent attempt, completed UNKNOWN execution, original ACK,
matching actor/entity/account late manual ACTIVE observation, and absence of any
pending job. Transport timeouts, unspent commands, open windows, missing/mismatched
manual evidence, wrong operation/revision/statement are held.

If the user approves only this administrative step:
- request 39836b5b-296f-4896-917c-3ae2b48eb536 becomes MANUALLY_REVIEWED;
- its execution remains live_unknown, with error/attempt/wire/audit preserved;
- one audit record and an explicit local-review marker are added, idempotently;
- no provider call, resend, advertising data change or pause ownership is created.

This is local acknowledgment of an unresolved historical outcome, not a success
claim. The workspace gate subsequently stops treating that request as active.
Every new advertising command still requires fresh scoped evidence and its own
explicit authorization. The expired e880... card is not reusable and no new
PAUSE is launched by this review. Applying the review is awaiting user agreement.

## Validation

Six targeted readiness/renewal regressions PASS. Nine administrative-review
regressions PASS, including preview with no mutation, explicit acknowledgment,
idempotency and preserved UNKNOWN. Restricted-role isolated PostgreSQL checks
PASS for special and strict rule modes, cancelled-draft renewal and the review
with UNKNOWN execution preserved. All temporary schemas/roles rolled back;
provider_requests=0 in tests. No production archival was applied by these tests.

Other changed modules pass Ruff. The legacy ActionEngine has five pre-existing
Ruff findings (2 I001, 2 FURB157, 1 BLE001); a HEAD-versus-change comparison confirms
zero new findings. No lint suppression or unrelated module reformat was added.
Full related regressions, rollout and production preview are recorded below.
Evidence ignored under .tools/pilot-readiness-fix-20261022/ and the authorization
trace under .tools/reported-spend-20261022-2100/.


## Completed rollout and production preview

Related regression: 308 PASS in 408.54 seconds. The six targeted checks and nine
administrative checks overlap this regression; counts are not summed as unique.
All three candidate PostgreSQL harness runs PASS. Build/format/secret checks PASS;
legacy-engine lint baseline remains unchanged as described above.

Deployed backend and Credential Manager image:
metric-control-center-pilot-readiness-20261022:prepared. Fourteen protected table
counts/digests unchanged across rollout, other five service identities unchanged,
environment hash unchanged. No new grants, migration or volume deletion. A fresh
backup was created. Advertising execution count remains 3 historical.

Production preview actually ran under mcc_credential_manager, without an
acknowledgment: request 39836b5b-296f-4896-917c-3ae2b48eb536 revision 10,
ENABLE_ADSET / act_1047962734516123 / 120247730105950571, current unknown,
proposed MANUALLY_REVIEWED, execution_outcome_preserved=live_unknown,
creates_pause_ownership=false, provider_requests=0, applied=false.
The new read-only contract review returned PILOT_WORKSPACE_CONFLICT before the
expired e880... card could be mistaken for a ready LIVE request.

No administrative review was applied in production. No additional provider READ
or advertising WRITE was performed after the guarded attempt. Global flags remain
ACTIONS_ENABLED=false, LOCAL_READ_ONLY=true, AI_ENABLED=false,
AI_AUTOPILOT_ALLOWED=false. The user's current PAUSE permission did not authorize
closing a different historical request; that local acknowledgment is the next
explicit decision. After it, prepare fresh evidence/a new exact advertising card;
do not execute the expired card or restore its timestamps.

FINAL STATUS: ADVERTISING PAUSE NOT SENT (0 GET / 0 POST IN AUTHORIZED RUN);
READINESS BUG FIXED AND DEPLOYED; OLD GROUP OUTCOME STILL UNKNOWN;
LOCAL UNKNOWN REVIEW READY, AWAITING USER ACKNOWLEDGMENT.
