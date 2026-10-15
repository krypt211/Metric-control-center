# Remaining roadmap to the first controlled PAUSE/ENABLE

Project status: PARTIAL. Keep ACTIONS_ENABLED=false, LOCAL_READ_ONLY=true,
AI_ENABLED=false, AI_AUTOPILOT_ALLOWED=false. Meta disconnected.

Smart Rules core and DRY RUN scheduler: [local acceptance](../audit/SMART_RULES_FINAL_ACCEPTANCE.md).
WRITE contract subset and mock adapter: [OpenAPI acceptance](../integrations/METRICFLOW_WRITE_ADAPTER_ACCEPTANCE.md).
The published OpenAPI confirms entities:write; campaigns:write is no longer a required blocker.
Historical credential checks are not a new live permission verification.

1. Resolve remaining contract gaps listed below; preserve the hard LIVE gate.
2. Complete the exact single-AD binding, object permission and configured/effective
   fresh READ verification contract. Job completion alone does not prove readback.
3. Integrate purpose/workspace/revision-bound encrypted WRITE credential handoff,
   bounded job observation, durable one-attempt authorization/correlation and
   unknown-outcome reconciliation in the existing ActionEngine; no automatic resend.
   The legacy plaintext WRITE-key factory is not this provisioning flow.
4. Accept that exact executor path on mocks and isolated PostgreSQL concurrency/restart tests.
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
