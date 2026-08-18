import { useState, useEffect, useRef } from 'react';
import {
  Globe,
  Clock3,
  Camera,
  Server,
  Activity,
  AlertTriangle,
  CheckCircle2,
  BarChart3,
  Monitor,
  PlayCircle,
  Loader2,
  Search,
  ShieldCheck,
  AlertCircle,
  Sun,
  Moon,
  ArrowLeftRight,
  Download,
  FileSpreadsheet,
  FileText,
  Circle,
} from 'lucide-react';
import './App.css';

const BASE_URL = 'http://localhost:8000';
const API_URL = `${BASE_URL}/api/validate`;

/* ------------------------------------------------------------------ */
/*  Design system — black & yellow. Yellow carries every interactive   */
/*  and brand moment; black anchors structure. Match/near-match/       */
/*  mismatch keep green/yellow/red so results still read at a glance.  */
/* ------------------------------------------------------------------ */
const styles = `
@import url('https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@500;600;700&family=Inter:wght@400;500;600;700&family=IBM+Plex+Mono:wght@400;500;600&display=swap');

/* Override Vite's default template styles (body { display:flex; place-items:center },
   #root { max-width: 1280px; margin: 0 auto }) which otherwise squeeze the app into
   a centered box and leave dead space on either side. */
html, body, #root {
  width: 100%;
  height: 100%;
  min-height: 100vh;
  margin: 0;
  padding: 0;
  max-width: none;
  display: block;
  place-items: normal;
}

.dv-app {
  width: 100%;
  min-height: 100vh;
  --bg: #FAFAF7;
  --surface: #FFFFFF;
  --surface-alt: #F2F2ED;
  --border: #E3E3DB;
  --text: #0A0A0A;
  --text-muted: #5C5C53;
  --ink: #0A0A0A;
  --accent: #F5C518;
  --accent-text: #7A5F00;
  --accent-bg: #FFF6D8;
  --accent-border: #EBD583;
  --success: #3F8F4A;
  --success-bg: #E8F5EA;
  --success-border: #BEE0C4;
  --danger: #C23B34;
  --danger-bg: #FBEAE8;
  --danger-border: #EFC0BB;
  --shadow-sm: 0 1px 2px rgba(10,10,10,0.06);
  --shadow-md: 0 10px 30px rgba(10,10,10,0.10);
  --font-display: 'Space Grotesk', sans-serif;
  --font-body: 'Inter', sans-serif;
  --font-mono: 'IBM Plex Mono', monospace;
  background: var(--bg);
  color: var(--text);
  font-family: var(--font-body);
  min-height: 100vh;
  transition: background 0.25s ease, color 0.25s ease;
}

.dv-app[data-theme='dark'] {
  --bg: #0A0A0A;
  --surface: #141414;
  --surface-alt: #1B1B1B;
  --border: #2A2A2A;
  --text: #F5F5F0;
  --text-muted: #9C9C93;
  --ink: #F5F5F0;
  --accent: #F5C518;
  --accent-text: #F5C518;
  --accent-bg: rgba(245,197,24,0.12);
  --accent-border: rgba(245,197,24,0.32);
  --success: #5FBE6B;
  --success-bg: rgba(95,190,107,0.14);
  --success-border: rgba(95,190,107,0.32);
  --danger: #EF6259;
  --danger-bg: rgba(239,98,89,0.14);
  --danger-border: rgba(239,98,89,0.32);
  --shadow-sm: 0 1px 2px rgba(0,0,0,0.5);
  --shadow-md: 0 16px 40px rgba(0,0,0,0.45);
}

.dv-app * { font-family: inherit; }
.dv-font-display { font-family: var(--font-display); letter-spacing: -0.01em; }
.dv-font-mono { font-family: var(--font-mono); font-variant-numeric: tabular-nums; }

.dv-topbar {
  background: linear-gradient(135deg, #141414 0%, #000000 100%);
  border-bottom: 3px solid var(--accent);
}

.dv-surface {
  background: var(--surface);
  border: 1px solid var(--border);
  box-shadow: var(--shadow-sm);
}

.dv-input {
  background: var(--surface-alt);
  border: 1px solid var(--border);
  color: var(--text);
  font-family: var(--font-mono);
}
.dv-input::placeholder { color: var(--text-muted); opacity: 0.7; }
.dv-input:focus {
  outline: none;
  border-color: var(--accent);
  box-shadow: 0 0 0 3px var(--accent-bg);
  background: var(--surface);
}

.dv-btn-primary {
  background: var(--accent);
  color: #0A0A0A;
  box-shadow: var(--shadow-sm);
}
.dv-btn-primary:hover:not(:disabled) {
  filter: brightness(1.06);
  box-shadow: var(--shadow-md);
}
.dv-btn-primary:disabled { opacity: 0.55; cursor: not-allowed; }

.dv-btn-outline {
  background: var(--surface);
  color: var(--text);
  border: 1px solid var(--border);
}
.dv-btn-outline:hover:not(:disabled) { border-color: var(--accent); background: var(--accent-bg); }
.dv-btn-outline:disabled { opacity: 0.5; cursor: not-allowed; }

.dv-toggle {
  background: rgba(255,255,255,0.08);
  border: 1px solid rgba(255,255,255,0.18);
  color: #fff;
}
.dv-toggle:hover { background: rgba(255,255,255,0.16); }

.dv-row:nth-child(even) { background: var(--surface-alt); }
.dv-row:hover { background: var(--accent-bg); }

.dv-stripe-source { border-top: 4px solid var(--ink); }
.dv-stripe-target { border-top: 4px solid var(--accent); }

.dv-diff-row-match { border-left: 4px solid var(--success); }
.dv-diff-row-near { border-left: 4px solid var(--accent); }
.dv-diff-row-mismatch { border-left: 4px solid var(--danger); }

.dv-pulse { animation: dv-pulse-anim 1.6s ease-in-out infinite; }
@keyframes dv-pulse-anim {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.35; }
}

@media (prefers-reduced-motion: reduce) {
  .dv-app * { animation-duration: 0.001ms !important; transition-duration: 0.001ms !important; }
}
`;

