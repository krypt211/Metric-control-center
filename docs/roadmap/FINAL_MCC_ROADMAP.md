# Remaining roadmap to the first controlled automatic PAUSE/ENABLE

Project status: PARTIAL. Keep ACTIONS_ENABLED=false, LOCAL_READ_ONLY=true,
AI_ENABLED=false, AI_AUTOPILOT_ALLOWED=false. Meta disconnected.

1. Complete Smart Rules action model (PAUSE/ENABLE/notify), profile timezone,
   conflict priority and anti-loop cooldown. Reuse existing selection/economics/audit.
2. Obtain an authoritative MetricFlow Business WRITE contract and resolve scope mismatch.
3. Test the exact typed adapter with mock responses including timeout/unknown outcome;
   do not retry a mutation with unknown outcome until verified by readback.
4. Complete object-level permission/binding and configured/effective-status checks.
5. Rehearse a single-ad command through the shared manual/rule executor with hard limits.
6. Obtain separate explicit user authorization for one real ad and bounded operation.
7. Perform one controlled action, verify readback, retain evidence, restore gates.
8. Only after acceptance, enable bounded 30-60 minute automation on that exact scope.
Direct Meta LIVE is not a prerequisite for MetricFlow-based automation.

## Concrete MetricFlow support request (prepared, not sent)
Please provide the versioned Business API/OpenAPI contract for pause and enable:
- Does entities:write authorize these operations, or is campaigns:write mandatory?
  The stored key check reports entities:write but not campaigns:write.
- What namespace does entity_id use: MetricFlow database ID or Meta provider AD ID?
  How is account ownership and level=AD validated?
- Exact method/path/body/query/header fields, including whether the body is empty.
- Success status and synchronous/asynchronous response schema and operation ID.
- Errors for token/plan/scope/object permissions/validation/rate limits/not found.
- A documented way to verify effective permissions on the specific advertising object.
- Configured versus effective status fields; parent pause semantics and freshness.
- Idempotency key support, scope/retention, duplicate response semantics.
- Timeout/unknown-outcome recovery, safe retry policy and operation lookup.
- Exact READ endpoint and polling bounds for post-write verification.
No secrets need to be sent with this request.

## Evidence and unresolved provider boundary
[Official MetricFlow documentation](https://metricflowit.click/docs) inspected during
this audit lists campaigns:write and /api/v1/entities/{entity_id}/pause, /enable.
It does not resolve the full contract above; entities:write equivalence is not
documented there. Cached key metadata is not a new live scope verification.
No API contract was inferred from the UI or from Meta's different HTTP API.

User actions: obtain the provider's contract/object permissions; after local gaps
are completed, choose one AD and explicitly approve a single controlled mutation.
No new key is required merely for this audit; existing independent encrypted key
and READ connection are preserved.
