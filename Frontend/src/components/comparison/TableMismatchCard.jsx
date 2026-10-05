import { CellMismatchTable } from './CellMismatchTable.jsx';

export function TableMismatchCard({ tableName, cellMismatches }) {
  if (!cellMismatches || cellMismatches.length === 0) return null;

  return (
    <div className="dv-surface rounded-3xl overflow-hidden mb-6 border" style={{ borderColor: 'var(--border)' }}>
      <div
        className="px-6 py-4 flex items-center justify-between gap-3"
        style={{ background: '#0A0A0A', color: 'white' }}
      >
        <span className="dv-font-display font-bold text-lg">{tableName}</span>
        <span className="text-xs text-white/60 font-mono">
          {cellMismatches.length} cell mismatch(es)
        </span>
      </div>

      <div className="p-6">
        <CellMismatchTable cellMismatches={cellMismatches} />
      </div>
    </div>
  );
}