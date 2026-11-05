# Campus Care

Campus Care is a Flask application for University Of Professional Studies' maintenance reporting workflow. Students and lecturers can report and track issues; maintenance staff update assigned work; administrators assign reports and manage accounts. The public campus board does not display reporter names or contact details.

Private report lists show the latest dated progress note. Search, status, issue-type and location filters, plus a compact-list toggle, help reporters and staff scan their queues. Administrators maintain the building/room directory, configure response targets, and review service analytics. Authorized maintenance staff can record append-only visit logs with labor, parts, and optional follow-up dates.

## Run a local preview

The app starts in **Demo data** mode when PostgreSQL is not configured. Preview the student, lecturer, maintenance, and administrator views with the role selector in the top bar. Demo reports are illustrative, stored in memory, and reset when the server restarts. Demo photo uploads are stored in the local `uploads/` folder.

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
py -m pip install -r requirements.txt
Copy-Item .env.example .env
py app.py
```

Edit `.env` to set local configuration; the app loads it automatically. Leave `DATABASE_URL` empty for the demo preview. Open `http://127.0.0.1:5000`.

## Connect PostgreSQL

Create a PostgreSQL database and application user using `psql` or pgAdmin. For example, as a PostgreSQL administrator:

```sql
CREATE USER campus_care WITH PASSWORD 'use-a-new-local-password';
CREATE DATABASE campus_care OWNER campus_care;
```

Set `DATABASE_URL` and `SECRET_KEY` in the project-root `.env` file (loaded automatically). URL-encode special characters in the database password. Do not commit `.env` or real credentials:

```powershell
py -m flask --app app init-db
py -m flask --app app create-admin
py -m flask --app app run
```
The administrator command prompts for name, email, and password. This operator-created initial account is marked verified. If you choose PowerShell environment variables instead of `.env`, keep them set in the same terminal whenever you run the app or its Flask commands. Existing MySQL data is not automatically migrated.

### Connect this local app to Supabase

1. In Supabase, open your project and choose **Connect**. Copy the PostgreSQL connection string for the **Session pooler** (recommended for hosted services that use IPv4). Do not use the Supabase `anon` or `service_role` API keys; this Flask app needs the PostgreSQL database URL.
2. In the URI, replace the password placeholder with your database password, URL-encoding any special characters. Add `?sslmode=verify-full` (or use `&sslmode=verify-full` if the URI already has query parameters).
3. Download the Supabase root certificate from the project's database SSL settings. Copy its full local path into `PGSSLROOTCERT` in `.env`, for example `C:/Users/YourName/Downloads/prod-supabase.cer`. Do not commit the certificate.
4. Generate a fresh app key in PowerShell with `py -c "import secrets; print(secrets.token_hex(32))"` and put the result in `.env` as `SECRET_KEY`. Put the pooler URI in `DATABASE_URL`.
5. From the project folder, run `py -m flask --app app init-db` once to create/update the schema, then `py -m flask --app app create-admin` once to create your first administrator. Start with `py -m flask --app app run`.

The `.env` file belongs in the project root beside `app.py`; it is ignored by Git. The committed `.env.example` is only a template and contains no credentials. For Render, do not upload `.env`: enter the settings in Render's **Environment** dashboard and use the CA certificate's Render secret-file path for `PGSSLROOTCERT`. Create and test with a separate Supabase project before using the production database. Rotate any database password previously shared in chat before connecting.

## Email/password sign-in

Password accounts require verified email addresses. Signup sends a one-time verification link; the sign-in page also offers password reset. Configure a trusted SMTP provider before users sign up or request recovery:

```powershell
$env:SMTP_HOST = "smtp.example.edu"
$env:SMTP_PORT = "587"
$env:SMTP_SECURITY = "starttls"
$env:SMTP_USERNAME = "campus-care@example.edu"
$env:SMTP_PASSWORD = "LOAD_FROM_A_SECRET_MANAGER"
$env:SMTP_FROM = "Campus Care <campus-care@example.edu>"
```

For implicit TLS, set `SMTP_SECURITY` to `ssl` and use the provider's SSL port (usually 465). Store SMTP credentials in environment variables or a secret manager, never in source control. Verification and password-reset links expire after 30 minutes and can be used once. Password resets invalidate existing sessions. New users can choose Student or Lecturer; this verifies mailbox access, not university affiliation, so production signup and role policies need institutional approval.

