# Frontend

Next.js + TypeScript. Login, dashboard, tracker, creative analytics and admin users/status.
Next.js forwards the browser's opaque HttpOnly session to FastAPI; it does not inject a shared operator identity.
The backend checks every private request independently. MetricFlow credentials never enter the browser.

Use start.bat from the project root, then create_admin.bat to bootstrap the first administrator.
Local URL: http://127.0.0.1:3000/login. Production: https://APP_DOMAIN/login.
Optional snapshots remain manual. Advertising controls remain disabled.
