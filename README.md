# Browser Metrics Validator

Compares two Power BI dashboards opened through an authenticated Microsoft Edge profile.

The backend captures browser/network metrics, reads rendered Power BI visuals and filters, asks Gemini to identify screenshot KPIs, and generates an Excel workbook plus a Word validation report.

## Run

1. Create `.env` with `GEMINI_API_KEY` and (optionally) `GEMINI_MODEL`.
2. Install dependencies from `requirements.txt`.
3. Start the API with `python run_server.py`.
4. Start the React app in `Frontend` with `npm run dev`.

The frontend calls `POST /api/validate` with `source_url` and `target_url`; `GET /api/health` confirms the service is running.

## Generated reports

Each successful validation writes reports beneath `output/reports/`:

- Excel: side-by-side source/target KPI values, filter comparison, individual source/target table blocks on one sheet, and a complete cell-level comparison across all detected columns.
- Word: concise match/mismatch counts for KPIs and visual/table data, browser metrics, and matched-slicer test results when a common slicer option can be applied safely.

## Important behaviour

- Visual capture waits for Power BI to settle to reduce loading placeholders and duplicate visual readings.
- Virtualised table rows are collected by vertical scrolling; matrix columns are merged across horizontal scroll positions (2D scan per column slice). Tune via `MATRIX_MAX_SCROLL_STEPS` (default 60) and `SCROLL_STEP_WAIT_MS` (default 350) in `.env`.
- Multi-page Power BI reports are navigated page-by-page when more than one report page is detected.
- A shared slicer test is only attempted when both dashboards expose the same named slicer with the same unselected value. It applies that value to both dashboards, captures new screenshots, and performs Gemini analysis again.
- Gemini is intentionally lazy-initialised: a missing API key does not prevent browser-side table and filter collection.
