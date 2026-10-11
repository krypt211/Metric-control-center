# UI navigation refactor acceptance

Date: 2026-10-11. Scope: compact navigation only; not a new action-engine phase.

## Actual navigation inventory

Before this change, page headers repeated branding and SessionBar links to
manual control, recommendations, rules, economics, connections and administration.
The dashboard separately rendered local tabs. Economics already had statistics,
profiles and approval tabs. Column Manager already existed inside each table.

| Existing destination | New location |
| --- | --- |
| `/` (overview, statistics, creatives, tracker tabs) | Main navigation, short labels |
| `/economics` | Main navigation |
| `/rules` | Main navigation |
| `/manual-control` | Main navigation |
| `/recommendations` | Main navigation |
| Existing table Column Manager and saved presets | Settings / General; table controls retained |
| Existing economics profiles tab | Settings / General; economics tab retained |
| `/settings/connections` | Settings / General, ADMIN only |
| `/settings/manual-control` | Settings / Control, existing role permissions |
| `/admin` | Settings / System, ADMIN only |

No separate user-profile, rule-settings, diagnostics or settings-audit route
exists. No placeholder route was added. Provider diagnostics and routing remain
inside connections. Existing AI Copilot/audit and legacy dashboard tabs retain
their existing non-LOCAL-READ-ONLY visibility. Local approval input remains
inside economics; rule construction and DRY RUN remain inside rules.

## Implementation

`frontend/lib/navigation.ts` is the shared registry with ID, label, real target,
icon, category, roles, desktop/mobile visibility and exact active matching.
`AppNavigation` renders both desktop and mobile from this registry. `SessionBar`
retains authenticated session loading, preference flush, serialized CSRF logout
and redirect behavior. All authenticated pages share that header with MCC branding.

Settings closes on Escape, outside pointer/focus, destination selection and
resize. Keyboard supports Tab, arrows, Home and End, with visible focus and
Escape returning focus to the trigger. Controls expose accessible names,
expanded state and panel association. Links expose active-page state.

At <=1100px the header uses one Menu button; its scrollable panel contains main
sections, grouped settings, current user/role and logout. Desktop stays one row.
No new package or UI library was installed.

Safe tab URLs: `/?tab=overview`, `statistics`, `creatives`, `tracker`;
`/economics?tab=profiles` and `tab=approval`.
`/?tab=statistics&columns=1` opens the existing manager and consumes only
`columns`. Same-page transitions preserve unrelated query parameters and mounted
page filters, with browser back/forward support. A Settings column link opens the
current table's manager directly when available. Cross-page transitions retain
the application's existing page initialization behavior.

## Validation

- Frontend unit tests: **33 passed** (28 existing, 5 new registry tests).
- TypeScript and production build: **PASS**, including the local Docker build.
- New navigation E2E: **7 distinct scenarios PASS** (first 5 plus final 2).
- Selected existing regression E2E: **9 distinct scenarios PASS** (8 plus final 1).
  Six column scenarios, economic profiles, approval/cohort input and real rule lifecycle/DRY RUN.
- Chromium widths: **1440 / 1024 / 768 / 390 PASS**. Assertions cover document
  overflow, panel bounds and hit testing above other content. Desktop/mobile
  screenshots were visually inspected.
- ADMIN, OPERATOR and VIEWER: **PASS**. Both menus hide ADMIN-only destinations
  from other roles; real `/api/admin/providers` returns 200 / 403 / 403.
- Column deep links, saved sets, statistics period, economic profiles,
  back/forward, rule/manual/connections/admin routes and mobile logout: **PASS**.

An initial new-test assertion expected the shortened menu label as the existing
connections page heading. It was corrected to the actual unchanged heading;
no application behavior or assertion was weakened. The first retry had already
loaded the earlier assertion; the final scoped rerun passed both remaining cases.
The existing rule lifecycle test also used the former long header link label;
it now locates the main navigation link with the new short label. Only that
scenario was repeated after the shared login rate-limit window expired naturally.
No rate-limit configuration or Redis limiter entry was modified.
Playwright retries were disabled. The full E2E suite is not claimed here.

Private local evidence: `.tools/navigation-navigation-browser.json`,
`.tools/navigation-navigation-fixed-browser.json`, their integrity JSON files,
`.tools/navigation-regression-browser.json` and regression integrity JSON. The final rule rerun uses
`.tools/navigation-rule-final-browser.json` and its integrity JSON.
Screenshots are `.tools/navigation-1440.png` and `.tools/navigation-390.png`.
These local artifacts contain fixture/runtime evidence and are not committed.

## Data and operational boundary

All navigation runs preserved **62/62 complete PostgreSQL table hashes**;
changed tables = 0 and ActionExecution delta = 0. Existing fixtures create
and clean only disposable local data. READ worker/scheduler are paused around
comparisons and resumed in finally; no advertising worker is activated.

Backend source, database schema, provider contracts, advertising statuses,
rule evaluation and action preparation/execution logic were not changed.
This UI task does not rerun the full backend suite: see the independently
completed [Phase 4A verification](phase4/FINAL_VERIFICATION_2026-10-11.md).
Runtime `/health/ready`: ready; PostgreSQL, migrations, schema and Redis OK.
`ACTIONS_ENABLED=false`, `LOCAL_READ_ONLY=true` remain set.
No real advertising WRITE request was executed.

Phase 4A remains **COMPLETE / READY - LOCAL SIMULATION ONLY**.
MetricFlow WRITE readiness remains **UNVERIFIED / LIVE BLOCKED**;
Phase 4B remains **BLOCKED / NOT AUTHORIZED**. This navigation change establishes
no new provider capability or authorization.

Only frontend was rebuilt/recreated. The previously reported obsolete stopped
migration container remains an existing operational issue, outside this UI task.
The pre-existing uncommitted roadmap and Phase 4 reports were preserved.
