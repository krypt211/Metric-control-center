# One rule-bound MetricFlow PAUSE pilot — 2026-10-22

## Implemented scope

The existing private single-use pilot now admits one PAUSE_AD proposal carrying
rule_source, instead of rejecting every rule source. It uses the same encrypted
WRITE credential handoff, three pre-POST catalog GETs, durable claim, transport,
HTTP contract and manual readback. No second dispatcher, scheduler, retry loop,
Meta connection, new database schema or public WRITE proxy was added.

ExperimentalPrepareInput accepts optional simulation_id only for PAUSE_AD.
The existing manual preparation recomputes the rule decision and attaches its
normal rule_source. Trusted experimental evidence additionally pins the entire
source SHA256 and automation-control generation. This covers simulation UUID,
rule UUID/revision, operation, decision key, provider and credential metadata.
The existing evidence fingerprint binds this addition to the provider contract.
An unbound rule source, removed source, wrong operation or changed source is held.

Rule/source is checked at authorization, execution and existing wire boundaries:
current same-version rule, same entity/simulation, matching positive decision key,
TRUE / WOULD_PAUSE, eligible future-action evidence, manual blocks and peer-rule
conflicts, emergency stop and unchanged generation. REVIEW, KEEP, unknown
attribution and other incomplete required evidence do not become PAUSE proposals.
This stage does not relax financial evidence policy or certify missing attribution.

Distinct authorization statement:
AUTHORIZE_ONE_EXPERIMENTAL_RULE_PAUSE_WITH_UNVERIFIED_ID.
A prior manual PAUSE statement is rejected for a rule-bound request. This statement
is a required protocol value, not authorization supplied by this report or by a
user request to develop software. WRITE ID namespace remains explicitly unverified.

## Own request and read-only revalidation

After a durable claim, the same request is executing. Revalidation now excludes
only that request from unresolved-action detection, after verifying its workspace,
entity, operation and simulation binding. Other commands still block; the existing
unique active-action constraint remains intact. Peers see the same validated
exclusion, so a rule cannot conflict solely with its own already claimed command.
This exclusion is internal and is not a client-supplied switch or rule setting.

Revalidation calls economics_adapter with persist_snapshot=false. It recomputes
financial values without inserting economic evaluation history. Ordinary DRY_RUN
simulations retain their existing snapshot persistence. Credential Manager needs
SELECT on 15 additional rule/financial evidence tables; these are explicitly
listed as RULE_READ_TABLES. No INSERT/UPDATE/DELETE to those tables is granted.
The existing provisioner grants the read set idempotently; financial writes and
provider_credentials access remain denied.

## Operator procedure

Use the existing private /controlled-pilot-experimental/prepare with the target
local entity_id, a genuinely positive simulation_id, current credential_revision,
management_confirmed=true and PREPARE_EXPERIMENT_ONLY_NO_POST. It only prepares and
performs bounded READs. The returned card exposes rule_source and the distinct
statement. Do not first create a competing manual draft for the same AD.

Review the exact request/rule/simulation revisions, entity hierarchy and baseline;
perform local preflight and confirmation. Only after separate explicit permission
for that exact proposal may an operator authorize the existing
/controlled-pilot/{request_id}/authorize and execute endpoint in a one-off scoped
process. Global flags stay closed. Maximum 1 POST, 3 execution revalidation GETs,
600-second permit (possibly shorter), original transport timeout, no resend.
HTTP 200 remains acknowledgement requiring manual readback, not automatic success
or Rule Engine pause ownership. Timeout/ambiguous ACK remain unknown without retry.
No new UI button or general automatic execution mode is included in this stage.

## Current project boundary

The existing Creo 03 rule v2 and its KEEP result are not modified. It must not
produce a PAUSE while CPL is below its threshold. No artificial fact, attribution
value, eligibility flag or production test threshold was inserted. A positive
local mock signal used here is not a positive production signal. No live pilot
request or authorization was created. The earlier three physical advertising
POSTs keep their original identities and outcomes; their permissions are consumed.

Source changes: actions/rule_pilot, experimental, pilot, pilot_contract, manual;
automation/smart_simulation; credential_permissions. No dependency updates.
Candidate/restore evidence is ignored under .tools/rule-pilot-20261022/.

## Validation and local rollout completed

- Targeted backend regression: 319 passed in 404.90 seconds.
- Final read-only revalidation/peer-rule checks: 31 passed in 39.13 seconds
  (overlap with the regression suite; these are not 350 unique tests).
- New rule-pilot suite: 11 passed. Coverage includes distinct authorization,
  changed evidence, emergency-stop generation, own-claim revalidation,
  duplicate preparation, timeout and no resend.
- Candidate image PostgreSQL checks: PASS on an isolated restored database,
  including restricted-role actual read-only economics and peer evaluation,
  one mock rule POST, and denied financial/credential writes. Both temporary
  test schemas/roles rolled back. No provider HTTP was sent by these checks.
- Backup restored successfully: 70 tables, 13,010,634 bytes. No production
  migration, volume deletion or data restoration was performed.
- Docker Engine was initially stopped. After starting Docker Desktop,
  PostgreSQL completed its startup recovery. An early rollout attempt stopped
  before grants while PostgreSQL rejected connections; its defensive rollback
  retained the previous backend/credential-manager image. Final rollout PASS.
- Deployed image: metric-control-center-rule-pilot-20261022:prepared.
  Backend and Credential Manager readiness checks passed; loaded action source
  hashes match the tested source. The other five service identities/images
  are unchanged. Fourteen protected production table counts/digests match the
  pre-deployment snapshot exactly. Environment-file SHA256 is unchanged.
- Added SELECT only for the 15 evidence tables; INSERT/UPDATE/DELETE remain
  denied. Runtime role is metric_control in backend and mcc_credential_manager
  in Credential Manager.
- Both services retain ACTIONS_ENABLED=false, LOCAL_READ_ONLY=true,
  AI_ENABLED=false, AI_AUTOPILOT_ALLOWED=false. Global WRITE gate reports
  WRITE_DISABLED and live capability BLOCKED. Meta remains disabled/disconnected.
- MetricFlow READ local status is healthy, revision 1; last recorded successful
  READ is 2026-10-22T03:00:01.546996+00:00. No extra provider probe was made.
  Separate encrypted WRITE credential remains configured at revision 1.
- Physical advertising executions remain 3 historical operations. New live
  advertising requests in this development/rollout stage: 0.
- Frontend did not change; no new browser acceptance run was needed or claimed.

## Exact remaining LIVE boundary

Implementation status: DEPLOYED / LOCAL AND MOCK VALIDATED.
Rule LIVE execution status: NOT AUTHORIZED / NOT EXECUTED.

The current saved Creo 03 simulation is KEEP, not a positive PAUSE signal.
Its source attribution/action eligibility is also unconfirmed; this adapter
still emits action_eligibility=false. This stage adds the execution admission
but does not supply the missing production financial-evidence contract. Positive
mock fixtures therefore do not prove a currently eligible production candidate.
The existing pilot also requires both parents to be PAUSED; the last manual
confirmation had the group enabled and campaign disabled. That prior observation
is not a current baseline and must be revalidated before preparing any LIVE card.
WRITE ID namespace remains explicitly experimental.

Next controlled step requires a genuine positive eligible rule decision under
an agreed test rule, current eligible parent/status evidence, then a new exact
request authorization. Do not change thresholds, fabricate attribution or reuse
any of the three consumed manual authorizations to manufacture readiness.
