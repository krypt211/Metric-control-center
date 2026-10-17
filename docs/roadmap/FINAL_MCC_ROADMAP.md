# Remaining roadmap to the first controlled PAUSE/ENABLE

Project status: PARTIAL. Keep ACTIONS_ENABLED=false, LOCAL_READ_ONLY=true,
AI_ENABLED=false, AI_AUTOPILOT_ALLOWED=false. Meta disconnected.

Smart Rules core and DRY RUN scheduler: [local acceptance](../audit/SMART_RULES_FINAL_ACCEPTANCE.md).
WRITE contract subset and mock adapter: [OpenAPI acceptance](../integrations/METRICFLOW_WRITE_ADAPTER_ACCEPTANCE.md).
The published OpenAPI confirms entities:write; campaigns:write is no longer a required blocker.
Historical credential checks are not a new live permission verification.
Encrypted handoff and durable one-attempt preparation are now accepted only in
[isolated mock rehearsal](../integrations/CONTROLLED_WRITE_REHEARSAL_REPORT.md).

1. Resolve remaining contract gaps listed below; preserve the hard LIVE gate.
2. Complete the exact single-AD binding, object permission and configured/effective
   fresh READ verification contract. Job completion alone does not prove readback.
3. Complete bounded job observation and authoritative unknown-outcome/readback
   reconciliation in the existing ActionEngine once the missing provider contract
   is confirmed; no automatic resend. Encrypted handoff and durable mock claim/job
   correlation are implemented. The plaintext WRITE-key factory is removed.
4. Implement and accept the actual single-AD LIVE authorization/dispatch path only
   after those prerequisites pass. Current MOCK_ONLY permits refuse the working DB,
   require explicit MockTransport and have no public route or scheduled dispatcher.
   Mock race/restart acceptance does not authorize or certify a LIVE executor.
5. Choose one AD and obtain separate explicit user authorization for one bounded operation.
6. Perform the authorized operation only after all gates pass; verify readback/audit,
   restore safety flags. Restoration is a second separately authorized action.
7. Only after a successful single-AD pilot consider bounded automated scope.
Direct Meta LIVE is not a prerequisite for MetricFlow control.

## Focused provider support request (prepared, not sent)
The public OpenAPI now documents entities:write, POST pause/enable with level=ad,
and GET /api/v1/jobs/{job_id}. Please clarify the remaining points:

- Is entity_id a MetricFlow internal ID or Meta AD ID? Which READ field provides
  the exact WRITE ID and how is its AD/account ownership checked?
- Provide the exact HTTP 202 body/schema and all denial/error bodies. The operation
  description mentions 202 but the formal responses list only 200 and 422.
- What scopes and owner/team/acting-as permissions apply to GET jobs and a specific AD?
  Is there a documented non-mutating way to verify effective object permissions?
- Is Idempotency-Key supported? What are its scope/retention and duplicate semantics?
- If a POST times out before job_id is received, how can the operation be located
  without resending? Are partial application and expiration outcomes distinguishable?
- Does READ status mean Meta configured_status, and effective_status mean effective
  delivery? How fresh are these fields and the parent statuses after a WRITE?
- Which READ route, timestamps and consistency deadline prove post-action readback?
  Does a GET merely return the last sync cache? What are safe job-polling bounds?

No API keys or secrets are needed for this request. Existing encrypted WRITE and
READ connections are preserved. Public specification and local tests are not LIVE authorization.


## After the user-run single-AD DRY RUN acceptance (2026-10-17)

The [measured walkthrough](../rules/CREO06_DRY_RUN_CHECKPOINT_2026-10-17.md)
accepted FALSE -> KEEP and TRUE with unknown attribution -> REVIEW, then restored
the profile threshold and left scheduling off. LIVE operations remain blocked.
The [detailed acceptance plan](../integrations/METRICFLOW_NEXT_PHASE_ACCEPTANCE_PLAN.md)
separates attribution, history freshness policy and actual LIVE execution work.
The [provider clarification request](../integrations/METRICFLOW_PROVIDER_CLARIFICATION_REQUEST.md)
is ready for the user to send; no message was sent by the agent.
