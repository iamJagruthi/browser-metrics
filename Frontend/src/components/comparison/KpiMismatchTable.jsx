import { AlertCircle } from 'lucide-react';
import { StatusBadge } from './StatusBadge';

export function KpiMismatchTable({ kpis }) {
  if (!kpis || kpis.length === 0) return null;

  return (
    <div>
      <h4 className="text-sm font-semibold mb-3 flex items-center gap-2" style={{ color: 'var(--text)' }}>
        <AlertCircle className="w-4 h-4 text-red-500" />
        KPI Mismatches ({kpis.length})
      </h4>
      <div className="overflow-x-auto rounded-xl border" style={{ borderColor: 'var(--border)' }}>
        <table className="w-full text-sm text-left">
          <thead style={{ background: 'var(--surface-alt)' }}>
            <tr>
              <th className="p-3 font-semibold">KPI Name</th>
              <th className="p-3 font-semibold">Source</th>
              <th className="p-3 font-semibold">Target</th>
              <th className="p-3 font-semibold">Status</th>
            </tr>
          </thead>
          <tbody>
            {kpis.map((item, idx) => (
              <tr key={idx} className="dv-row dv-diff-row-mismatch" style={{ borderTop: '1px solid var(--border)' }}>
                <td className="p-3 font-medium">{item.kpi || item.name}</td>
                <td className="p-3 dv-font-mono">{item.source ?? '—'}</td>
                <td className="p-3 dv-font-mono">{item.target ?? '—'}</td>
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
