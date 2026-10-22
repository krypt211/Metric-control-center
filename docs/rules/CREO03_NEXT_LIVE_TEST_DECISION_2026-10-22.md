# Creo 03: next LIVE rule test decision - 2026-10-22

Status: USER POLICY DECISION REQUIRED. No advertising authorization requested
or consumed by preparing this document. No new pilot, rule or permit created.

## Completed implementation

The existing rule-bound single-PAUSE pilot and atomic preparation fix are deployed
(commits cfdbaf2, 0ebbea1). The last related regression run passed 216 tests and
14 subtests, plus restricted-role isolated PostgreSQL mock checks. Those tests
were completed in the previous implementation stage, not rerun in this review.
Manual advertising PAUSE/ENABLE evidence is separate from rule LIVE evidence.

## Fresh evidence collected in this review

Public specification downloaded without a key:
https://metricflowit.click/api/v1/openapi.json?lang=en
HTTP 200, SHA256 ce1e16c80e8bbc8b3e28623ea579c867c8bebaeab80292123055b1599502d0fe.
The document hash differs from the earlier snapshot, but the descriptions and
parameter names of insights, daily and adsets are unchanged. InsightRow.leads
has no event-definition or attribution description. No documented insights
attribution-window/report-time request or historical response evidence was found.
AdsetSpec.attribution_spec is a creation input, not historical insights evidence.
Generic QueryRow.attributes and product-breakdown conversion text do not establish
these missing contracts. No synthetic attribution was inserted.

Context7 did not contain a relevant MetricFlow Business API library; unrelated
search matches were rejected. The browser fetch failed, so the public official
JSON was retrieved directly. No authenticated MetricFlow or Meta GET was made.

Current local evaluation was recomputed at 2026-10-22T13:25:48.906664+00:00 in a
PostgreSQL READ ONLY transaction with persist_snapshot=false for own/peer rules.
No simulation/economic snapshot was written. Selected rule:
4ce4ba4b-6c54-42f7-9da8-9e55e75cab3a, revision 2, disabled SMART_DRY_RUN;
next_evaluation_at is null. No active in-flight action exists for the selected AD.

| Item | Result |
| --- | --- |
| Account | Valya Sergeeva / act_1047962734516123 |
| AD | #71012012_EGR_Creo 03 / 120247730105960571 |
| Campaign | 120247730079240571 |
| Adset | 120247730105950571 |
| Rule period | 2026-09-28 / America/Los_Angeles |
| Spend / leads | USD 16.15 / 3 |
| CPL / maximum | 5.38333333 / 8.81355932 |
| Saved simulation | 500366ca-94d1-407d-bc81-b0945f08e448 / KEEP |
| Current recomputation | DATA_STALE / condition UNKNOWN |
| Window completeness | true |
| Source attribution | unconfirmed |
| Phase 2 financial eligibility | false |
| Current status freshness | false |
| Stored effective status | CAMPAIGN_PAUSED; does not prove own AD switch |
| MetricFlow READ connection | healthy, revision 1 |
| Local requests today / cooldown | 90 at check / none |
| Advertising executions | 3 historical; 0 new |

A healthy connection does not make this historical window or entity status fresh.
Do not overwrite the saved KEEP with this diagnostic. A bounded existing READ
refresh belongs immediately before an agreed test card; repeating that refresh
now would not repair attribution or confirmed-sales evidence.

The strict Phase 2 eligibility contract in economics.core also requires actual
ROI, compatible mature approval observations and sufficient approved sales.
Source attribution alone therefore cannot make this candidate eligible.
DRY_RUN action_eligibility=false is intentional, not a defect. The pilot checks
safe_to_consider_for_future_action; changing a DRY_RUN marker is no solution.

## Concrete option A: one reported-spend test, pending user agreement

Purpose: test the real rule-condition-to-single-PAUSE dispatch chain. This would
not validate profitability, approved-sale ROI, lead attribution or autopilot.

- Keep the existing CPL rule revision 2, profile and economics unchanged.
- Use a separate disabled test rule scoped only to AD 120247730105960571.
- Proposed one-leaf condition: reported USD spend >= 15.00, period 2026-09-28,
  America/Los_Angeles. Recorded spend is 16.15. The comparison can be TRUE only
  after an actual fresh scoped READ; the current condition diagnostic is UNKNOWN
  because SOURCE_STALE. No saved threshold or financial fact has been changed.
- Action only PAUSE_AD. No ENABLE, campaign/adset action, bid or budget change.
- Introduce an explicitly typed, pinned, one-off reported-spend evidence policy
  in the EXISTING experimental pilot, only after user agrees to this policy.
  Do not turn normal eligible_for_rule_evaluation or attribution into true.
- The narrowly scoped policy would replace attribution/approved-sales eligibility
  for this single spend-only experiment with verified fresh, complete, exact-AD
  spend evidence and a distinct operator acknowledgment. It would not apply to
  CPL, ROI, CPS, composite rules, other accounts/ADs or normal automation.
- Preserve all other gates: admin, workspace, exact hierarchy, current READ/WRITE
  revisions, separate encrypted credential, quota, no conflicting command,
  unchanged rule/simulation/evidence fingerprint, emergency-stop generation,
  current own ACTIVE status and both parents configured PAUSED. The last manual
  observation had the group enabled, so parent preconditions are NOT confirmed.
- No automatic parent changes. Any required group pause needs its own separate
  user action/authorization. Campaign must remain off so the test cannot start
  delivery through this hierarchy.
- Reuse the existing 3 bounded catalog GETs at preparation and 3 at execution,
  no retries, single POST maximum, concurrency 1 and permit lifetime <=600 seconds.
  Respect any tighter existing gate. No scheduler, automatic resend or AI.
- Test the new policy locally on mock transport and isolated PostgreSQL first,
  including rejection outside exact scope, changed evidence and stale data.
- Then present a new exact test card and request separate advertising permission
  for one PAUSE_AD. Agreement to this design is NOT that permission.
- After the one POST, manual readback must check the own AD switch and both
  parent switches by exact IDs. ACK alone is not verified success or pause ownership.
  Stop on timeout, token/permission/rate-limit error or identity/status change.

This changes the evidence policy for one experimental test. It is not implemented
or enabled under the general instruction to continue development. No existing
server-side gate was bypassed. A later restore/ENABLE would need separate permission.

## Option B: retain strict financial eligibility

Keep the current policy. To prepare a real positive financial rule candidate,
obtain documented attribution/lead semantics for the exact MetricFlow facts plus
compatible actual approval/revenue evidence, sufficient sample and a genuine TRUE
condition. A provider clarification is one route; a separately authorized Meta
READ is another source, not retroactive certification of MetricFlow rows.
No Meta connection or provider switch was performed by this review.

## Decision boundary

The next required user action is choosing the evidence policy for the next test:
A (separate, spend-only experiment) or B (retain strict financial evidence).
No more repeated KEEP screenshots are needed. If A is agreed, implementation,
mock acceptance and test-card preparation can continue before asking for any POST.

All four safety flags remain false/true/false/false respectively:
ACTIONS_ENABLED=false, LOCAL_READ_ONLY=true, AI_ENABLED=false,
AI_AUTOPILOT_ALLOWED=false. No new advertising WRITE and no Meta LIVE requests.
Ignored evidence: .tools/rule-readiness-final-20261022/.
