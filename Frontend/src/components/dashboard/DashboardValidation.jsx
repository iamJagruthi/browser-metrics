import { useState } from 'react';
import { Loader2, PlayCircle } from 'lucide-react';
import { API_URL, BROWSER_METRICS_URL, runStatusUrl } from '../../config';
import { REPORT_POLL_INTERVAL_MS, REPORT_POLL_MAX_CONSECUTIVE_FAILURES } from '../../config';
import { UrlField } from '../form/UrlField';
import { ErrorBanner } from '../form/ErrorBanner';
import { ProgressSteps } from '../progress/ProgressSteps';
import { PerformanceSummary } from '../metrics/PerformanceSummary';
import { AppliedFiltersSection } from '../comparison/AppliedFiltersSection';
import { AiResultsSection } from '../comparison/AiResultsSection';
import { MismatchResultsSection } from '../comparison/MismatchResultsSection';
import { DashboardResultPanel } from './DashboardResultPanel';
import { DashboardInventory } from './DashboardInventory';

const SOURCE_TAG_STYLE = {
  background: 'var(--surface-alt)',
  color: 'var(--text-muted)',
  border: '1px solid var(--border)',
};
const TARGET_TAG_STYLE = { background: 'var(--accent-bg)', color: 'var(--accent-text)' };

const STEP_DEFS = [
  { key: 'started', label: 'Performance capture started' },
  { key: 'captured', label: 'Performance metrics captured' },
  { key: 'compared', label: 'Validation comparison built' },
  { key: 'docx', label: 'Word report with embedded screenshots generated' },
];

const extractErrorDetail = async (res) => {
  const data = await res.json().catch(() => ({}));
  return data.detail || `Request failed with status ${res.status}`;
};

const waitForCapture = async (runId, intervalMs = REPORT_POLL_INTERVAL_MS) => {
  let consecutiveFailures = 0;
  for (;;) {
    let statusDoc;
    try {
      const res = await fetch(runStatusUrl(runId));
      if (res.status === 404) {
        throw new Error('Capture run no longer exists on the server. Start a new run.');
      }
      if (!res.ok) {
        throw new Error('Failed to read capture status.');
      }
      statusDoc = await res.json();
    } catch (err) {
      // The backend status is the authority: keep polling while the run is
      // legitimately "running" (multi-page captures take minutes). Only abort
      // once the server can no longer be read reliably.
      consecutiveFailures += 1;
      if (consecutiveFailures >= REPORT_POLL_MAX_CONSECUTIVE_FAILURES) {
        throw new Error(
          `Unable to reach the validation server while the capture was in progress. ${
            err && err.message ? err.message : ''
          }`.trim(),
          { cause: err },
        );
      }
      await new Promise((resolve) => setTimeout(resolve, intervalMs));
      continue;
    }
    consecutiveFailures = 0;
    if (['completed', 'partial', 'failed'].includes(statusDoc.status)) {
      return statusDoc;
    }
    await new Promise((resolve) => setTimeout(resolve, intervalMs));
  }
};

const initialSteps = () => STEP_DEFS.map((step, index) => ({ ...step, state: index === 0 ? 'active' : 'pending' }));

