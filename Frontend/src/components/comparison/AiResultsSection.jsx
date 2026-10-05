import { Sparkles, Table2, Image as ImageIcon, FileDown } from 'lucide-react';

const num = (value) => (value == null || value === '' ? '—' : value);
const money = (value) => (value == null ? '—' : `$${Number(value).toFixed(4)}`);
const moneyInr = (value) => (value == null ? '—' : `₹${Number(value).toFixed(2)}`);
const tokens = (value) => (value == null ? '—' : Number(value).toLocaleString());
const pct = (value) => (value == null ? '—' : `${(Number(value) * 100).toFixed(1)}%`);
const seconds = (value) => (value == null ? '—' : `${Number(value).toFixed(0)}s`);

function AiStatusPill({ status, reason }) {
  const lower = String(status || '').toLowerCase();
  let style;
  if (['completed', 'ok', 'success', 'done'].includes(lower)) {
    style = { background: 'var(--success-bg)', color: 'var(--success)', border: '1px solid var(--success-border)' };
  } else if (['running', 'queued', 'pending', 'processing', 'started', 'in_progress'].includes(lower)) {
    style = { background: 'var(--accent-bg)', color: 'var(--accent-text)', border: '1px solid var(--accent-border)' };
  } else if (['not_configured', 'not-configured', 'skipped', 'disabled', 'unconfigured'].includes(lower)) {
    style = { background: 'var(--surface-alt)', color: 'var(--text-muted)', border: '1px solid var(--border)' };
  } else {
    style = { background: 'var(--danger-bg)', color: 'var(--danger)', border: '1px solid var(--danger-border)' };
  }
  return (
    <div className="flex items-center gap-2 flex-wrap">
      <span className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-semibold" style={style}>
        {status || '—'}
      </span>
      {reason && (
        <span className="text-xs" style={{ color: 'var(--text-muted)' }}>
          {reason}
        </span>
      )}
    </div>
  );
}

const statChip = (label, value) => (
  <span
    style={{
      display: 'inline-flex',
      alignItems: 'center',
      gap: '0.35rem',
      padding: '0.2rem 0.55rem',
      borderRadius: '9999px',
      fontSize: '0.7rem',
      fontWeight: 600,
      background: 'var(--surface-alt)',
      color: 'var(--text-muted)',
      border: '1px solid var(--border)',
    }}
  >
    {label} <b style={{ color: 'var(--text)' }}>{num(value)}</b>
  </span>
);

