import { AlertTriangle } from 'lucide-react';
import { StatusBadge } from './StatusBadge';

export function FilterMismatchTable({ filters }) {
  if (!filters || filters.length === 0) return null;

  return (
    <div>
      <h4 className="text-sm font-semibold mb-3 flex items-center gap-2" style={{ color: 'var(--text)' }}>
        <AlertTriangle className="w-4 h-4 text-yellow-500" />
        Slicer / Filter Mismatches ({filters.length})
      </h4>
      <div className="overflow-x-auto rounded-xl border" style={{ borderColor: 'var(--border)' }}>
        <table className="w-full text-sm text-left">
          <thead style={{ background: 'var(--surface-alt)' }}>
            <tr>
              <th className="p-3 font-semibold">Filter Name</th>
              <th className="p-3 font-semibold">Source Selection</th>
              <th className="p-3 font-semibold">Target Selection</th>
              <th className="p-3 font-semibold">Status</th>
            </tr>
          </thead>
          <tbody>
            {filters.map((item, idx) => (
              <tr key={idx} className="dv-row dv-diff-row-mismatch" style={{ borderTop: '1px solid var(--border)' }}>
                <td className="p-3 font-medium">{item.filter_name}</td>
                <td className="p-3 dv-font-mono text-xs">{(item.source_selected || []).join(', ') || '—'}</td>
                <td className="p-3 dv-font-mono text-xs">{(item.target_selected || []).join(', ') || '—'}</td>
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
