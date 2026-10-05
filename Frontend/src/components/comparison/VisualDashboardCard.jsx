export function VisualDashboardCard({ dashboardName, visuals, kpiCards, kpis }) {
  const hasVisuals = visuals && visuals.length > 0;
  const hasKpis = kpis && kpis.length > 0;
  const hasKpiCards = kpiCards && kpiCards.length > 0;

  if (!hasVisuals && !hasKpis && !hasKpiCards) return null;

  return (
    <div className="dv-surface rounded-3xl overflow-hidden mb-6 border" style={{ borderColor: 'var(--border)' }}>
      <div
        className="px-6 py-4 flex items-center justify-between gap-3"
        style={{ background: '#0A0A0A', color: 'white' }}
      >
        <span className="dv-font-display font-bold text-lg">{dashboardName}</span>
        <span className="text-xs text-white/60 font-mono">
          {visuals?.length || 0} visual(s) · {(kpis?.length || 0) + (kpiCards?.length || 0)} KPI(s)
        </span>
      </div>

      <div className="p-6 space-y-6">
        {hasVisuals && (
          <div>
            <h4 className="text-sm font-semibold mb-3" style={{ color: 'var(--text)' }}>
              Visuals
            </h4>
            <div className="overflow-x-auto rounded-xl border" style={{ borderColor: 'var(--border)' }}>
              <table className="w-full text-sm text-left">
                <thead style={{ background: 'var(--surface-alt)' }}>
                  <tr>
                    <th className="p-3 font-semibold">#</th>
                    <th className="p-3 font-semibold">Title</th>
                    <th className="p-3 font-semibold">Type</th>
                    <th className="p-3 font-semibold">Role</th>
                  </tr>
                </thead>
                <tbody>
                  {visuals.map((v) => (
                    <tr key={v.id ?? v.index} style={{ borderTop: '1px solid var(--border)' }}>
                      <td className="p-3 dv-font-mono text-xs">{v.index}</td>
                      <td className="p-3 font-medium">{v.title || '—'}</td>
                      <td className="p-3 dv-font-mono text-xs">{v.visual_type || '—'}</td>
                      <td className="p-3 dv-font-mono text-xs">{v.aria_role || '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}

        {(hasKpis || hasKpiCards) && (
          <div>
            <h4 className="text-sm font-semibold mb-3" style={{ color: 'var(--text)' }}>
              KPIs
            </h4>
            {!hasKpis && !hasKpiCards ? null : (
              <div className="overflow-x-auto rounded-xl border" style={{ borderColor: 'var(--border)' }}>
                <pre
                  className="text-xs dv-font-mono p-3"
                  style={{ background: 'var(--surface-alt)', color: 'var(--text-muted)' }}
                >
                  {JSON.stringify(hasKpis ? kpis : kpiCards, null, 2)}
                </pre>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}