function PairsTable({ pairs }) {
  if (!pairs || pairs.length === 0) return null;
  return (
    <div>
      <h3 className="text-sm font-semibold mb-3 flex items-center gap-2" style={{ color: 'var(--text)' }}>
        <Table2 className="w-4 h-4" style={{ color: 'var(--accent-text)' }} />
        Image Pair Comparison ({pairs.length})
      </h3>
      <div className="overflow-x-auto rounded-xl border" style={{ borderColor: 'var(--border)' }}>
        <table className="w-full text-sm text-left">
          <thead style={{ background: 'var(--surface-alt)' }}>
            <tr>
              <th className="p-3 font-semibold">Pair</th>
              <th className="p-3 font-semibold">Source title</th>
              <th className="p-3 font-semibold">Target title</th>
              <th className="p-3 font-semibold">Total items</th>
              <th className="p-3 font-semibold">Matches</th>
              <th className="p-3 font-semibold">Differences</th>
              <th className="p-3 font-semibold">Source-only</th>
              <th className="p-3 font-semibold">Target-only</th>
              <th className="p-3 font-semibold">Uncertain</th>
              <th className="p-3 font-semibold">Match %</th>
            </tr>
          </thead>
          <tbody>
            {pairs.map((pair, idx) => (
              <tr key={idx} className="dv-row" style={{ borderTop: '1px solid var(--border)' }}>
                <td className="p-3 font-medium">{num(pair.pair)}</td>
                <td className="p-3">{pair.spartnash_title || '—'}</td>
                <td className="p-3">{pair.trendence_title || '—'}</td>
                <td className="p-3">{num(pair.total_items)}</td>
                <td className="p-3" style={{ color: 'var(--success)' }}>
                  {num(pair.matches)}
                </td>
                <td className="p-3" style={{ color: 'var(--danger)' }}>
                  {num(pair.differences)}
                </td>
                <td className="p-3">{num(pair.spartnash_only)}</td>
                <td className="p-3">{num(pair.trendence_only)}</td>
                <td className="p-3">{num(pair.uncertain)}</td>
                <td className="p-3 phon">{pct(pair.match_percentage)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function ImageStatsTable({ imageStats }) {
  if (!imageStats || imageStats.length === 0) return null;
  return (
    <div>
      <h3 className="text-sm font-semibold mb-3 flex items-center gap-2" style={{ color: 'var(--text)' }}>
        <ImageIcon className="w-4 h-4" style={{ color: 'var(--accent-text)' }} />
        Token & Cost per Image ({imageStats.length})
      </h3>
      <div className="overflow-x-auto rounded-xl border" style={{ borderColor: 'var(--border)' }}>
        <table className="w-full text-sm text-left">
          <thead style={{ background: 'var(--surface-alt)' }}>
            <tr>
              <th className="p-3 font-semibold">Folder</th>
              <th className="p-3 font-semibold">Image</th>
              <th className="p-3 font-semibold">Dimensions</th>
              <th className="p-3 font-semibold">Prompt tokens</th>
              <th className="p-3 font-semibold">Image tokens</th>
              <th className="p-3 font-semibold">Input tokens</th>
              <th className="p-3 font-semibold">Output tokens</th>
              <th className="p-3 font-semibold">Total tokens</th>
              <th className="p-3 font-semibold">Cost USD</th>
              <th className="p-3 font-semibold">Cost INR</th>
              <th className="p-3 font-semibold">LLM calls</th>
            </tr>
          </thead>
          <tbody>
            {imageStats.map((item, idx) => (
              <tr key={idx} className="dv-row" style={{ borderTop: '1px solid var(--border)' }}>
                <td className="p-3 font-medium">{item.folder || '—'}</td>
                <td className="p-3">{item.image || '—'}</td>
                <td className="p-3">
                  {item.width != null && item.height != null ? `${item.width}×${item.height}` : '—'}
                </td>
                <td className="p-3">{tokens(item.prompt_tokens)}</td>
                <td className="p-3">{tokens(item.image_input_tokens)}</td>
                <td className="p-3">{tokens(item.total_input_tokens)}</td>
                <td className="p-3">{tokens(item.output_tokens)}</td>
                <td className="p-3">{tokens(item.total_tokens)}</td>
                <td className="p-3">{money(item.total_cost_usd)}</td>
                <td className="p-3">{moneyInr(item.total_cost_inr)}</td>
                <td className="p-3">{num(item.llm_calls)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export function AiResultsSection({ aiAnalysis }) {
  if (!aiAnalysis) return null;

  const payload =
    aiAnalysis.results && typeof aiAnalysis.results === 'object' && !Array.isArray(aiAnalysis.results)
      ? aiAnalysis.results
      : aiAnalysis.compare_status_payload || {};
  const pairs = Array.isArray(payload.pairs) ? payload.pairs : [];
  const imageStats = Array.isArray(payload.image_stats) ? payload.image_stats : [];
  const uploaded = aiAnalysis.uploaded || {};
  const summary = aiAnalysis.status === 'completed' ? aiAnalysis : payload;
  const workbookAvailable =
    aiAnalysis.workbook_available === true || payload.workbook_available === true;
  const downloadUrl = aiAnalysis.download_url || payload.download_url || null;
  const jsonDownloadUrl = aiAnalysis.json_download_url || payload.json_download_url || null;

  return (
    <div className="dv-surface rounded-3xl p-6 space-y-6 animate-in fade-in slide-in-from-bottom-8 duration-500 fill-mode-both">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div className="flex items-center gap-2">
          <Sparkles className="w-5 h-5" style={{ color: 'var(--accent-text)' }} />
          <h2 className="dv-font-display text-xl font-bold" style={{ color: 'var(--text)' }}>
            AI Validation Results
          </h2>
        </div>
        <AiStatusPill status={aiAnalysis.status} reason={aiAnalysis.reason || aiAnalysis.error} />
      </div>

      {pairs.length === 0 && aiAnalysis.status === 'completed' && (
        <p className="text-sm" style={{ color: 'var(--text-muted)' }}>
          The hosted service completed but returned no image pair comparisons.
        </p>
      )}

      <div className="flex gap-2 flex-wrap">
        {aiAnalysis.job_id && statChip('Job', aiAnalysis.job_id)}
        {uploaded.source != null && statChip('Source images uploaded', uploaded.source)}
        {uploaded.target != null && statChip('Target images uploaded', uploaded.target)}
        {aiAnalysis.dashboard_name && statChip('Dashboard', aiAnalysis.dashboard_name)}
        {aiAnalysis.duration_seconds != null && statChip('Duration', seconds(aiAnalysis.duration_seconds))}
        {summary.total_llm_calls != null && statChip('LLM calls', summary.total_llm_calls)}
        {summary.total_tokens != null && statChip('Total tokens', tokens(summary.total_tokens))}
        {summary.total_cost_usd != null && statChip('Total cost', `${money(summary.total_cost_usd)} / ${moneyInr(summary.total_cost_inr)}`)}
      </div>

      <div className="space-y-6">
        <PairsTable pairs={pairs} />
        <ImageStatsTable imageStats={imageStats} />
      </div>

      {workbookAvailable && (downloadUrl || jsonDownloadUrl) && (
        <div
          className="flex items-center gap-2 px-4 py-3 rounded-xl text-xs"
          style={{ background: 'var(--accent-bg)', color: 'var(--accent-text)', border: '1px solid var(--accent-border)' }}
        >
          <FileDown className="w-4 h-4" />
          <span>
            Excel workbook / JSON are available from the hosted AI service
            {downloadUrl ? ` (${downloadUrl})` : ''}
            {downloadUrl && jsonDownloadUrl ? ' and' : ''}
            {jsonDownloadUrl ? ` (${jsonDownloadUrl})` : ''}.
          </span>
        </div>
      )}
    </div>
  );
}