# FinPilot deployment

Status: deployment configuration is in the repository; cloud services and a public URL have not yet been created.

## Hosting layout

- **Vercel** serves the Vite/React app from the `frontend/` directory. `frontend/vercel.mjs` sends `/api/*` requests to the configured backend origin and serves `index.html` for client-side routes.
- **Render** runs the API and arq worker together in the `finpilot-api` Docker web service. They share `/app/uploads`, which preserves the current invoice upload/download flow and lets the worker read the file.
- **Render PostgreSQL and Key Value** provide the database and Redis queue. The Render Blueprint connects the app to both using private service URLs.
- **Supabase Auth** remains the identity provider. The browser signs in with the Supabase public URL and anon key; the API validates the Supabase access token and maps the auth identity to the FinPilot user record.
- **Anthropic** provides the current constrained invoice extraction, transaction categorization, financial Q&A planning, anomaly phrasing, and digest summary calls.

This first hosted arrangement intentionally runs the API and worker as one Render service. The upload disk is attached to that service, so the invoice worker can read the same files without an object-storage rewrite. Keep it at one instance. Splitting the API and worker later requires shared object storage or a different storage backend.

## Vercel setup

1. Connect the repository to a Vercel project and set **Root Directory** to `frontend`.
2. Use the Vite build settings from `frontend/vercel.mjs`: `npm ci`, `npm run build`, output directory `dist`.
3. Add these project environment variables to Production and Preview:
   - `FINPILOT_API_ORIGIN`: the HTTPS origin assigned to the Render `finpilot-api` service, without a path (for example, `https://finpilot-api.onrender.com`).
   - `VITE_SUPABASE_URL`: the Supabase project URL.
   - `VITE_SUPABASE_ANON_KEY`: the Supabase anon/public key.
4. Deploy the frontend. Vercel preserves the website origin while proxying `/api/*` to Render, so the browser does not need cross-origin API configuration.

The API origin is checked when Vercel builds. A missing or malformed origin fails the deployment rather than silently sending API calls to the frontend.

## Render setup

1. Connect the Git repository to Render and create a Blueprint from the root `render.yaml`.
2. Choose the Singapore region, already reflected in the Blueprint, for the API, database, and Redis resources.
3. Provide the prompted `ANTHROPIC_API_KEY`, `SUPABASE_URL`, `SUPABASE_ANON_KEY`, and `APP_PUBLIC_URL` values. `APP_PUBLIC_URL` can be updated after the Vercel URL is known. Render generates `SECRET_KEY`.
4. The Blueprint creates a private Redis service, a private PostgreSQL database, and a persistent upload disk. Do not use the free service plans for the finished deployment: Render documents that free web services sleep and lose local files on restart, free Key Value has no persistence, and free Postgres expires after 30 days. The selected always-on/persistent plans have a monthly cost; confirm the current amount in Render before provisioning.
5. Render starts the API and worker together. Verify `https://<render-service>/health`, then set `FINPILOT_API_ORIGIN` in Vercel to that HTTPS origin.
6. After Vercel creates the production URL, update Render's `APP_PUBLIC_URL` and the Supabase Auth **Site URL** and redirect allow-list. Include the Vercel origin and the app routes `/verify-email` and `/reset-password`.

## Database initialization gate

The Blueprint deliberately does **not** run migrations automatically. Each Alembic migration must be reviewed before it changes a database. The repository's earlier frontend operating brief restricted migrations to `finpilot_test`; the production database is a new target, so confirm the intended release process before applying the reviewed chain.

After the database has been created and the migration chain has been reviewed and approved, run this manually from the Render service shell:

```sh
uv run alembic upgrade head
uv run python -m app.scripts.seed_categories
```

Do not add this command as a deploy-time hook until that migration process is agreed. Then check `/health`, sign in through the website, create a company, and follow the deployed acceptance process in [TESTING_GUIDE.md](TESTING_GUIDE.md).

## Deployment prerequisites still needing account access

- A Vercel account connected to the GitHub repository.
- A Render account with approval for its always-on compute/database/Redis costs.
- A Supabase Auth project whose signup, email verification, recovery, and redirect settings are known to work.
- An Anthropic API key for live AI workflows.
- Human review/approval of the current migration chain before it is applied to the new hosted database.
- A human-created Git commit and push: project instructions reserve commits to the human, and the deployment providers build from the connected repository.

No credentials belong in this repository. Enter them in provider dashboards or local ignored environment files.

## Provider references

- [Vite on Vercel](https://vercel.com/docs/frameworks/frontend/vite) describes the SPA fallback needed for direct client-side routes.
- [Vercel external rewrites](https://vercel.com/docs/routing/rewrites) documents proxying API requests to another origin without changing the browser URL.
- [Render free-plan limits](https://render.com/docs/free) explains why free services are unsuitable for this always-available setup. Check [current Render pricing](https://render.com/pricing) in the account before creating resources.
