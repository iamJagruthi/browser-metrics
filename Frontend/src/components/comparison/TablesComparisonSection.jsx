import { Database, AlertCircle, CheckCircle2 } from 'lucide-react';
import { TableMismatchCard } from './TableMismatchCard.jsx';

export function TablesComparisonSection({ tables }) {
  if (!tables) return null;

  const {
    source_table_count = 0,
    target_table_count = 0,
    paired_table_count = 0,
    compared_table_count = 0,
    match_count = 0,
    comparisons = [],
  } = tables;

  const totalCellMismatches = comparisons.reduce(
    (sum, c) => sum + (c.cell_mismatches?.length || 0),
    0
  );

  const stats = [
    { label: 'Source Tables', value: source_table_count },
    { label: 'Target Tables', value: target_table_count },
    { label: 'Paired', value: paired_table_count },
    { label: 'Compared', value: compared_table_count },
    { label: 'Matched', value: match_count },
  ];

  return (
    <div className="space-y-6 animate-in fade-in slide-in-from-bottom-8 duration-700 delay-200 fill-mode-both">
      <div className="flex items-center gap-2 mb-2">
        <Database className="w-5 h-5" style={{ color: 'var(--accent-text)' }} />
        <h2 className="dv-font-display text-xl font-bold" style={{ color: 'var(--text)' }}>
          Table Data Comparison
        </h2>
      </div>

      <div className="dv-surface rounded-3xl p-6 grid grid-cols-2 sm:grid-cols-5 gap-4">
        {stats.map((s) => (
          <div key={s.label} className="text-center">
            <div className="dv-font-mono text-2xl font-bold" style={{ color: 'var(--text)' }}>
              {s.value}
            </div>
            <div className="text-xs uppercase font-bold tracking-wider mt-1" style={{ color: 'var(--text-muted)' }}>
              {s.label}
            </div>
          </div>
        ))}
      </div>

      {totalCellMismatches === 0 ? (
        <div className="dv-surface p-8 rounded-3xl text-center" style={{ color: 'var(--success)' }}>
          <CheckCircle2 className="w-8 h-8 mx-auto mb-3" />
          <p className="font-semibold">All compared table cells matched perfectly!</p>
        </div>
      ) : (
        <div className="flex items-center gap-2 text-sm" style={{ color: 'var(--text-muted)' }}>
          <AlertCircle className="w-4 h-4" style={{ color: 'var(--danger)' }} />
          {totalCellMismatches} cell mismatch(es) found across {comparisons.length} table(s).
        </div>
      )}

      {comparisons.map((tableComparison, idx) => (
        <TableMismatchCard
          key={tableComparison.table_name || idx}
          tableName={tableComparison.table_name || `Table ${idx + 1}`}
          cellMismatches={tableComparison.cell_mismatches || []}
        />
      ))}
    </div>
  );
}