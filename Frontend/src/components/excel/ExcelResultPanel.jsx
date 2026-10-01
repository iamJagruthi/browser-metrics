import { CheckCircle2, XCircle, Fuel, MinusCircle, Columns3 } from 'lucide-react';

const STATUS_OK = 'matched';

const statChip = (label, value) => (
  <div
    className="flex-1 min-w-[110px] px-4 py-3 rounded-xl"
    style={{ background: 'var(--surface-alt)', border: '1px solid var(--border)' }}
  >
    <p className="text-[11px] font-bold uppercase tracking-wider mb-1" style={{ color: 'var(--text-muted)' }}>
      {label}
    </p>
    <p className="dv-font-display text-lg font-bold" style={{ color: 'var(--text)' }}>{value}</p>
  </div>
);

export function ExcelResultPanel({ result }) {
  if (!result) return null;

  const ok = result.status === STATUS_OK;
  const summary = result.summary || {};

  return (
    <div className="space-y-4 animate-in fade-in slide-in-from-bottom-8 duration-500 fill-mode-both">
      <div className="dv-surface p-6 rounded-3xl border">
        <div className="flex flex-col gap-6">
          <div className="flex items-start justify-between gap-4 flex-wrap">
            <div>
              <h3 className="dv-font-display text-base font-bold mb-1" style={{ color: 'var(--text)' }}>
                Excel Validation Result
              </h3>
              <p className="text-xs" style={{ color: 'var(--text-muted)' }}>
                {result.source_filename} vs {result.target_filename}
              </p>
            </div>
            <div className="flex items-center gap-2">
              {ok ? (
                <CheckCircle2 className="w-5 h-5" style={{ color: 'var(--success)' }} />
              ) : (
                <XCircle className="w-5 h-5" style={{ color: 'var(--danger)' }} />
              )}
              <span className="text-sm font-bold" style={{ color: ok ? 'var(--success)' : 'var(--danger)' }}>
                {result.status}
              </span>
            </div>
          </div>

          <div className="flex gap-3 flex-wrap">
            {statChip('Sheets Compared', summary.sheet_count ?? '—')}
            {statChip('Total Checks', summary.total_checks ?? '—')}
            {statChip('Matched', summary.matched_count ?? '—')}
            {statChip('Mismatched', summary.mismatch_count ?? '—')}
            {statChip('Mismatched Cells', summary.mismatched_cells ?? '—')}
            {statChip('Column Diffs', summary.column_difference_count ?? '—')}
          </div>

          {result.word_report_note && (
            <p className="text-xs" style={{ color: 'var(--text-muted)' }}>
              {result.word_report_note}
            </p>
          )}
        </div>
      </div>

      {(result.sheet_comparisons || []).map((sheet) => {
        const matched = sheet.status === 'TABLE_MATCHED';
        const columnDiffs = sheet.column_differences || [];
        return (
          <div key={sheet.sheet} className="dv-surface p-5 rounded-3xl border">
            <div className="flex items-center justify-between gap-4 flex-wrap mb-3">
              <h4 className="dv-font-display text-sm font-bold" style={{ color: 'var(--text)' }}>
                Sheet "{sheet.sheet}"
              </h4>
              <span
                className="inline-flex items-center gap-1.5 text-[11px] font-bold px-2.5 py-1 rounded-full"
                style={{
                  color: matched ? 'var(--success)' : 'var(--danger)',
                  background: 'var(--surface-alt)',
                  border: '1px solid var(--border)',
                }}
              >
                {matched ? <CheckCircle2 className="w-3.5 h-3.5" /> : <XCircle className="w-3.5 h-3.5" />}
                {sheet.status}
              </span>
            </div>

            <div className="flex gap-3 flex-wrap mb-4">
              {statChip('Source Rows', sheet.source_row_count)}
              {statChip('Target Rows', sheet.target_row_count)}
              {statChip('Matched Rows', sheet.matched_rows)}
              {statChip('Mismatched Rows', sheet.mismatched_rows)}
              {statChip('Missing Src/Tgt', `${sheet.missing_in_source_rows}/${sheet.missing_in_target_rows}`)}
              {statChip('Mismatched Cells', sheet.mismatched_cells)}
            </div>

            {columnDiffs.length > 0 && (
              <div className="mb-3">
                <p className="flex items-center gap-1.5 text-[11px] font-bold uppercase tracking-wider mb-1.5" style={{ color: 'var(--text-muted)' }}>
                  <Columns3 className="w-3.5 h-3.5" /> Column differences
                </p>
                <div className="flex flex-wrap gap-2">
                  {columnDiffs.map((diff, idx) => (
                    <span
                      key={idx}
                      className="dv-font-mono text-[11px] px-2 py-1 rounded"
                      style={{ background: 'var(--surface-alt)', border: '1px solid var(--border)', color: 'var(--danger)' }}
                    >
                      {diff.column} ({diff.presence})
                    </span>
                  ))}
                </div>
              </div>
            )}

            {(sheet.mismatch_details || []).length > 0 && (
              <div>
                <p className="flex items-center gap-1.5 text-[11px] font-bold uppercase tracking-wider mb-1.5" style={{ color: 'var(--text-muted)' }}>
                  <Fuel className="w-3.5 h-3.5" /> Mismatch details
                </p>
                <ul className="space-y-1.5">
                  {sheet.mismatch_details.map((item, idx) => (
                    <li
                      key={idx}
                      className="p-2.5 rounded-lg"
                      style={{ background: 'var(--surface-alt)', border: '1px solid var(--danger-border)' }}
                    >
                      <p className="dv-font-mono text-[11px] mb-1" style={{ color: 'var(--text)' }}>
                        {item.keys ? JSON.stringify(item.keys) : 'row'}
                      </p>
                      {(item.differences || []).map((diff, dIdx) => (
                        <p key={dIdx} className="dv-font-mono text-[11px]" style={{ color: 'var(--text-muted)' }}>
                          {diff.column}: "{diff.source_value}" → "{diff.target_value}"
                        </p>
                      ))}
                    </li>
                  ))}
                </ul>
              </div>
            )}

            {matched && (sheet.mismatch_details || []).length === 0 && columnDiffs.length === 0 && (
              <p className="flex items-center gap-1.5 text-sm" style={{ color: 'var(--success)' }}>
                <MinusCircle className="w-4 h-4" /> All rows matched between source and target.
              </p>
            )}
          </div>
        );
      })}
    </div>
  );
}