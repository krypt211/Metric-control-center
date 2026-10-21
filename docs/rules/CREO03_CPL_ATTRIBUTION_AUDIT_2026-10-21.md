# Creo 03 — CPL attribution readiness audit — 2026-10-21

## Decision

The submitted v2 manual UI check is accepted: false CPL condition, KEEP,
complete period in America/Los_Angeles, fresh saved effective status, no action.
No additional repeat of this KEEP UI check is required for this checkpoint.
LIVE rule readiness remains BLOCKED. Production safety code was not weakened.

CPL uses reported spend / reported leads, not approved tracker sales. Nevertheless,
the attribution window, reporting date basis, and meaning of the reported lead
counter affect which leads enter that denominator. An unconfirmed sales approval
and an unconfirmed advertising attribution are distinct issues. A ratio can be
calculated from the returned counters without proving eligibility for action.
The engine's explicit policy is false condition -> KEEP, true condition with
unknown source attribution -> REVIEW. Removing the latter guard would change the
safety contract; this audit does not authorize that change.

## Official contract evidence

Public GET (no API key): https://metricflowit.click/api/v1/openapi.json?lang=en.
HTTP 200, SHA256 f52bc8ca0691fa0e2f2b5a5de06aa74a897546b88705ee16851859138a2f3327,
matching the earlier verified document. /insights offers from/to, level,
ad_account_ids, fields, URL/UTM filters, limit, cursor, currency. No attribution
window/report-time parameter or attribution evidence field is specified for its
InsightRow / InsightsResponse response. /adsets and /daily were also inspected.

The explicit attribution_spec field is in AdsetSpec, an entity creation input.
It does not establish the actual attribution of a historical insights response.
QueryRow.attributes is a generic attributes property, not a documented attribution
proof. No assumption of 7d_click/1d_view was inserted into production data.
This is a gap in the examined contract, not proof that MetricFlow can never expose
such evidence. The existing importer and adapter correctly retain attribution=None.

Data path inspected: SyncEngine -> DailyMetric.raw -> analytics.table source_attribution
-> smart_simulation -> smart_core.decision. Provider windows prove complete scoped
pagination/period ingestion, not advertising attribution. The missing attribution
is not repaired by another identical GET, fresh timestamp, UI reload, WRITE scope,
account management permission, configured/effective status, or successful PAUSE/ENABLE.

## Regression evidence

Added a parameterized pure-engine test in tests/test_smart_rules.py:

| Synthetic CPL | Limit | Attribution fixture | Decision |
| --- | --- | --- | --- |
| 5.38333333 | 8.81355932 | unknown | KEEP |
| 9 | 8.81355932 | unknown | REVIEW |
| 9 | 8.81355932 | explicitly supplied mock | WOULD_PAUSE |

All cases assert real_action=false, action_eligibility=false, DRY_RUN_ONLY.
Mock attribution is confined to tests and is not provider evidence. No threshold,
profile, rule configuration, advertising fact, or production simulation was changed.
The entire test_smart_rules.py suite: 35 PASS, 25.04 seconds; Ruff check and format PASS.
The initial 3 new cases: 3 PASS, 32 deselected. No real advertising provider calls.
Only the public unauthenticated documentation was downloaded in this audit.

## Next evidence checkpoint

Required proof for the same account, AD and exact historical period:

1. Lead event definition and included action types for MetricFlow's leads counter.
2. Attribution windows and whether unified/adset settings were used.
3. Reporting basis (for example impression-time versus conversion-time), timezone,
   and confirmation that the chosen definition applied to this response/period.
4. Provenance: a provider-documented contract or a verified READ extraction with
   reproducible request parameters and response evidence. Screenshots of current
   adset settings alone do not prove historical MetricFlow insights semantics.

A no-email alternative is a separately authorized, bounded direct Meta READ using
explicit attribution parameters, with Meta facts retained as a distinct source.
That would not retroactively certify MetricFlow rows; routing requires the existing
mapping/fallback compatibility checks. Meta remains disabled. No Graph API call,
credential check, connection change, pilot session or authorization was performed.
A direct Meta pilot needs its own current preflight and exact user authorization;
previous AD/ADSET writes do not authorize it. Do not delete MetricFlow: its manual
status controls were separately observed working and this is a READ-evidence gap.

If MetricFlow documentation later establishes the attribution contract, add a
validated versioned evidence mapping and tests before changing eligibility. Merely
setting a truthy local attribution value is not verification. Existing late UNKNOWN
pilot results and Rule Engine pause ownership must also remain honest.

STATUS: CPL LOGIC VERIFIED; METRICFLOW ATTRIBUTION EVIDENCE MISSING;
LIVE RULE EXECUTION BLOCKED; ADVERTISING WRITE REQUESTS THIS AUDIT=0.
Ignored official evidence: .tools/rules-attribution-20261021/official-evidence.json.