Existing accounts created before email verification was introduced are not automatically verified. An operator can verify an account after checking it out-of-band:

```powershell
py -m flask --app app verify-account --email account@example.edu
```

## Prepare a Render + Supabase deployment

The app is configured to run on Render with Supabase PostgreSQL. Deployment itself still requires your hosting accounts, domain, email provider, and approved campus policies. Do not commit credentials or paste them into source files.

1. **Put the project in a private GitHub repository.** The hosting service deploys from a connected Git repository. Review the files before pushing and keep `.env`, passwords, API keys, and database certificates out of Git.
2. **Prepare Supabase.** Create a production project and copy its PostgreSQL connection details. Use a connection method reachable from Render (the Supabase session pooler is suitable), enable certificate verification, and append `sslmode=verify-full` to the connection URL. Download the Supabase server CA certificate and add it to Render as a secret file; set `PGSSLROOTCERT` to that file's path.
3. **Create a Render Web Service** from the repository. The included `Procfile` runs Gunicorn. Set the build command to `pip install -r requirements.txt`; Render supplies `PORT`.
4. **Attach persistent storage** to the web service, mounted at `/var/data`. Set `UPLOAD_DIR=/var/data/uploads`. Uploaded photos otherwise disappear when an instance is replaced. A Render disk is tied to one service instance; keep this service at one instance and do not enable autoscaling while using local disk for photos.
5. **Set the following Render environment variables** in the service dashboard:

   ```text
   APP_ENV=production
   DATABASE_URL=<Supabase PostgreSQL URL with sslmode=verify-full>
   PGSSLROOTCERT=<path to the Supabase CA secret file>
   SECRET_KEY=<a newly generated, long random secret>
   PUBLIC_BASE_URL=https://<your-render-service>.onrender.com
   PHOTO_RETENTION_DAYS=<university-approved positive number>
   UPLOAD_DIR=/var/data/uploads
   TRUSTED_PROXY_HOPS=1
   ```

   `PUBLIC_BASE_URL` must be the canonical HTTPS origin, without a path. Change it to the approved custom HTTPS domain after configuring that domain in Render. For email/password sign-in, also configure `SMTP_HOST`, `SMTP_PORT`, `SMTP_SECURITY`, `SMTP_USERNAME`, `SMTP_PASSWORD`, and `SMTP_FROM`. Alternatively, configure the university OIDC settings described below. Never set both auth modes unless the intended OIDC behavior has been reviewed.
6. **Initialize the database and create the first administrator** after setting the production environment, using the Render Shell:

   ```text
   flask --app app init-db
   flask --app app create-admin
   ```

   The second command prompts for account details. Keep its credentials private. Back up the database before applying future schema changes.
7. **Verify the live service before inviting users:** test HTTPS sign-in, signup and email delivery (or OIDC), password recovery, a report submission, staff updates, restricted photo access, and database connectivity. Add the approved UPSA locations and only then enable public report intake.

The supplied process uses two Gunicorn workers. The PostgreSQL pool can use up to five connections per worker, so confirm Supabase's connection limits before increasing worker count or running multiple instances. Schedule `flask --app app prune-auth-attempts` daily with a Render Cron Job, supplying the same database and CA settings. Schedule `flask --app app prune-photos` only after the photo-retention policy is approved. Configure database and photo backups, monitoring, and incident response before public launch.

For OIDC, configure `OIDC_ISSUER`, `OIDC_CLIENT_ID`, `OIDC_CLIENT_SECRET`, and `OIDC_REDIRECT_URI`; register the exact HTTPS callback URI with the provider. OIDC sign-in requires a verified email claim and an administrator-provisioned account. When OIDC is enabled, password signup and recovery are disabled.

Email verification proves mailbox access only; it does not prove student status. Rate limits are baseline bot controls, not a substitute for an institution-approved CAPTCHA or managed bot challenge for a public service. The application does not configure PostgreSQL row-level-security policies; use a least-privilege database account, restricted database access, and separate production credentials. Obtain institutional approval for privacy notices, photo retention, identity-provider tenant, domain policy, service targets, account lifecycle, monitoring, and incident response.

The schema is in [`schema.sql`](./schema.sql). Report photos are limited to JPG, PNG, and WebP files up to 8 MB.

## Product decisions to confirm before production

The authoritative campus location hierarchy, anonymous-report policy, photo retention, urgency response targets, and feedback timing need university approval. The included sample reports and account names are fictional and must not be presented as live campus data.
