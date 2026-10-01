import { Camera, Clock, Filter, Gauge } from 'lucide-react';

function PerfRow({ label, icon, value, sub }) {
  const Icon = icon;
  return (
    <div className="dv-row flex items-center justify-between gap-4 px-4 py-2.5 rounded-xl transition-colors duration-150">
      <div className="flex items-center gap-2.5 min-w-0">
        <Icon className="w-4 h-4 flex-shrink-0" style={{ color: 'var(--text-muted)' }} />
        <span className="text-sm truncate" style={{ color: 'var(--text-muted)' }}>{label}</span>
      </div>
      <div className="text-right min-w-0">
        <span className="dv-font-mono text-sm font-semibold whitespace-nowrap" style={{ color: 'var(--text)' }}>
          {value ?? '—'}
        </span>
        {sub ? (
          <p className="text-[11px] truncate" style={{ color: 'var(--text-muted)' }}>
            {sub}
          </p>
        ) : null}
      </div>
    </div>
  );
}

function formatSeconds(value) {
  if (value == null) return null;
  return `${Number(value).toFixed(2)}s`;
}

function filterTestSummary(filterTest) {
  if (!filterTest) return null;
  if (filterTest.status === 'applied') {
    const taken = filterTest.filter_dashboard_render_seconds;
    return {
      value: taken == null ? 'Applied' : `${Number(taken).toFixed(2)}s`,
      sub: filterTest.slicer ? `${filterTest.slicer}: ${filterTest.value}` : filterTest.value,
    };
  }
  if (filterTest.status === 'unavailable') {
    return {
      value: 'Not run',
      sub: filterTest.slicer ? `${filterTest.slicer} — no usable option` : 'No slicers found',
    };
  }
  return { value: filterTest.status, sub: filterTest.error || filterTest.slicer };
}

function SidePerformanceCard({ side, tagStyle, performance }) {
  const p = performance || {};
  const filter = filterTestSummary(p.filter_test);
  const isSource = side === 'source';

  return (
    <div
      className={`dv-surface rounded-3xl overflow-hidden transition-colors duration-500 ${
        isSource ? 'dv-stripe-source' : 'dv-stripe-target'
      }`}
    >
      <div
        className="flex items-center gap-3 p-6 pb-4 border-b"
        style={{ borderColor: 'var(--border)' }}
      >
        <div className="p-2 rounded-lg" style={{ background: 'var(--surface-alt)' }}>
          <Gauge className="w-5 h-5" style={{ color: isSource ? 'var(--text)' : 'var(--accent-text)' }} />
        </div>
        <span
          className="dv-font-mono text-[10px] font-bold px-1.5 py-0.5 rounded"
          style={tagStyle}
        >
          {isSource ? 'SOURCE' : 'TARGET'}
        </span>
      </div>
      <div className="px-2 py-2 space-y-1">
        <PerfRow
          label="Browser Launch"
          icon={Clock}
          value={formatSeconds(p.browser_launch_seconds)}
        />
        <PerfRow
          label="Dashboard Render"
          icon={Gauge}
          value={formatSeconds(p.dashboard_render_seconds)}
        />
        <PerfRow label="Filter Probe" icon={Filter} value={filter?.value} sub={filter?.sub} />
        <PerfRow
          label="Baseline Screenshot"
          icon={Camera}
          value={p.baseline_stable ? 'Captured' : 'Skipped (not stable)'}
        />
      </div>
    </div>
  );
}

export function PerformanceSummary({ captureStatus }) {
  const statusDoc = captureStatus || {};
  if (typeof statusDoc.status === 'undefined') return null;
  const details = statusDoc.details || {};
  if (!details.source && !details.target) return null;

  const sourceTagStyle = {
    background: 'var(--surface-alt)',
    color: 'var(--text-muted)',
    border: '1px solid var(--border)',
  };
  const targetTagStyle = { background: 'var(--accent-bg)', color: 'var(--accent-text)' };

  return (
    <div className="space-y-6 animate-in fade-in slide-in-from-bottom-8 duration-700 fill-mode-both">
      <div className="flex items-center gap-2 mb-6">
        <Gauge className="w-5 h-5" style={{ color: 'var(--accent-text)' }} />
        <h2
          className="dv-font-display text-xl font-bold"
          style={{ color: 'var(--text)' }}
        >
          Performance Metrics
        </h2>
      </div>

      <div className="grid lg:grid-cols-2 gap-6 relative">
        <SidePerformanceCard side="source" tagStyle={sourceTagStyle} performance={details.source} />
        <SidePerformanceCard side="target" tagStyle={targetTagStyle} performance={details.target} />
      </div>
    </div>
  );
}