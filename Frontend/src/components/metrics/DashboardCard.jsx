import { AlertTriangle, Monitor } from 'lucide-react';
import { METRIC_ROWS } from '../../constants/metricRows';

function MetricRow({ row, value }) {
  const isAlert = row.alert && Number(value) > 0;
  const Icon = row.icon;

  return (
    <div className="dv-row flex items-center justify-between gap-4 px-4 py-2.5 rounded-xl transition-colors duration-150">
      <div className="flex items-center gap-2.5 min-w-0">
        <Icon className="w-4 h-4 flex-shrink-0" style={{ color: isAlert ? 'var(--danger)' : 'var(--text-muted)' }} />
        <span className="text-sm truncate" style={{ color: 'var(--text-muted)' }}>
          {row.label}
        </span>
      </div>
      <span className="dv-font-mono text-sm font-semibold whitespace-nowrap" style={{ color: isAlert ? 'var(--danger)' : 'var(--text)' }}>
        {value ?? '—'}
        {row.unit && value != null ? <span className="opacity-60 ml-0.5">{row.unit}</span> : null}
      </span>
    </div>
  );
}

function FailedCard({ index }) {
  return (
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
  );
}

export function DashboardCard({ metric, index }) {
  const isSource = index === 0;
  const stripeClass = isSource ? 'dv-stripe-source' : 'dv-stripe-target';
  const tagStyle = isSource
    ? { background: 'var(--surface-alt)', color: 'var(--text-muted)', border: '1px solid var(--border)' }
    : { background: 'var(--accent-bg)', color: 'var(--accent-text)' };

  if (!metric) {
    return (
      <div className={`dv-surface ${stripeClass} rounded-3xl overflow-hidden transition-colors duration-500`}>
        <FailedCard index={index} />
      </div>
    );
  }

  return (
    <div className={`dv-surface ${stripeClass} rounded-3xl overflow-hidden transition-colors duration-500`}>
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
        {METRIC_ROWS.map((row) => (
          <MetricRow key={row.key} row={row} value={metric[row.key]} />
        ))}
      </div>
    </div>
  );
}
