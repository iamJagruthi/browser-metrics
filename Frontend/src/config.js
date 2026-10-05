// Central place for backend endpoints. Change BASE_URL here (or better,
// swap it for an env var like import.meta.env.VITE_API_BASE_URL) rather
// than hunting through components.
export const BASE_URL = 'http://localhost:8000';

// "Performance" API - schedules the asynchronous browser capture; replies
// immediately with { run_id }. Browser/performance metrics for source +
// target are surfaced the moment the capture completes (run status details).
export const BROWSER_METRICS_URL = `${BASE_URL}/api/browser-metrics`;

// "Validation" API - artifact-based comparison + Word report (no browser).
// Performance data is NOT part of validation; it lives in the performance
// capture above.
export const API_URL = `${BASE_URL}/api/validate`;

// 3) POST - uploads two spreadsheets and reuses the table comparison engine.
export const EXCEL_VALIDATE_URL = `${BASE_URL}/api/excel-validate`;

// 4) GET helpers keyed by run_id.
export const runStatusUrl = (runId) => `${BASE_URL}/api/runs/${runId}/status`;
export const runReportUrl = (runId) => `${BASE_URL}/api/runs/${runId}/report`;

export const REPORT_POLL_INTERVAL_MS = 3000;
// The capture poll no longer uses a wall-clock attempt cap: multi-page
// captures legitimately run several minutes and the backend's status is the
// sole authority for when a run ends (completed/partial/failed). This constant
// is only a liveness guard - the frontend aborts after this many consecutive
// failures to read the run status (server down, run removed, persistent 5xx).
export const REPORT_POLL_MAX_CONSECUTIVE_FAILURES = 3;
