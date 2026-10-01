# Browser Metrics Validator

Compares two Power BI dashboards opened through an authenticated Microsoft Edge profile.

The backend captures browser/network metrics, reads rendered Power BI visuals and filters, asks Gemini to identify screenshot KPIs, and generates an Excel workbook plus a Word validation report.

## Run

1. Create `Backend/.env` with `GEMINI_API_KEY` and (optionally) `GEMINI_MODEL`.
2. Install dependencies from `Backend/requirements.txt`.
3. Start the API from the `Backend` folder with `python run_server.py`.
4. Start the React app from the `Frontend` folder with `npm run dev`.

The API flow is two-phase:

1. `POST /api/browser-metrics` with `source_url` and `target_url` schedules the asynchronous browser capture and returns a `run_id` immediately.
2. Poll `GET /api/runs/{run_id}/status` until the capture reaches `completed`/`partial`/`failed`.
3. `POST /api/validate` with `{"run_id": "..."}` rebuilds the comparison from the captured artifacts (no second browser launch, no metric recalculation) and generates the Word report.
4. Download the Word report with embedded screenshots from `GET /api/runs/{run_id}/report`.

`GET /api/health` confirms the service is running. The frontend runs these steps automatically on submit.

## Git workflow (team)

Do **not** push directly to `main`. Use `dev` as the shared integration branch.

| Branch | Purpose |
|--------|---------|
| `main` | Production-ready code only (merge from `dev` via pull request) |
| `dev` | Daily integration — **push your work here** (or open a PR into `dev`) |
| `feature/*` | Optional personal branches → PR into `dev` |

### Clone and start on `dev`

```bash
git clone https://github.com/iamJagruthi/browser-metrics.git
cd browser-metrics
git checkout dev
git pull origin dev
```

### Day-to-day

```bash
git checkout dev
git pull origin dev
# ... make changes ...
git add <files>
git commit -m "Describe your change"
git push origin dev
```

### Install local hook (blocks accidental `git push origin main`)

```powershell
# Windows
.\Backend\scripts\install-git-hooks.ps1
```

```bash
# macOS / Linux
./Backend/scripts/install-git-hooks.sh
```

### Protect `main` on GitHub (repo admin)

In GitHub → **Settings** → **Branches** → **Add branch protection rule** for `main`:

- Require a pull request before merging
- Do not allow bypassing the above settings
- (Optional) Require approvals

Set **default branch** to `dev` under **Settings** → **General** so new PRs target `dev` by default.

Full admin checklist (screenshots-level steps): **`docs/GITHUB_BRANCH_POLICY.md`**

Optional API setup (repo admin PAT):

```powershell
$env:GITHUB_TOKEN = "ghp_your_personal_access_token"
.\Backend\scripts\setup-github-branch-protection.ps1
```

## Generated reports

Each successful validation writes reports beneath `Backend/output/reports/`:

- Excel: side-by-side source/target KPI values, filter comparison, individual source/target table blocks on one sheet, and a complete cell-level comparison across all detected columns.
- Word: concise match/mismatch counts for KPIs and visual/table data, browser metrics, and matched-slicer test results when a common slicer option can be applied safely.

## Important behaviour

- Visual capture waits for Power BI to settle to reduce loading placeholders and duplicate visual readings.
- Virtualised table rows are collected by vertical scrolling; matrix columns are merged across horizontal scroll positions (2D scan per column slice). Tune via `MATRIX_MAX_SCROLL_STEPS` (default 60) and `SCROLL_STEP_WAIT_MS` (default 350) in `.env`.
- Multi-page Power BI reports are navigated page-by-page when more than one report page is detected.
- A shared slicer test is only attempted when both dashboards expose the same named slicer with the same unselected value. It applies that value to both dashboards, captures new screenshots, and performs Gemini analysis again.
- Gemini is intentionally lazy-initialised: a missing API key does not prevent browser-side table and filter collection.
