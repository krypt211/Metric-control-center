# Phase 4B — controlled single-action plan

**PHASE 4B LIVE TEST: BLOCKED. LIVE AD WRITES: NOT AUTHORIZED.**

This plan is reviewable preparation only. Do not start the existing action
service, enable global flags, connect Meta or send WRITE while following it.
The manual-control API has no execution endpoint. Local confirmation authorizes
only local simulation; it is not an advertising permission.

## Existing infrastructure and remaining implementation

Available: independent READ routing, immutable captured identity and revisions,
local preflight, actor/workspace authorization, separate operator grant,
idempotency, row locks, pending uniqueness, confirmation, expiry and append-only
audit. The legacy engine has durable attempts and unknown-outcome READ
reconciliation without resending. Both engine and HTTP transport enforce the
environment safety gate. The action router is disabled; provider placeholder
classes do not implement LIVE execution.

Still required AFTER contract verification: verified provider adapter, separate
WRITE credential revision/permission metadata, durable single-use authorization,
atomic consumption with request/attempt creation, operation-specific rate cap,
configured/effective readback and a controlled execution entry point. None of
these permissions is inferred from a READ connection or a Phase 4A confirmation.
Keep this infrastructure disabled until a separate user-authorized task.

## 1. Contract and credential prerequisites

Resolve every relevant gap in [WRITE API audit](WRITE_API_AUDIT.md). Obtain a
separate minimal-scope `campaigns:write` credential from MetricFlow. Never send
it in chat, put it in Git, logs or frontend. The existing Compose secret path is
`.secrets/metricflow_write_key`, mounted only into the isolated action service as
`/run/secrets/metricflow_write_key` via `METRICFLOW_WRITE_KEY_FILE`. The folder is
ignored by Git. Keep the service off; creating a file grants no LIVE capability.
Windows file permissions must restrict access to the service owner.

READ credentials and encrypted connection settings remain independent.
Record a separate WRITE revision and verified asset permissions without exposing
the token. A new token invalidates earlier approvals. Do not reuse the READ
revision as proof of WRITE permission.

## 2. Explicitly choose one object and one operation

Later select exactly one numeric Meta AD ID, its `act_<id>` account and
campaign/adset parents. Separately confirm the WRITE endpoint's entity-ID
namespace and its mapping to that same AD; do not assume its path accepts the
READ ID just because the local stub does. Show name, workspace, provider,
original configured status, effective
status and timestamp. Obtain fresh READ before preview and again immediately
before execution; reserve necessary GET quota instead of exceeding its cap.
Reject missing identity, stale facts, paused-parent ambiguity, pending/unknown
operations, mismatched status, changed routing/credentials or already-target
state. No concrete production AD or command is selected by this document.

## 3. One-time authorization

Persist an immutable approval bound to actor/workspace, provider, account/AD,
operation, original/target state, full preflight hash, contract version, WRITE
credential revision and routing revision. Give it a short expiry and exactly
one attempt. Show these facts and ask the user explicitly to authorize that
single advertising change. No bulk action, budgets, bids, rules, AI or failover.

Lock authorization and entity; atomically verify and consume the approval while
creating one durable attempt. Replays return the existing request result.
Consumption is not reversed after network timeout or process crash. Same-key
different-command input is a conflict. Unresolved earlier outcome blocks further
commands for that AD. Verify this concurrency behavior in isolated PostgreSQL.

## 4. Controlled dispatch and readback

Run a dedicated process bound to that permit, with a hard maximum of **one
advertising WRITE HTTP attempt**. Any later authorized execution flags must be
scoped to that process; keep the workspace `.env`, backend and READ workers
disabled for advertising WRITE. Never activate the general legacy action queue
to conduct a one-object test. No retries at transport, worker, proxy or
provider routing layers. Recheck the safety gate and all bindings immediately
before HTTP; toggling global flags alone must never authorize an object.
Persist attempt start before dispatch. Store sanitized request/result, IDs,
revisions, preflight, actor, timestamps and correlation in audit.

After a response, use independent READ of the same provider/object to verify
configured and effective state plus parent identity. HTTP success alone never
means SUCCEEDED. Use bounded reads within a documented consistency window and
quota. Definitive provider rejection becomes FAILED only if the contract makes
its meaning unambiguous.

## 5. Unknown outcome and restoration

Timeout, connection loss, unrecognized response, worker crash after dispatch or
missing trustworthy readback => OUTCOME_UNKNOWN / RECONCILIATION_REQUIRED.
Never issue a second WRITE automatically. Continue bounded READ reconciliation;
escalate to manual inspection if unresolved. A state coincidence alone is not
proof of attribution where other operators may have changed the object.

Capture the original status beforehand. Restoration is a **separate** action
with new current READ, new preflight, new one-time approval and new attempt;
the first authorization must not include a hidden second WRITE. If the initial
outcome is unknown, resolve it before proposing restoration. Stop all dispatch
after the one permitted attempt; preserve READ, audit and records.

## Exit criteria

One authorized object/operation; one WRITE at most; no unrelated object changed;
readback and truthful final state; full audit; deterministic unknown-outcome
handling; manual restoration procedure demonstrated separately if authorized.
Restore disabled global flags before finishing. If MetricFlow cannot supply the
contract, remain BLOCKED and discuss a separate Meta route without activating it.