export function DashboardValidation() {
  const [sourceUrl, setSourceUrl] = useState('');
  const [targetUrl, setTargetUrl] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [result, setResult] = useState(null);
  const [captureStatus, setCaptureStatus] = useState(null);
  const [steps, setSteps] = useState([]);

  const setStepState = (key, state) =>
    setSteps((prev) => prev.map((step) => (step.key === key ? { ...step, state } : step)));

  const resetSteps = () => setSteps(initialSteps());

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError('');
    setResult(null);
    setCaptureStatus(null);

    if (!sourceUrl.trim() || !targetUrl.trim()) {
      setSteps([]);
      setError('Please enter both dashboard URLs.');
      return;
    }

    setLoading(true);
    resetSteps();
    try {
      // 1) Schedule the async browser capture.
      const captureRes = await fetch(BROWSER_METRICS_URL, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ source_url: sourceUrl.trim(), target_url: targetUrl.trim() }),
      });
      if (!captureRes.ok) {
        setStepState('started', 'error');
        throw new Error(await extractErrorDetail(captureRes));
      }
      const capture = await captureRes.json();
      const runId = capture.run_id;
      setStepState('started', 'done');
      setStepState('captured', 'active');

      // 2) Poll until the browser capture finishes. The moment it does,
      // surface the performance metrics (browser-metrics/performance API)
      // BEFORE validation, so the user never waits for results they already
      // have. Validation itself carries no performance data.
      const statusDoc = await waitForCapture(runId);
      setCaptureStatus(statusDoc);
      if (statusDoc.status === 'failed') {
        setStepState('captured', 'error');
        throw new Error(statusDoc.details?.error || 'Browser capture failed on the server.');
      }
      setStepState('captured', 'done');
      setStepState('compared', 'active');

      // 3) Rebuild the comparison + generate the Word report (no browser).
      const validateRes = await fetch(API_URL, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ run_id: runId }),
      });
      if (!validateRes.ok) {
        setStepState('compared', 'error');
        throw new Error(await extractErrorDetail(validateRes));
      }
      const data = await validateRes.json();
      setStepState('compared', 'done');
      setResult(data);

      if (data.docx_ready === true) {
        setStepState('docx', 'done');
      } else {
        setStepState('docx', 'error');
      }
    } catch (err) {
      setError(err.message || 'Something went wrong while validating.');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="space-y-6">
      <div className="dv-surface p-6 md:p-8 rounded-3xl animate-in fade-in zoom-in-95 duration-500">
        <form onSubmit={handleSubmit} className="space-y-6">
          <div className="grid md:grid-cols-2 gap-6">
            <UrlField
              tag="SOURCE"
              tagStyle={SOURCE_TAG_STYLE}
              value={sourceUrl}
              onChange={setSourceUrl}
              placeholder="https://app.powerbi.com/..."
            />
            <UrlField
              tag="TARGET"
              tagStyle={TARGET_TAG_STYLE}
              value={targetUrl}
              onChange={setTargetUrl}
              placeholder="https://app.powerbi.com/..."
            />
          </div>

          <div className="flex justify-center pt-1">
            <button
              type="submit"
              disabled={loading}
              className="dv-btn-primary group relative inline-flex items-center justify-center gap-2 px-8 py-3.5 font-semibold rounded-xl transition-all duration-300 w-full md:w-auto min-w-[240px]"
            >
              {loading ? (
                <>
                  <Loader2 className="w-5 h-5 animate-spin" />
                  <span>Validating…</span>
                </>
              ) : (
                <>
                  <PlayCircle className="w-5 h-5 group-hover:scale-110 transition-transform duration-300" />
                  <span>Run Dashboard Validation</span>
                </>
              )}
            </button>
          </div>
          <p className="text-center text-xs" style={{ color: 'var(--text-muted)' }}>
            Opens both dashboards once to capture performance metrics, visuals, filters, and screenshots, then builds the comparison and Word report from the artifacts.
          </p>
        </form>
      </div>

      <ErrorBanner message={error} />
      <ProgressSteps steps={steps} />

      {captureStatus && <PerformanceSummary captureStatus={captureStatus} />}

      {result && (
        <div className="space-y-12">
          <DashboardResultPanel result={result} />
          {result.ai_analysis && <AiResultsSection aiAnalysis={result.ai_analysis} />}
          <MismatchResultsSection mismatches={result.mismatches} />
          {result.dashboards && result.dashboards.length > 0 && (
            <DashboardInventory dashboards={result.dashboards} />
          )}
          {result.applied_filter_selections && (
            <AppliedFiltersSection
              appliedFilters={result.applied_filter_selections}
              mismatches={result.mismatches}
            />
          )}
        </div>
      )}
    </div>
  );
}