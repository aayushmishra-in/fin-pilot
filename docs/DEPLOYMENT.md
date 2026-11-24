# FinPilot deployment

Status: deployment files target a free hosted setup. Cloud services, credentials, reviewed schema setup, and the public URL still need to be configured by the project owner.

## Free hosting layout

- **Vercel Hobby** serves the React/Vite website. Its `/api/*` rewrite sends API calls to Render while keeping one browser origin.
- **Render Free** runs FastAPI and the arq worker together in one Docker web service. The service has an ephemeral filesystem and sleeps after inactivity, so it must not hold uploaded files or be treated as always-on.
- **Supabase Free** supplies the existing Auth project, PostgreSQL, and a private Storage bucket. Use the Supabase **session pooler** connection string for `DATABASE_URL` so the Render service can connect over IPv4. The application stores uploaded invoices and imported CSVs in Supabase Storage when `STORAGE_BACKEND=supabase`.
- **Upstash Redis Free** supplies the arq queue and rate-limit counters. Use its TLS connection string for `REDIS_URL`.
- **Anthropic** supplies the app's AI features. API usage may be metered even when the hosting tiers are free.

This is one product with a separately hosted browser bundle and API process. The browser only calls the Vercel origin; Vercel proxies `/api` to the API. Auth remains Supabase Auth. Locally, Docker Compose runs the same API and worker alongside PostgreSQL and Redis, while Vite serves the browser app separately and proxies `/api` to the local API. Local uploads use disk; hosted uploads use Supabase Storage.

## Free-tier behavior to expect

- Render Free sleeps after about 15 minutes without inbound traffic, and the next request may wait roughly a minute for startup. A sleeping instance is not continuously available.
- The API and worker share that one instance. Worker cron schedules cannot fire while it sleeps. Weekly digest scheduling and delivery sweeps run at worker startup as well as on their normal schedule, so they catch up after a wake/restart; actual delivery can still be delayed until then.
- Supabase Free projects may pause after a period of inactivity, and free database/storage quotas apply. Upstash also has free command/bandwidth quotas. Check the current provider dashboard limits before relying on the service.
- This is suitable for a free project/demo that can tolerate cold starts and delayed background work. It does not provide guaranteed always-on access.

## Prepare Supabase

1. Use the existing Supabase project. In Storage, create a **private** bucket named `finpilot-files` (or set `SUPABASE_STORAGE_BUCKET` to the chosen name).
2. Leave the bucket private. The backend uses the service-role key only for server-side object access; never put it in Vercel or browser code.
3. Copy the project URL, anon/public key, and service-role key for Render. The anon key is also used by the Vercel frontend.
4. Copy the session-mode pooler URI from the Supabase database connection settings. Put its password in the connection URI without committing it. Configure the URI as `DATABASE_URL` on Render; the app adapts `postgresql://` to its async driver.
5. Review every pending Alembic migration before applying it. After the target database and migration chain are confirmed, initialize the new database manually from a trusted local environment using that hosted database URL:

   ```powershell
   uv run alembic upgrade head
   uv run python -m app.scripts.seed_categories
   ```

   Do not run those commands against `finpilot_test`; test fixtures own that database. No migration runs automatically during deployment.

## Prepare Upstash

Create a Redis database in a nearby region and copy its TLS connection URL as `REDIS_URL`. Keep the value private. The arq worker and API use the same database; do not reuse the local Redis database.

## Deploy the API and worker to Render

1. Connect the Git repository and create a Blueprint using the root `render.yaml`. The blueprint creates only the free Docker web service; it does not create a database, Redis instance, disk, or paid resource.
2. Fill the prompted values in Render:
   - `DATABASE_URL`: Supabase session-pooler connection URI.
   - `REDIS_URL`: Upstash TLS URL.
   - `ANTHROPIC_API_KEY`: the key for live AI features.
   - `SUPABASE_URL`, `SUPABASE_ANON_KEY`, `SUPABASE_SERVICE_ROLE_KEY`: values from the existing Supabase project.
   - `APP_PUBLIC_URL`: set this after Vercel provides its URL; a temporary local origin is fine before then.
3. Keep `STORAGE_BACKEND=supabase` and the private `finpilot-files` bucket setting. Render generates `SECRET_KEY`.
4. Deploy and check `https://<render-service>.onrender.com/health`. The first request after idle may be slow while the free service wakes.

## Deploy the website to Vercel

1. Import the same repository in Vercel and set **Root Directory** to `frontend`.
2. Use the settings in `frontend/vercel.mjs` (`npm ci`, `npm run build`, output `dist`).
3. Set these environment variables for Production and Preview:
   - `FINPILOT_API_ORIGIN`: the HTTPS origin of the Render API, with no path.
   - `VITE_SUPABASE_URL`: the Supabase project URL.
   - `VITE_SUPABASE_ANON_KEY`: the Supabase anon/public key.
4. Deploy, then set Render's `APP_PUBLIC_URL` to the resulting Vercel origin. In Supabase Auth URL configuration, set the Site URL and allow the Vercel origin plus `/verify-email` and `/reset-password` redirect routes.
5. Follow the deployed acceptance process in [TESTING_GUIDE.md](TESTING_GUIDE.md), including signup, email verification, recovery, and API authorization. The local automated suite does not verify real Supabase Auth.

## Release gates and boundaries

- The project owner must make the human Git commit and push; provider builds use the connected branch.
- Never put Supabase service-role, database, Redis, or Anthropic credentials in the repository or Vercel frontend variables.
- Complete the manual migration review and database initialization before trying database-backed product flows.
- Verify invoice upload, download, and extraction plus CSV import on the deployed site to confirm Supabase Storage integration.
- Confirm signup, verified-email sign-in, company setup, role gating, and recovery against the actual Supabase configuration.
- A public URL and healthy service do not by themselves verify AI behavior or financial correctness. Use the test guide's deterministic expected metrics and live-AI checks.

## Provider references

- [Vercel Vite deployment](https://vercel.com/docs/frameworks/frontend/vite)
- [Vercel external rewrites](https://vercel.com/docs/routing/rewrites)
- [Render free services](https://render.com/docs/free)
- [Supabase Storage](https://supabase.com/docs/guides/storage)
- [Supabase connection strings](https://supabase.com/docs/guides/database/connecting-to-postgres)
- [Upstash Redis](https://upstash.com/docs/redis/overall/getstarted)