/* ------------------------------------------------------------------ */
/*  Small building blocks                                             */
/* ------------------------------------------------------------------ */

function BrandMark({ size = 26 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" fill="none">
      <rect x="3" y="3" width="16" height="16" rx="4" fill="#0A0A0A" stroke="#F5C518" strokeWidth="1.5" />
      <circle cx="22" cy="21" r="8" fill="#F5C518" />
    </svg>
  );
}

function HealthDot({ status }) {
  const label = status === 'online' ? 'API online' : status === 'offline' ? 'API unreachable' : 'Checking API…';
  const color = status === 'online' ? '#F5C518' : status === 'offline' ? '#EF6259' : 'rgba(255,255,255,0.4)';
  return (
    <div className="flex items-center gap-1.5 px-2.5 py-1 rounded-full" style={{ background: 'rgba(255,255,255,0.08)' }} title={label}>
      <Circle
        className={status === 'checking' ? 'dv-pulse' : ''}
        style={{ width: 8, height: 8, color, fill: color }}
      />
      <span className="text-[11px] text-white/60 hidden sm:inline">{label}</span>
    </div>
  );
}

function TopBar({ theme, onToggleTheme, apiStatus }) {
  return (
    <div className="dv-topbar sticky top-0 z-20">
      <div className="max-w-6xl mx-auto px-4 sm:px-8 py-3.5 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="p-1.5 bg-white/10 rounded-lg border border-white/15">
            <BrandMark />
          </div>
          <div>
            <p className="dv-font-display text-white font-semibold text-base leading-none">
              Dashboard Validator
            </p>
            <p className="text-[11px] text-white/60 mt-1 tracking-wide uppercase">
              SpartanNash · Talent Acquisition BI
            </p>
          </div>
        </div>

        <div className="flex items-center gap-3">
          <HealthDot status={apiStatus} />
          <button
            onClick={onToggleTheme}
            aria-label="Toggle dark mode"
            className="dv-toggle flex items-center gap-2 px-3 py-2 rounded-full text-xs font-medium transition-colors duration-200"
          >
            {theme === 'dark' ? <Sun className="w-4 h-4" /> : <Moon className="w-4 h-4" />}
            <span className="hidden sm:inline">{theme === 'dark' ? 'Light' : 'Dark'}</span>
          </button>
        </div>
      </div>
    </div>
  );
}

