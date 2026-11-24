# FinPilot MCP demo dataset

All transactions below are fictional. Use a dedicated demo company with no other transactions or budgets if you want the expected figures to match exactly. FinPilot interprets the numbers in the company's accounting currency; it does not convert them.

## Import the transactions

1. Sign in as an Owner or Admin, select the demo company, and open **Transactions**.
2. Select **Import CSV**, choose `mcp_demo_transactions.csv` from this folder, and select **Import CSV**.
3. The file contains 37 transactions dated 18 August through 10 November 2026. Stable demo references prevent the same rows from being imported twice into the same company.
4. Expense descriptions use FinPilot's existing category rules. The corresponding global default categories were present in the local database when this dataset was prepared. Inflows may remain pending categorization; cash-flow totals include them.

## Add the November budgets

FinPilot currently imports transactions from CSV; budgets must be added individually in **Budgets**. For each row below, select the default expense category, choose November 2026, enter the limit, and select **Add budget**. If a budget already exists for that category and month, inspect it rather than adding a duplicate.

| Expense category | Budget limit | Expected actual | Expected remaining |
| --- | ---: | ---: | ---: |
| Software & Subscriptions | 5,500.00 | 6,000.00 | -500.00 |
| Rent & Utilities | 15,000.00 | 13,800.00 | 1,200.00 |
| Payroll & Contractors | 40,000.00 | 38,500.00 | 1,500.00 |
| Marketing & Advertising | 9,000.00 | 10,300.00 | -1,300.00 |
| **Total** | **69,500.00** | **68,600.00** | **900.00** |

Actuals depend on the imported expenses being assigned to those exact default categories. Do not create same-named company categories for these budgets: they have different category IDs.

## Show the dashboard and MCP

- The full dashboard is shown after at least one invoice has been confirmed for the company. If the company shows the first-run invoice screen, use the existing invoice workflow to upload, review, and confirm a fictional invoice first. Upload extraction requires the worker; confirming an invoice does not create a transaction.
- On the dashboard, choose **90 days** or a custom range of 2026-08-18 through 2026-11-10, then choose November 2026 for budget versus actual.
- In MCP Inspector, run `list_my_companies`, copy the demo company's `company_id`, and run `get_cash_flow` with that ID, `start_date` `2026-08-18`, `end_date` `2026-11-10`, and `granularity` `month`.
- Run `get_budget_vs_actual` with the same `company_id` and `period` `2026-11`. The November totals should match the table if the demo company has no other relevant records.
- For November, the synthetic file contains inflows of 120,000.00, outflows of 68,600.00, and net cash flow of 51,400.00.

The dataset has not been imported by this file. Uploading it and adding the budgets create records in the selected company. CSV imports can queue unmatched rows for categorization; running the worker may process queued jobs using the configured LLM provider.
