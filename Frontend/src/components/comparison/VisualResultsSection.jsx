import { LayoutGrid } from 'lucide-react';
import { VisualDashboardCard } from './VisualDashboardCard.jsx';

export function VisualResultsSection({ visualResults, kpis, comparisonVisuals }) {
  const dashboards = Array.isArray(visualResults) ? visualResults : [];
  if (dashboards.length === 0) return null;

  return (
    <div className="space-y-6 animate-in fade-in slide-in-from-bottom-8 duration-700 delay-200 fill-mode-both">
      <div className="flex items-center gap-2 mb-2">
        <LayoutGrid className="w-5 h-5" style={{ color: 'var(--accent-text)' }} />
        <h2 className="dv-font-display text-xl font-bold" style={{ color: 'var(--text)' }}>
          Visuals & KPIs Detected
        </h2>
      </div>

      {dashboards.map((dashboardResult, idx) => (
        <VisualDashboardCard
          key={dashboardResult.dashboard || idx}
          dashboardName={dashboardResult.dashboard || `Dashboard ${idx + 1}`}
          visuals={dashboardResult.visuals || []}
          kpiCards={dashboardResult.kpi_cards || []}
          kpis={Array.isArray(kpis) ? kpis[idx] : []}
        />
      ))}

      {Array.isArray(comparisonVisuals) && comparisonVisuals.length > 0 && (
        <div className="dv-surface rounded-3xl p-6">
          <h3 className="text-sm font-semibold mb-3" style={{ color: 'var(--text)' }}>
            Visual Comparison Results
          </h3>
          <pre
            className="text-xs dv-font-mono overflow-x-auto p-3 rounded-xl"
            style={{ background: 'var(--surface-alt)', color: 'var(--text-muted)' }}
          >
            {JSON.stringify(comparisonVisuals, null, 2)}
          </pre>
        </div>
      )}
    </div>
  );
}