function Hero() {
  return (
    <div className="text-center mb-10 mt-10 animate-in fade-in slide-in-from-top-4 duration-700">
      <p className="dv-font-mono text-xs tracking-[0.2em] uppercase mb-3" style={{ color: 'var(--accent-text)' }}>
        Power BI · Pipeline QA
      </p>
      <h1 className="dv-font-display text-4xl sm:text-5xl font-bold mb-3" style={{ color: 'var(--text)' }}>
        Dashboard Metrics Validator
      </h1>
      <p className="text-base" style={{ color: 'var(--text-muted)' }}>
        Run two Power BI dashboards side by side and confirm the KPIs still match.
      </p>
    </div>
  );
}

function ValidationForm({ sourceUrl, setSourceUrl, targetUrl, setTargetUrl, handleSubmit, loading }) {
  return (
    <div className="dv-surface p-6 md:p-8 rounded-3xl animate-in fade-in zoom-in-95 duration-500">
      <form onSubmit={handleSubmit} className="space-y-6">
        <div className="grid md:grid-cols-2 gap-6">
          <div className="space-y-2">
            <label className="flex items-center gap-2 text-sm font-semibold ml-1">
              <span
                className="dv-font-mono text-[10px] font-bold px-1.5 py-0.5 rounded"
                style={{ background: 'var(--surface-alt)', color: 'var(--text-muted)', border: '1px solid var(--border)' }}
              >
                SOURCE
              </span>
              Dashboard URL
            </label>
            <input
              type="text"
              value={sourceUrl}
              onChange={(e) => setSourceUrl(e.target.value)}
              placeholder="https://app.powerbi.com/..."
              className="dv-input w-full px-4 py-3 rounded-xl text-sm transition-all duration-200"
            />
          </div>

          <div className="space-y-2">
            <label className="flex items-center gap-2 text-sm font-semibold ml-1">
              <span
                className="dv-font-mono text-[10px] font-bold px-1.5 py-0.5 rounded"
                style={{ background: 'var(--accent-bg)', color: 'var(--accent-text)' }}
              >
                TARGET
              </span>
              Dashboard URL
            </label>
            <input
              type="text"
              value={targetUrl}
              onChange={(e) => setTargetUrl(e.target.value)}
              placeholder="https://app.powerbi.com/..."
              className="dv-input w-full px-4 py-3 rounded-xl text-sm transition-all duration-200"
            />
          </div>
        </div>

        <div className="flex justify-center pt-1">
          <button
            type="submit"
            disabled={loading}
            className="dv-btn-primary group relative inline-flex items-center justify-center gap-2 px-8 py-3.5 font-semibold rounded-xl transition-all duration-300 w-full md:w-auto min-w-[220px]"
          >
            {loading ? (
              <>
                <Loader2 className="w-5 h-5 animate-spin" />
                <span>Validating…</span>
              </>
            ) : (
              <>
                <PlayCircle className="w-5 h-5 group-hover:scale-110 transition-transform duration-300" />
                <span>Run Validation</span>
              </>
            )}
          </button>
        </div>
      </form>
    </div>
  );
}

const METRIC_ROWS = [
  { key: 'http_status', label: 'HTTP Status', icon: Server },
  { key: 'browser_launch_seconds', label: 'Browser Launch', icon: Globe, unit: 's' },
  { key: 'page_load_seconds', label: 'Page Load', icon: Clock3, unit: 's' },
  { key: 'dashboard_render_seconds', label: 'Dashboard Render', icon: Monitor, unit: 's' },
  { key: 'screenshot_seconds', label: 'Screenshot Time', icon: Camera, unit: 's' },
  { key: 'total_execution_seconds', label: 'Total Execution', icon: Activity, unit: 's' },
  { key: 'total_requests', label: 'Total Requests', icon: BarChart3 },
  { key: 'failed_requests', label: 'Failed Requests', icon: AlertTriangle, alert: true },
  { key: 'console_messages', label: 'Console Messages', icon: Search },
  { key: 'page_errors', label: 'Page Errors', icon: AlertCircle, alert: true },
];

