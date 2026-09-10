import { KpiMismatchTable } from './KpiMismatchTable';
import { FilterMismatchTable } from './FilterMismatchTable';

export function PageMismatchCard({ pageMismatch }) {
  const { page_name, filter_applied, kpis, filters, visuals } = pageMismatch;
  const mismatchCount = (kpis?.length || 0) + (filters?.length || 0) + (visuals?.length || 0);

  return (
    <div className="dv-surface rounded-3xl overflow-hidden mb-8 border" style={{ borderColor: 'var(--border)' }}>
      <div
        className="px-6 py-4 flex flex-wrap items-center justify-between gap-3"
        style={{ background: '#0A0A0A', color: 'white' }}
      >
        <div className="flex items-center gap-3">
          <span className="dv-font-display font-bold text-lg">{page_name}</span>
          <span className="text-xs px-2.5 py-1 rounded-full font-mono bg-white/10 text-white/80 border border-white/20">
            Filter: {filter_applied || 'Default State'}
          </span>
        </div>
        <span className="text-xs text-white/60 font-mono">{mismatchCount} Mismatch(es)</span>
      </div>

      <div className="p-6 space-y-6">
        <KpiMismatchTable kpis={kpis} />
        <FilterMismatchTable filters={filters} />
      </div>
    </div>
  );
}
