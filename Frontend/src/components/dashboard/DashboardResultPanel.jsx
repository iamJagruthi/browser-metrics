import { FileText, ImageIcon, CheckCircle2, XCircle } from 'lucide-react';
import { BASE_URL } from '../../config';
import { ReportButton } from '../reports/ReportButton';

export function DashboardResultPanel({ result }) {
  if (!result) return null;

  const status = result.comparison?.status;
  const matchPercentage = result.comparison?.summary?.overall_match_percentage;
  const mismatchCount = result.mismatches?.summary?.total_mismatches;
  const docxReady = result.docx_ready === true;
  const docxUrl = result.docx_download_url
    ? `${BASE_URL}${result.docx_download_url}`
    : null;

  const statusLabel = status || 'not_compared';
  const statusOk = statusLabel === 'success';
  const match = matchPercentage != null ? `${Number(matchPercentage).toFixed(2)}%` : '—';

  const statChip = (label, value) => (
    <div
      className="flex-1 min-w-[110px] px-4 py-3 rounded-xl"
      style={{ background: 'var(--surface-alt)', border: '1px solid var(--border)' }}
    >
      <p className="text-[11px] font-bold uppercase tracking-wider mb-1" style={{ color: 'var(--text-muted)' }}>
        {label}
      </p>
      <p className="dv-font-display text-lg font-bold" style={{ color: 'var(--text)' }}>
        {value}
      </p>
    </div>
  );

  return (
    <div className="space-y-4 animate-in fade-in slide-in-from-bottom-8 duration-500 fill-mode-both">
      <div className="dv-surface p-6 rounded-3xl border">
        <div className="flex flex-col gap-6">
          <div className="flex items-start justify-between gap-4 flex-wrap">
            <div>
              <h3 className="dv-font-display text-base font-bold mb-1" style={{ color: 'var(--text)' }}>
                Dashboard Validation Result
              </h3>
              <p className="dv-font-mono text-[11px]" style={{ color: 'var(--text-muted)', opacity: 0.7 }}>
                run_id: {result.run_id}
              </p>
            </div>
            <div className="flex items-center gap-2">
              {statusOk ? (
                <CheckCircle2 className="w-5 h-5" style={{ color: 'var(--success)' }} />
              ) : (
                <XCircle className="w-5 h-5" style={{ color: 'var(--danger)' }} />
              )}
              <span className="text-sm font-bold" style={{ color: statusOk ? 'var(--success)' : 'var(--danger)' }}>
                {statusLabel}
              </span>
            </div>
          </div>

          <div className="flex gap-3 flex-wrap">
            {statChip('Overall Match', match)}
            {statChip('Mismatches', mismatchCount ?? '—')}
            {statChip('Word Report', docxReady ? 'Ready' : 'Not generated')}
          </div>

          <div
            className="flex items-start gap-3 p-4 rounded-2xl"
            style={{ background: 'var(--surface-alt)', border: '1px solid var(--border)' }}
          >
            <ImageIcon className="w-5 h-5 flex-shrink-0 mt-0.5" style={{ color: 'var(--accent-text)' }} />
            <div>
              <p className="text-sm font-semibold" style={{ color: 'var(--text)' }}>
                Screenshots included
              </p>
              <p className="text-sm" style={{ color: 'var(--text-muted)' }}>
                The Word report embeds the source/target dashboard screenshots
                captured during validation. No screenshots are re-captured for
                the report.
              </p>
            </div>
          </div>

          <div className="flex gap-3 flex-shrink-0">
            <ReportButton
              label={docxReady ? 'Download Word Report' : 'Word Report unavailable'}
              icon={FileText}
              ready={docxReady}
              href={docxUrl}
              checking={false}
            />
          </div>
        </div>
      </div>
    </div>
  );
}