function DashboardCard({ metric, index }) {
  const isSource = index === 0;
  const stripeClass = isSource ? 'dv-stripe-source' : 'dv-stripe-target';
  const tagStyle = isSource
    ? { background: 'var(--surface-alt)', color: 'var(--text-muted)', border: '1px solid var(--border)' }
    : { background: 'var(--accent-bg)', color: 'var(--accent-text)' };

  return (
    <div className={`dv-surface ${stripeClass} rounded-3xl overflow-hidden transition-colors duration-500`}>
      {metric ? (
        <>
          <div className="flex items-center gap-3 p-6 pb-4 border-b" style={{ borderColor: 'var(--border)' }}>
            <div className="p-2 rounded-lg" style={{ background: 'var(--surface-alt)' }}>
              <Monitor className="w-5 h-5" style={{ color: isSource ? 'var(--text)' : 'var(--accent-text)' }} />
            </div>
            <div className="min-w-0">
              <div className="flex items-center gap-2">
                <span className="dv-font-mono text-[10px] font-bold px-1.5 py-0.5 rounded" style={tagStyle}>
                  {isSource ? 'SOURCE' : 'TARGET'}
                </span>
                <h3 className="dv-font-display font-semibold leading-tight truncate" style={{ color: 'var(--text)' }}>
                  {metric.dashboard_name || `Dashboard ${index + 1}`}
                </h3>
              </div>
              <p className="text-xs mt-1 truncate" style={{ color: 'var(--text-muted)' }} title={metric.page_title}>
                {metric.page_title}
              </p>
            </div>
          </div>

          <div className="px-2 py-2">
            {METRIC_ROWS.map((row) => {
              const value = metric[row.key];
              const isAlert = row.alert && Number(value) > 0;
              const Icon = row.icon;
              return (
                <div
                  key={row.key}
                  className="dv-row flex items-center justify-between gap-4 px-4 py-2.5 rounded-xl transition-colors duration-150"
                >
                  <div className="flex items-center gap-2.5 min-w-0">
                    <Icon
                      className="w-4 h-4 flex-shrink-0"
                      style={{ color: isAlert ? 'var(--danger)' : 'var(--text-muted)' }}
                    />
                    <span className="text-sm truncate" style={{ color: 'var(--text-muted)' }}>
                      {row.label}
                    </span>
                  </div>
                  <span
                    className="dv-font-mono text-sm font-semibold whitespace-nowrap"
                    style={{ color: isAlert ? 'var(--danger)' : 'var(--text)' }}
                  >
                    {value ?? '—'}
                    {row.unit && value != null ? <span className="opacity-60 ml-0.5">{row.unit}</span> : null}
                  </span>
                </div>
              );
            })}
          </div>
        </>
      ) : (
        <div
          className="h-full flex flex-col items-center justify-center p-10 text-center rounded-3xl"
          style={{ background: 'var(--danger-bg)', border: '1px solid var(--danger-border)' }}
        >
          <AlertTriangle className="w-10 h-10 mb-4 opacity-80" style={{ color: 'var(--danger)' }} />
          <h3 className="dv-font-display font-semibold mb-1" style={{ color: 'var(--danger)' }}>
            Validation Failed
          </h3>
          <p className="text-sm" style={{ color: 'var(--danger)', opacity: 0.85 }}>
            Dashboard {index + 1} failed to run. Check the backend logs for details.
          </p>
        </div>
      )}
    </div>
  );
}

