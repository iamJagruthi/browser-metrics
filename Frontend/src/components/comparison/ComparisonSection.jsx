import { ShieldCheck, CheckCircle2 } from 'lucide-react';
import {MatchRing} from './MatchRing.jsx';
import { PageMismatchCard } from './PageMismatchCard.jsx';

export function ComparisonSection({ mismatches }) {
  if (!mismatches) return null;

  const pageMismatches = Array.isArray(mismatches?.page_mismatches) ? mismatches.page_mismatches : [];
  const summary = mismatches?.summary || {};
  const totalMismatches = summary.total_mismatches ?? 0;
  const matchPercentage = mismatches?.match_percentage ?? summary.overall_match_percentage ?? 0;

  return (
    <div className="space-y-8 animate-in fade-in slide-in-from-bottom-8 duration-700 delay-200 fill-mode-both">
      <div className="dv-surface flex flex-col md:flex-row gap-6 items-center p-6 rounded-3xl">
        <MatchRing percentage={matchPercentage} />
        <div>
          <h2 className="dv-font-display text-xl font-bold mb-2 flex items-center gap-2" style={{ color: 'var(--text)' }}>
            <ShieldCheck className="w-5 h-5" style={{ color: 'var(--accent-text)' }} />
            Page & Filter Validation Breakdown
          </h2>
          <p className="text-sm leading-relaxed max-w-2xl" style={{ color: 'var(--text-muted)' }}>
            Found {totalMismatches} total mismatch(es) across {pageMismatches.length} report page state(s).
          </p>
        </div>
      </div>

      {totalMismatches === 0 && (
        <div className="dv-surface p-8 rounded-3xl text-center" style={{ color: 'var(--success)' }}>
          <CheckCircle2 className="w-8 h-8 mx-auto mb-3" />
          <p className="font-semibold">All pages and applied filter permutations match perfectly!</p>
        </div>
      )}

      {pageMismatches.map((pageMismatch, idx) => (
        <PageMismatchCard key={idx} pageMismatch={pageMismatch} />
      ))}
    </div>
  );
}
