import { AlertCircle, Table2, Timer, ListChecks } from 'lucide-react';
import { StatusBadge } from './StatusBadge';

const statChip = (label, count, danger) => (
  <span
    style={{
      display: 'inline-flex',
      alignItems: 'center',
      gap: '0.35rem',
      padding: '0.2rem 0.55rem',
      borderRadius: '9999px',
      fontSize: '0.7rem',
      fontWeight: 600,
      background: danger ? 'var(--danger-bg)' : 'var(--surface-alt)',
      color: danger ? 'var(--danger)' : 'var(--text-muted)',
      border: '1px solid var(--border)',
    }}
  >
    {label} <b>{count}</b>
  </span>
);

const toList = (value) => {
  if (value == null) return '';
  if (Array.isArray(value)) return value.length ? value.join(', ') : '';
  return String(value);
};

const pickSource = (item) => item?.source_value ?? item?.source ?? toList(item?.source_selected);
const pickTarget = (item) => item?.target_value ?? item?.target ?? toList(item?.target_selected);
const pickName = (item) => item?.kpi || item?.filter_name || item?.visual_name || item?.title || item?.name || 'Unnamed';

function TableVisualMismatchCard({ item }) {
  return (
    <div className="dv-surface rounded-2xl p-4 border" style={{ borderColor: 'var(--border)' }}>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <Table2 className="w-4 h-4" style={{ color: 'var(--danger)' }} />
          <span className="text-sm font-semibold" style={{ color: 'var(--text)' }}>
            {item.table_title || 'Unnamed table'}
          </span>
        </div>
        <StatusBadge status={item.status} />
      </div>
      <div className="flex gap-3 flex-wrap mt-3" style={{ fontSize: '0.72rem', color: 'var(--text-muted)' }}>
        <span>
          Source rows: <b style={{ color: 'var(--text)' }}>{item.source_row_count ?? '—'}</b>
        </span>
        <span>
          Target rows: <b style={{ color: 'var(--text)' }}>{item.target_row_count ?? '—'}</b>
        </span>
        {item.missing_rows_in_target_count != null && (
          <span>
            Missing in target: <b style={{ color: 'var(--text)' }}>{item.missing_rows_in_target_count}</b>
          </span>
        )}
        {item.extra_rows_in_target_count != null && (
          <span>
            Extra in target: <b style={{ color: 'var(--text)' }}>{item.extra_rows_in_target_count}</b>
          </span>
        )}
      </div>
      {((Array.isArray(item.missing_columns_in_target) && item.missing_columns_in_target.length) ||
        (Array.isArray(item.extra_columns_in_target) && item.extra_columns_in_target.length)) && (
        <div className="mt-2" style={{ fontSize: '0.72rem', color: 'var(--text-muted)' }}>
          {Array.isArray(item.missing_columns_in_target) && item.missing_columns_in_target.length > 0 && (
            <div>
              Missing columns in target: {toList(item.missing_columns_in_target)}
            </div>
          )}
          {Array.isArray(item.extra_columns_in_target) && item.extra_columns_in_target.length > 0 && (
            <div>
              Extra columns in target: {toList(item.extra_columns_in_target)}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function BrowserMetricMismatchTable({ items }) {
  if (!items || items.length === 0) return null;
  return (
    <div className="overflow-x-auto rounded-xl border" style={{ borderColor: 'var(--border)' }}>
      <table className="w-full text-sm text-left">
        <thead style={{ background: 'var(--surface-alt)' }}>
          <tr>
            <th className="p-3 font-semibold">Metric</th>
            <th className="p-3 font-semibold">Page</th>
            <th className="p-3 font-semibold">Source</th>
            <th className="p-3 font-semibold">Target</th>
          </tr>
        </thead>
        <tbody>
          {items.map((item, idx) => (
            <tr key={idx} className="dv-row dv-diff-row-mismatch" style={{ borderTop: '1px solid var(--border)' }}>
              <td className="p-3 font-medium">{item.metric}</td>
              <td className="p-3">{item.page_name || '—'}</td>
              <td className="p-3 dv-font-mono">{item.source ?? '—'}</td>
              <td className="p-3 dv-font-mono">{item.target ?? '—'}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function GenericMismatchList({ title, icon: Icon, items, sourceOf, targetOf }) {
  if (!items || items.length === 0) return null;
  return (
    <div>
      <h4 className="text-sm font-semibold mb-3 flex items-center gap-2" style={{ color: 'var(--text)' }}>
        <Icon className="w-4 h-4 text-red-500" />
        {title} ({items.length})
      </h4>
      <div className="overflow-x-auto rounded-xl border" style={{ borderColor: 'var(--border)' }}>
        <table className="w-full text-sm text-left">
          <thead style={{ background: 'var(--surface-alt)' }}>
            <tr>
              <th className="p-3 font-semibold">Name</th>
              <th className="p-3 font-semibold">Source</th>
              <th className="p-3 font-semibold">Target</th>
              <th className="p-3 font-semibold">Status</th>
            </tr>
          </thead>
          <tbody>
            {items.map((item, idx) => (
              <tr key={idx} className="dv-row dv-diff-row-mismatch" style={{ borderTop: '1px solid var(--border)' }}>
                <td className="p-3 font-medium">{pickName(item)}</td>
                <td className="p-3 dv-font-mono">{sourceOf(item) || '—'}</td>
                <td className="p-3 dv-font-mono">{targetOf(item) || '—'}</td>
                <td className="p-3">
                  <StatusBadge status={item.status} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export function MismatchResultsSection({ mismatches }) {
  if (!mismatches) return null;

  const summary = mismatches.summary || {};
  const total = summary.total_mismatches ?? 0;
  const tableVisuals = mismatches.table_visuals || [];
  const tableCells = mismatches.table_cells || [];
  const browserMetrics = mismatches.browser_metrics || [];
  const kpis = mismatches.kpis || mismatches.results || [];
  const filters = mismatches.filters || [];
  const visuals = mismatches.visuals || [];

  return (
    <div className="dv-surface rounded-3xl p-6 space-y-6 animate-in fade-in slide-in-from-bottom-8 duration-500 fill-mode-both">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div className="flex items-center gap-2">
          <AlertCircle className="w-5 h-5" style={{ color: 'var(--danger)' }} />
          <h2 className="dv-font-display text-xl font-bold" style={{ color: 'var(--text)' }}>
            Comparison Mismatch Details
          </h2>
        </div>
        <div
          className="flex items-center gap-2 px-4 py-2 rounded-full"
          style={{ background: 'var(--danger-bg)', color: 'var(--danger)', border: '1px solid var(--danger-border)' }}
        >
          <span className="text-xs font-bold uppercase tracking-wider">Total mismatches</span>
          <b className="dv-font-display text-lg">{total}</b>
        </div>
      </div>

      <div className="flex gap-2 flex-wrap">
        {statChip('Table visual mismatches', summary.table_visual_mismatch_count ?? tableVisuals.length, (summary.table_visual_mismatch_count ?? tableVisuals.length) > 0)}
        {statChip('Table cell mismatches', summary.table_cell_mismatch_count ?? tableCells.length, (summary.table_cell_mismatch_count ?? tableCells.length) > 0)}
        {statChip('Browser metric mismatches', summary.browser_metric_mismatch_count ?? browserMetrics.length, (summary.browser_metric_mismatch_count ?? browserMetrics.length) > 0)}
        {statChip('Filter mismatches', summary.filter_mismatch_count ?? 0, (summary.filter_mismatch_count ?? 0) > 0)}
        {statChip('KPI mismatches', summary.kpi_mismatch_count ?? 0, (summary.kpi_mismatch_count ?? 0) > 0)}
        {statChip('Visual mismatches', summary.visual_mismatch_count ?? 0, (summary.visual_mismatch_count ?? 0) > 0)}
      </div>

      {total === 0 ? (
        <p className="text-sm" style={{ color: 'var(--success)' }}>
          No mismatches detected — source and target match on every checked item.
        </p>
      ) : (
        <div className="space-y-6">
          {tableVisuals.length > 0 && (
            <div className="space-y-3">
              <h3
                className="text-sm font-semibold flex items-center gap-2"
                style={{ color: 'var(--danger)' }}
              >
                <Table2 className="w-4 h-4" />
                Table Visual Mismatches ({tableVisuals.length})
              </h3>
              {tableVisuals.map((item, idx) => (
                <TableVisualMismatchCard key={idx} item={item} />
              ))}
            </div>
          )}

          {tableCells.length > 0 && (
            <div>
              <h3
                className="text-sm font-semibold mb-3 flex items-center gap-2"
                style={{ color: 'var(--danger)' }}
              >
                <ListChecks className="w-4 h-4" />
                Table Cell Mismatches ({tableCells.length})
              </h3>
              <div className="overflow-x-auto rounded-xl border" style={{ borderColor: 'var(--border)' }}>
                <table className="w-full text-sm text-left">
                  <thead style={{ background: 'var(--surface-alt)' }}>
                    <tr>
                      <th className="p-3 font-semibold">Table</th>
                      <th className="p-3 font-semibold">Row</th>
                      <th className="p-3 font-semibold">Column</th>
                      <th className="p-3 font-semibold">Source</th>
                      <th className="p-3 font-semibold">Target</th>
                      <th className="p-3 font-semibold">Status</th>
                    </tr>
                  </thead>
                  <tbody>
                    {tableCells.map((item, idx) => (
                      <tr key={idx} className="dv-row dv-diff-row-mismatch" style={{ borderTop: '1px solid var(--border)' }}>
                        <td className="p-3 font-medium">{item.table_title}</td>
                        <td className="p-3 dv-font-mono text-xs">
                          {item.row_identifier ? toList(Object.values(item.row_identifier)) : '—'}
                        </td>
                        <td className="p-3">{item.column || '—'}</td>
                        <td className="p-3 dv-font-mono">{item.source_value ?? '—'}</td>
                        <td className="p-3 dv-font-mono">{item.target_value ?? '—'}</td>
                        <td className="p-3">
                          <StatusBadge status={item.status} />
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {browserMetrics.length > 0 && (
            <div>
              <h3
                className="text-sm font-semibold mb-3 flex items-center gap-2"
                style={{ color: 'var(--danger)' }}
              >
                <Timer className="w-4 h-4" />
                Browser Metric Mismatches ({browserMetrics.length})
              </h3>
              <BrowserMetricMismatchTable items={browserMetrics} />
            </div>
          )}

          <GenericMismatchList title="Filter Mismatches" icon={AlertCircle} items={filters} sourceOf={pickSource} targetOf={pickTarget} />
          <GenericMismatchList title="KPI Mismatches" icon={AlertCircle} items={kpis} sourceOf={pickSource} targetOf={pickTarget} />
          <GenericMismatchList title="Visual Mismatches" icon={AlertCircle} items={visuals} sourceOf={pickSource} targetOf={pickTarget} />
        </div>
      )}
    </div>
  );
}