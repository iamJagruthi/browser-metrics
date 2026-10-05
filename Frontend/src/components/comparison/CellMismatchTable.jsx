function formatRowIdentifier(rowIdentifier) {
  if (!rowIdentifier || typeof rowIdentifier !== 'object') return String(rowIdentifier ?? '—');
  return Object.entries(rowIdentifier)
    .map(([k, v]) => `${k}: ${v}`)
    .join(', ');
}

export function CellMismatchTable({ cellMismatches }) {
  if (!cellMismatches || cellMismatches.length === 0) return null;

  return (
    <div className="overflow-x-auto rounded-xl border" style={{ borderColor: 'var(--border)' }}>
      <table className="w-full text-sm text-left">
        <thead style={{ background: 'var(--surface-alt)' }}>
          <tr>
            <th className="p-3 font-semibold">Row</th>
            <th className="p-3 font-semibold">Column</th>
            <th className="p-3 font-semibold">Source Value</th>
            <th className="p-3 font-semibold">Target Value</th>
          </tr>
        </thead>
        <tbody>
          {cellMismatches.map((cell, idx) => (
            <tr key={idx} className="dv-row dv-diff-row-mismatch" style={{ borderTop: '1px solid var(--border)' }}>
              <td className="p-3 dv-font-mono text-xs" style={{ color: 'var(--text-muted)' }}>
                {formatRowIdentifier(cell.row_identifier)}
              </td>
              <td className="p-3 font-medium">{cell.column}</td>
              <td className="p-3 dv-font-mono text-xs">{cell.source_value ?? '—'}</td>
              <td className="p-3 dv-font-mono text-xs">{cell.target_value ?? '—'}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}