import { KpiMismatchTable } from './KpiMismatchTable';
import { FilterMismatchTable } from './FilterMismatchTable';

export function AppliedFiltersCard({ pageName, filters, pageMismatch }) {
  const entries = Object.entries(filters || {});
  const kpis = pageMismatch?.kpis || [];
  const mismatchedFilters = pageMismatch?.filters || [];
  const mismatchCount = kpis.length + mismatchedFilters.length;

  return (
    <div className="dv-surface rounded-3xl overflow-hidden mb-6 border" style={{ borderColor: 'var(--border)' }}>
      <div
        className="px-6 py-4 flex items-center justify-between gap-3"
        style={{ background: '#0A0A0A', color: 'white' }}
      >
        <span className="dv-font-display font-bold text-lg">{pageName}</span>
        <span className="text-xs text-white/60 font-mono">
          {entries.length} filter{entries.length === 1 ? '' : 's'} applied
        </span>
      </div>

      <div className="p-6 space-y-6">
        {entries.length === 0 ? (
          <p className="text-sm" style={{ color: 'var(--text-muted)' }}>
            No filters were applied on this page — default view was used.
          </p>
        ) : (
          <div className="overflow-x-auto rounded-xl border" style={{ borderColor: 'var(--border)' }}>
            <table className="w-full text-sm text-left">
              <thead style={{ background: 'var(--surface-alt)' }}>
                <tr>
                  <th className="p-3 font-semibold">Filter Name</th>
                  <th className="p-3 font-semibold">Applied Value</th>
                </tr>
              </thead>
              <tbody>
                {entries.map(([filterName, value]) => (
                  <tr key={filterName} style={{ borderTop: '1px solid var(--border)' }}>
                    <td className="p-3 font-medium">{filterName}</td>
                    <td className="p-3 dv-font-mono">{value}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {/* Mismatches for this same page, shown right below its applied filters */}
        {pageMismatch && (
          <div className="pt-2 border-t" style={{ borderColor: 'var(--border)' }}>
            <div className="flex items-center justify-between mb-4 pt-4">
              <h4 className="text-sm font-semibold" style={{ color: 'var(--text)' }}>
                Comparison Result
              </h4>
              <span className="text-xs font-mono" style={{ color: mismatchCount === 0 ? 'var(--success)' : 'var(--danger)' }}>
                {mismatchCount === 0 ? 'No mismatches' : `${mismatchCount} mismatch(es)`}
              </span>
            </div>

            {mismatchCount === 0 ? (
              <p className="text-sm" style={{ color: 'var(--success)' }}>
                Source and target matched perfectly on this page.
              </p>
            ) : (
              <div className="space-y-6">
                <KpiMismatchTable kpis={kpis} />
                <FilterMismatchTable filters={mismatchedFilters} />
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}