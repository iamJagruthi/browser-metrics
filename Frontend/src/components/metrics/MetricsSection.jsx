import { BarChart3, ArrowLeftRight } from 'lucide-react';
import { DashboardCard } from './DashboardCard';

export function MetricsSection({ metrics }) {
  const safeMetrics = Array.isArray(metrics) ? metrics : [];
  if (safeMetrics.length === 0) return null;

  return (
    <div className="space-y-6 animate-in fade-in slide-in-from-bottom-8 duration-700 delay-100 fill-mode-both">
      <div className="flex items-center gap-2 mb-6">
        <BarChart3 className="w-5 h-5" style={{ color: 'var(--accent-text)' }} />
        <h2 className="dv-font-display text-xl font-bold" style={{ color: 'var(--text)' }}>
          Performance Metrics
        </h2>
      </div>

      <div className="grid lg:grid-cols-2 gap-6 relative">
        {safeMetrics.map((m, i) => (
          <DashboardCard key={i} metric={m} index={i} />
        ))}
        {safeMetrics.length === 2 && (
          <div
            className="hidden lg:flex absolute left-1/2 top-16 -translate-x-1/2 items-center justify-center w-9 h-9 rounded-full z-10"
            style={{ background: 'var(--accent)', border: '1px solid var(--accent-border)', boxShadow: 'var(--shadow-md)' }}
          >
            <ArrowLeftRight className="w-4 h-4" style={{ color: '#0A0A0A' }} />
          </div>
        )}
      </div>
    </div>
  );
}