function MetricsSection({ metrics }) {
  const safeMetrics = Array.isArray(metrics) ? metrics : [];
  if (safeMetrics.length === 0) return null;

  return (
    <div className="space-y-6 animate-in fade-in slide-in-from-bottom-8 duration-700 delay-100 fill-mode-both">
      <div className="flex items-center gap-2 mb-6">
        <BarChart3 className="w-5 h-5" style={{ color: 'var(--accent-text)' }} />
        <h2 className="dv-font-display text-xl font-bold" style={{ color: 'var(--text)' }}>
          Performance Metrics
        </h2>
      </div>

      <div className="grid lg:grid-cols-2 gap-6 relative">
        {safeMetrics.map((m, i) => (
          <DashboardCard key={i} metric={m} index={i} />
        ))}
        {safeMetrics.length === 2 && (
          <div
            className="hidden lg:flex absolute left-1/2 top-16 -translate-x-1/2 items-center justify-center w-9 h-9 rounded-full z-10"
            style={{ background: 'var(--accent)', border: '1px solid var(--accent-border)', boxShadow: 'var(--shadow-md)' }}
          >
            <ArrowLeftRight className="w-4 h-4" style={{ color: '#0A0A0A' }} />
          </div>
        )}
      </div>
    </div>
  );
}

function StatusBadge({ status }) {
  const isMatch = status === 'Match';
  const isNearMatch = status === 'Near Match';

  const style = isMatch
    ? { background: 'var(--success-bg)', color: 'var(--success)', border: '1px solid var(--success-border)' }
    : isNearMatch
    ? { background: 'var(--accent-bg)', color: 'var(--accent-text)', border: '1px solid var(--accent-border)' }
    : { background: 'var(--danger-bg)', color: 'var(--danger)', border: '1px solid var(--danger-border)' };

  return (
    <div className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-semibold" style={style}>
      {isMatch ? <CheckCircle2 className="w-3.5 h-3.5" /> : isNearMatch ? <AlertTriangle className="w-3.5 h-3.5" /> : <AlertCircle className="w-3.5 h-3.5" />}
      {status}
    </div>
  );
}

function MatchRing({ percentage }) {
  return (
    <div className="flex-shrink-0 relative flex items-center justify-center w-32 h-32">
      <svg className="w-full h-full -rotate-90" viewBox="0 0 36 36">
        <path
          strokeWidth="3"
          stroke="var(--border)"
          fill="none"
          d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831"
        />
        <path
          className="transition-all duration-1000 ease-out"
          strokeDasharray={`${percentage}, 100`}
          strokeWidth="3"
          strokeLinecap="round"
          stroke="var(--accent)"
          fill="none"
          d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831"
        />
      </svg>
      <div className="absolute flex flex-col items-center justify-center">
        <span className="dv-font-mono text-2xl font-bold" style={{ color: 'var(--text)' }}>
          {percentage}%
        </span>
        <span className="text-[10px] uppercase font-bold tracking-wider" style={{ color: 'var(--text-muted)' }}>
          Match
        </span>
      </div>
    </div>
  );
}

