# Frontend

Next.js + TypeScript. Login, dashboard, tracker, creative analytics and admin users/status.
Next.js forwards the browser's opaque HttpOnly session to FastAPI; it does not inject a shared operator identity.
The backend checks every private request independently. MetricFlow credentials never enter the browser.

Use start.bat from the project root, then create_admin.bat to bootstrap the first administrator.
Local URL: http://127.0.0.1:3000/login. Production: https://APP_DOMAIN/login.
Optional snapshots remain manual. Advertising controls remain disabled.

Navigation is defined once in `lib/navigation.ts` and rendered by
`components/AppNavigation.tsx` through `SessionBar`. Add existing destinations to
that registry with explicit roles; desktop and mobile use the same entries.
At widths up to 1100px, the header uses the Menu disclosure. Settings includes
column presets, economic profiles, API connections (ADMIN), action safety and
administration (ADMIN). Backend permissions remain mandatory.

Dashboard tabs support `/?tab=statistics`, `creatives`, `tracker` and `overview`.
Economics supports `/economics?tab=profiles` and `tab=approval`.
`/?tab=statistics&columns=1` opens the existing Column Manager; the parameter is
consumed without changing other query parameters. Same-page tab transitions use
browser history and retain mounted page filters, including back/forward.
Table-local controls and economic profile/approval tabs remain available.

Navigation checks: `npm run test:unit`, `npm run build`, and
`npx playwright test e2e/navigation.spec.mjs` against the local Docker stack.
Browser fixtures create and remove disposable local accounts; keep advertising
writes disabled. See [navigation acceptance](../docs/ui-navigation-refactor.md).
