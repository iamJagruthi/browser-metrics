import { ShieldCheck } from 'lucide-react';
import { AppliedFiltersCard } from './AppliedFiltersCard';

export function AppliedFiltersSection({ appliedFilters, mismatches }) {
  if (!appliedFilters) return null;

  const pageNames = Object.keys(appliedFilters);
  if (pageNames.length === 0) return null;

  const pageMismatches = Array.isArray(mismatches?.page_mismatches) ? mismatches.page_mismatches : [];
  const mismatchByPage = Object.fromEntries(
    pageMismatches.map((pm) => [pm.page_name, pm])
  );

  return (
    <div className="space-y-6 animate-in fade-in slide-in-from-bottom-8 duration-700 delay-200 fill-mode-both">
      <div className="flex items-center gap-2 mb-2">
        <ShieldCheck className="w-5 h-5" style={{ color: 'var(--accent-text)' }} />
        <h2 className="dv-font-display text-xl font-bold" style={{ color: 'var(--text)' }}>
          Filters Applied & Comparison Results
        </h2>
      </div>
      <p className="text-sm mb-4" style={{ color: 'var(--text-muted)' }}>
        Filter values picked on the source dashboard and replayed on the target, with the resulting comparison per page.
      </p>

      {pageNames.map((pageName) => (
        <AppliedFiltersCard
          key={pageName}
          pageName={pageName}
          filters={appliedFilters[pageName]}
          pageMismatch={mismatchByPage[pageName]}
        />
      ))}
    </div>
  );
}