function ComparisonSection({ mismatches }) {
  if (!mismatches) return null;

  const results = Array.isArray(mismatches?.results) ? mismatches.results : [];
  const filters = Array.isArray(mismatches?.filters) ? mismatches.filters : [];
  const tableCells = Array.isArray(mismatches?.table_cells) ? mismatches.table_cells : [];
  const summary = mismatches?.summary || {};
  const totalMismatches = summary.total_mismatches ?? results.length;
  const matchPercentage = mismatches?.match_percentage ?? summary.overall_match_percentage ?? 0;

  const hasAny =
    results.length > 0 ||
    filters.length > 0 ||
    tableCells.length > 0 ||
    (mismatches?.page_mismatches?.length ?? 0) > 0;

  return (
    <div className="space-y-8 animate-in fade-in slide-in-from-bottom-8 duration-700 delay-200 fill-mode-both">
      <div className="dv-surface flex flex-col md:flex-row gap-6 items-center p-6 rounded-3xl">
        <MatchRing percentage={matchPercentage} />
        <div>
          <h2 className="dv-font-display text-xl font-bold mb-2 flex items-center gap-2" style={{ color: 'var(--text)' }}>
            <ShieldCheck className="w-5 h-5" style={{ color: 'var(--accent-text)' }} />
            Mismatches Only
          </h2>
          <p className="text-sm leading-relaxed max-w-2xl" style={{ color: 'var(--text-muted)' }}>
            Showing {totalMismatches} mismatch(es) across KPIs, filters, and table cells.
            Matching rows are hidden. Download the Excel report for the full comparison.
          </p>
        </div>
      </div>

      {!hasAny && (
        <div className="dv-surface p-8 rounded-3xl text-center" style={{ color: 'var(--success)' }}>
          <CheckCircle2 className="w-8 h-8 mx-auto mb-3" />
          <p className="font-semibold">No mismatches detected between source and target.</p>
        </div>
      )}

      {results.length > 0 && (
        <div className="dv-surface rounded-3xl overflow-hidden">
          <div className="px-5 py-4 font-semibold" style={{ background: '#0A0A0A', color: 'white' }}>
            KPI Mismatches ({results.length})
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-sm text-left">
              <thead style={{ background: 'var(--surface-alt)' }}>
                <tr>
                  <th className="p-5 font-semibold">KPI / Metric Name</th>
                  <th className="p-5 font-semibold">Source</th>
                  <th className="p-5 font-semibold">Target</th>
                  <th className="p-5 font-semibold">Status</th>
                </tr>
              </thead>
              <tbody>
                {results.map((r, i) => (
                  <tr
                    key={i}
                    className="dv-row dv-diff-row-mismatch transition-colors duration-150"
                    style={{ borderTop: '1px solid var(--border)' }}
                  >
                    <td className="p-5 font-medium" style={{ color: 'var(--text)' }}>{r.kpi}</td>
                    <td className="p-5 dv-font-mono" style={{ color: 'var(--text-muted)' }}>{r.source ?? '—'}</td>
                    <td className="p-5 dv-font-mono" style={{ color: 'var(--text-muted)' }}>{r.target ?? '—'}</td>
                    <td className="p-5"><StatusBadge status={r.status} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {filters.length > 0 && (
        <div className="dv-surface rounded-3xl overflow-hidden">
          <div className="px-5 py-4 font-semibold" style={{ background: '#0A0A0A', color: 'white' }}>
            Filter Mismatches ({filters.length})
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-sm text-left">
              <thead style={{ background: 'var(--surface-alt)' }}>
                <tr>
                  <th className="p-5 font-semibold">Filter</th>
                  <th className="p-5 font-semibold">Source Selected</th>
                  <th className="p-5 font-semibold">Target Selected</th>
                  <th className="p-5 font-semibold">Status</th>
                </tr>
              </thead>
              <tbody>
                {filters.map((f, i) => (
                  <tr key={i} className="dv-row dv-diff-row-mismatch" style={{ borderTop: '1px solid var(--border)' }}>
                    <td className="p-5 font-medium">{f.filter_name}</td>
                    <td className="p-5 dv-font-mono text-xs">{(f.source_selected || []).join(', ') || '—'}</td>
                    <td className="p-5 dv-font-mono text-xs">{(f.target_selected || []).join(', ') || '—'}</td>
                    <td className="p-5"><StatusBadge status={f.status} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {tableCells.length > 0 && (
        <div className="dv-surface rounded-3xl overflow-hidden">
          <div className="px-5 py-4 font-semibold" style={{ background: '#0A0A0A', color: 'white' }}>
            Table Cell Mismatches ({tableCells.length})
          </div>
          <div className="overflow-x-auto max-h-96">
            <table className="w-full text-sm text-left">
              <thead style={{ background: 'var(--surface-alt)' }}>
                <tr>
                  <th className="p-4 font-semibold">Visual</th>
                  <th className="p-4 font-semibold">Row</th>
                  <th className="p-4 font-semibold">Column</th>
                  <th className="p-4 font-semibold">Source</th>
                  <th className="p-4 font-semibold">Target</th>
                  <th className="p-4 font-semibold">Status</th>
                </tr>
              </thead>
              <tbody>
                {tableCells.map((c, i) => (
                  <tr key={i} className="dv-row dv-diff-row-mismatch" style={{ borderTop: '1px solid var(--border)' }}>
                    <td className="p-4">{c.visual}</td>
                    <td className="p-4 dv-font-mono">{c.row_number}</td>
                    <td className="p-4">{c.column}</td>
                    <td className="p-4 dv-font-mono">{c.source_value ?? '—'}</td>
                    <td className="p-4 dv-font-mono">{c.target_value ?? '—'}</td>
                    <td className="p-4"><StatusBadge status={c.status} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Reports panel — wired to GET /api/reports/{run_id}, .../excel,     */
/*  .../docx. Polls until both files are ready, then links straight    */
/*  to the download endpoints.                                         */
/* ------------------------------------------------------------------ */

function ReportButton({ label, icon: Icon, ready, href, checking }) {
  if (ready && href) {
    return (
      <a
        href={href}
        target="_blank"
        rel="noreferrer"
        className="dv-btn-outline inline-flex items-center gap-2 px-5 py-3 rounded-xl text-sm font-semibold transition-all duration-200"
      >
        <Icon className="w-4 h-4" style={{ color: 'var(--accent-text)' }} />
        <span>{label}</span>
        <Download className="w-4 h-4 ml-1" />
      </a>
    );
  }
  return (
    <button
      type="button"
      disabled
      className="dv-btn-outline inline-flex items-center gap-2 px-5 py-3 rounded-xl text-sm font-semibold"
    >
      {checking ? <Loader2 className="w-4 h-4 animate-spin" /> : <Icon className="w-4 h-4" style={{ color: 'var(--text-muted)' }} />}
      <span style={{ color: 'var(--text-muted)' }}>{checking ? 'Generating…' : `${label} unavailable`}</span>
    </button>
  );
}

function ReportsPanel({ runId, reportStatus, polling }) {
  const excelHref = reportStatus?.excel_ready ? `${BASE_URL}${reportStatus.excel_download_url}` : null;
  const docxHref = reportStatus?.docx_ready ? `${BASE_URL}${reportStatus.docx_download_url}` : null;

  return (
    <div className="dv-surface p-6 rounded-3xl flex flex-col sm:flex-row sm:items-center gap-5 sm:gap-8 animate-in fade-in slide-in-from-bottom-4 duration-500">
      <div className="flex-1 min-w-0">
        <h3 className="dv-font-display text-base font-bold mb-1" style={{ color: 'var(--text)' }}>
          Validation Reports
        </h3>
        <p className="text-sm mb-1" style={{ color: 'var(--text-muted)' }}>
          {polling ? 'Generating downloadable Excel and Word reports for this run…' : 'Reports for this run are ready to download.'}
        </p>
        <p className="dv-font-mono text-[11px]" style={{ color: 'var(--text-muted)', opacity: 0.7 }}>
          run_id: {runId}
        </p>
      </div>
      <div className="flex gap-3 flex-shrink-0">
        <ReportButton label="Excel Report" icon={FileSpreadsheet} ready={reportStatus?.excel_ready} href={excelHref} checking={polling} />
        <ReportButton label="Word Report" icon={FileText} ready={reportStatus?.docx_ready} href={docxHref} checking={polling} />
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Main App                                                          */
/* ------------------------------------------------------------------ */

function App() {
  const [sourceUrl, setSourceUrl] = useState('');
  const [targetUrl, setTargetUrl] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [result, setResult] = useState(null);
  const [apiStatus, setApiStatus] = useState('checking'); // 'checking' | 'online' | 'offline'
  const [reportStatus, setReportStatus] = useState(null);
  const [reportPolling, setReportPolling] = useState(false);
  const [theme, setTheme] = useState(() => {
    if (typeof window === 'undefined') return 'light';
    const saved = window.localStorage.getItem('dv-theme');
    if (saved) return saved;
    return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
  });

  const pollTimeoutRef = useRef(null);

  useEffect(() => {
    window.localStorage.setItem('dv-theme', theme);
  }, [theme]);

  // GET /api/health — surfaced as the status dot in the top bar.
  useEffect(() => {
    let cancelled = false;
    fetch(`${BASE_URL}/api/health`)
      .then((res) => {
        if (!cancelled) setApiStatus(res.ok ? 'online' : 'offline');
      })
      .catch(() => {
        if (!cancelled) setApiStatus('offline');
      });
    return () => {
      cancelled = true;
    };
  }, []);

  // GET /api/reports/{run_id} — poll until both files are ready (or give up).
  useEffect(() => {
    if (pollTimeoutRef.current) {
      clearTimeout(pollTimeoutRef.current);
      pollTimeoutRef.current = null;
    }

    const runId = result?.run_id;
    if (!runId) {
      setReportStatus(null);
      setReportPolling(false);
      return;
    }

    let cancelled = false;
    let attempts = 0;
    const maxAttempts = 20; // ~60s at 3s intervals
    setReportPolling(true);
    setReportStatus(null);

    const poll = async () => {
      try {
        const res = await fetch(`${BASE_URL}/api/reports/${runId}`);
        if (!res.ok) throw new Error('report status check failed');
        const data = await res.json();
        if (cancelled) return;

        setReportStatus(data);
        attempts += 1;

        if ((data.excel_ready && data.docx_ready) || attempts >= maxAttempts) {
          setReportPolling(false);
          return;
        }
        pollTimeoutRef.current = setTimeout(poll, 3000);
      } catch {
        if (!cancelled) setReportPolling(false);
      }
    };

    poll();

    return () => {
      cancelled = true;
      if (pollTimeoutRef.current) clearTimeout(pollTimeoutRef.current);
    };
  }, [result?.run_id]);

  // GET /api/reports/{run_id}/mismatches — fallback when validate response omits mismatches.
  useEffect(() => {
    const runId = result?.run_id;
    if (!runId || result?.mismatches) return;

    let cancelled = false;
    fetch(`${BASE_URL}/api/reports/${runId}/mismatches`)
      .then((res) => (res.ok ? res.json() : null))
      .then((data) => {
        if (!cancelled && data) {
          setResult((prev) => (prev ? { ...prev, mismatches: data } : prev));
        }
      })
      .catch(() => {});

    return () => {
      cancelled = true;
    };
  }, [result?.run_id, result?.mismatches]);

  const toggleTheme = () => setTheme((t) => (t === 'dark' ? 'light' : 'dark'));

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError('');
    setResult(null);

    if (!sourceUrl.trim() || !targetUrl.trim()) {
      setError('Please enter both dashboard URLs.');
      return;
    }

    setLoading(true);

    try {
      const response = await fetch(API_URL, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          source_url: sourceUrl.trim(),
          target_url: targetUrl.trim(),
        }),
      });

      if (!response.ok) {
        const errData = await response.json().catch(() => ({}));
        throw new Error(errData.detail || `Request failed with status ${response.status}`);
      }

      const data = await response.json();
      console.log('validation response:', data);
      setResult(data);
    } catch (err) {
      setError(err.message || 'Something went wrong while validating.');
    } finally {
      setLoading(false);
    }
  };

  return (
    <>
      <style>{styles}</style>
      <div className="dv-app" data-theme={theme}>
        <TopBar theme={theme} onToggleTheme={toggleTheme} apiStatus={apiStatus} />

        <div className="max-w-6xl mx-auto px-4 sm:px-8 pb-16">
          <Hero />

          <div className="max-w-4xl mx-auto">
            <ValidationForm
              sourceUrl={sourceUrl}
              setSourceUrl={setSourceUrl}
              targetUrl={targetUrl}
              setTargetUrl={setTargetUrl}
              handleSubmit={handleSubmit}
              loading={loading}
            />
          </div>

          {error && (
            <div className="max-w-4xl mx-auto mt-6 animate-in fade-in slide-in-from-top-2 duration-300">
              <div
                className="flex items-center gap-3 p-4 rounded-2xl"
                style={{ background: 'var(--danger-bg)', border: '1px solid var(--danger-border)' }}
              >
                <AlertTriangle className="w-5 h-5 flex-shrink-0" style={{ color: 'var(--danger)' }} />
                <p className="font-medium text-sm" style={{ color: 'var(--danger)' }}>
                  {error}
                </p>
              </div>
            </div>
          )}

          {result && (
            <div className="mt-12 space-y-12">
              <MetricsSection metrics={result.metrics} />
              {result.mismatches && <ComparisonSection mismatches={result.mismatches} />}
              {result.run_id && (
                <ReportsPanel runId={result.run_id} reportStatus={reportStatus} polling={reportPolling} />
              )}
            </div>
          )}
        </div>
      </div>
    </>
  );
}

export default App;

// #changes