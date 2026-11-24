# FinPilot test and metrics guide

This guide separates automated checks (which do not call Anthropic) from real-service checks. The interview-assessment MCP tests are outside this FinPilot product run.

## 1. Automated backend suite

Start the local PostgreSQL service first:

```powershell
docker compose up -d postgres
```

From the repository root, run:

```powershell
uv run pytest --ignore=tests/mcp -q
```

The test fixture refuses any database whose name does not end in `_test`, creates `finpilot_test` if necessary, applies Alembic migrations, and truncates its tables around each test. Keep `DATABASE_URL` unset in the shell so the fixture selects its guarded test URL. The tests fake Redis queue submissions and forbid real Anthropic requests.

Expected checks include API permissions, company isolation, transactions, invoices, CSV behavior, metrics, AI response validation, workers, and Supabase token validation. A passing backend suite does not prove the external Supabase login flow or call a live AI model.

## 2. Automated frontend checks

From `frontend/`:

```powershell
npm ci
npm run test -- --maxWorkers=1
npm run typecheck
npm run lint
npm run build
npm run e2e
```

Vitest uses mocked APIs and Supabase. Playwright browser tests also mock Auth/API routes; they check navigation, first-run screens, permissions presentation, and other UI paths, but they are not a real-backend or real-Supabase test. Lint may report the existing React Fast Refresh warnings recorded in the engineering log.

## 3. Local real-stack smoke test

Use a dedicated local development database, not `finpilot_test` and not a database containing records you want to keep.

1. Review the pending Alembic migration scripts and apply them to that local development database only.
2. Seed global categories with `uv run python -m app.scripts.seed_categories`.
3. Start the app services with `docker compose up -d --build` and the Vite frontend with `cd frontend; npm run dev`.
4. Register through the UI with a Supabase test project, complete the email code flow, sign in, and create a company. Confirm the company appears after refresh and sign-out/sign-in.
5. Create an owner, accountant, and viewer account or invite test users. Confirm the viewer has no write controls and the API rejects viewer write requests. Switch between two companies and confirm records never cross over.
6. Create one manual transaction, then edit and delete a separate one. Confirm the dashboard and ledger update.
7. Upload a CSV with a stable bank transaction ID. Re-upload the same file and confirm the second result marks that row as a duplicate. Check an invalid row and a malformed file.
8. Upload a clear, synthetic invoice with a purchase direction and then a sale direction. Confirm extraction settles, edit any missing field, and confirm the document. Verify invoice confirmation does not add a cash-flow transaction.
9. Create a transaction with a description that does not match any rule. Wait for the categorization worker; accept a high-confidence suggestion or override a review result. Confirm the ledger status and category.
10. Test Q&A, anomaly scan, and weekly digest using the guidance below.

The current checkout's auth path has not yet been live-smoke-tested. Because earlier project notes describe a different auth contract, treat the signup, email verification, recovery, Google OAuth (if enabled), logout, and API-token acceptance steps as a release gate. Do not call the app complete if these fail.

## 4. Get meaningful financial metrics

FinPilot calculates its metrics from company transactions, not invoices. An invoice is a payable/receivable record; confirming it never posts cash movement. For this scenario, create a temporary company in INR and add these four transactions manually, with the listed categories:

| Date | Description | Direction | Category | Amount |
|---|---|---|---|---:|
| 2026-11-01 | Demo customer payment | Inflow | Demo Income | ₹20,000.00 |
| 2026-11-03 | Demo office rent | Outflow | Rent | ₹35,000.00 |
| 2026-11-10 | Demo software subscription | Outflow | Software | ₹25,000.00 |
| 2026-11-17 | Demo travel | Outflow | Travel | ₹15,000.00 |

Set the dashboard's custom cash-flow range to **2026-10-26 through 2026-11-24** (30 inclusive dates), choose daily or monthly buckets, and enter an as-of-end-date cash balance of **₹300,000**. The API should report:

- Inflows: **₹20,000.00**
- Outflows: **₹75,000.00**
- Net cash flow: **−₹55,000.00**
- Average monthly outflow: **₹76,092.19**
- Average monthly net burn: **₹55,800.94**
- Estimated runway: **5.38 months**
- Transaction count: **4**

The cash balance is used for the runway request only; FinPilot does not save it. Values may differ if you change dates or transactions. Financial amounts are not converted between currencies.

For budget-versus-actual, create a **November 2026** budget of **₹40,000** for Software. The row should show actual **₹25,000**, remaining **₹15,000**, and 62.5% used.

After confirming this simple scenario, add the following anomaly history to the same company. Assign all records to an expense category and use the exact same merchant description:

- 2026-09-02: Demo Stationery Shop, outflow ₹1,000
- 2026-09-12: Demo Stationery Shop, outflow ₹1,000
- 2026-09-22: Demo Stationery Shop, outflow ₹1,000
- 2026-11-15: Demo Stationery Shop, outflow ₹4,000

Run the default anomaly scan. The recent spend is four times the three-record baseline mean, which gives the detector enough history to flag it. The four added rows change cash-flow totals, so capture the initial metric results first.

## 5. Live AI checks and model evaluation

Automated tests never make real Anthropic calls. To check the live AI layer after setting a valid API key:

- Upload a synthetic receipt/invoice with legible vendor, date, and total; check the extracted fields and manually correct one field before confirmation.
- Create a transaction description that does not match a rule and observe categorization, confidence, and review behavior.
- Ask one of the four supported financial Q&A questions and compare every displayed number with the dashboard/API. The model only selects the query plan; backend SQL and code provide figures.
- Run an anomaly scan and check whether its explanation source is `llm` or deterministic. Both are valid; the numeric comparison must match the computed baseline.
- Inspect the weekly digest after the Monday 08:00 UTC worker run. For a live-email check, configure digest SMTP; otherwise the persisted digest should say `not_configured`.

To calculate real categorization quality, prepare a labeled CSV with `description`, `amount`, and `expected_category`, then run the evaluation harness against a company whose categories include those labels:

```powershell
uv run python -m app.scripts.evaluate_categorization path\to\labeled.csv --company-id <company-uuid>
```

It makes one metered Anthropic request for every eligible row, does not write to the database, and reports precision and coverage across confidence thresholds from 0.70 to 0.95. Review the sample labels first; synthetic or unrepresentative data will not give a useful estimate. See [CATEGORIZATION_EVAL.md](CATEGORIZATION_EVAL.md).

## 6. Deployed user acceptance

After deployment and migration approval, repeat the real-stack flow on the Vercel URL. Check direct navigation to `/login`, `/register`, and one company route; confirm `/api/v1` requests reach the Render service through Vercel; and verify the API returns the authenticated user's company roles. Then re-run the exact four-transaction metric scenario and the role/company-isolation checks.

Keep the temporary demo company separate from any company where you later enter actual financial records. Delete only test data you explicitly created for this walkthrough.
