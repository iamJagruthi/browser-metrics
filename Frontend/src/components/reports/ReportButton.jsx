import { Loader2, Download } from 'lucide-react';

export function ReportButton({ label, icon: Icon, ready, href, checking }) {
  if (ready && href) {
    return (
      <a
        href={href}
        target="_blank"
        rel="noreferrer"
        className="dv-btn-outline inline-flex items-center gap-2 px-5 py-3 rounded-xl text-sm font-semibold transition-all duration-200"
      >
        <Icon className="w-4 h-4" style={{ color: 'var(--accent-text)' }} />
        <span>{label}</span>
        <Download className="w-4 h-4 ml-1" />
      </a>
    );
  }

  return (
    <button type="button" disabled className="dv-btn-outline inline-flex items-center gap-2 px-5 py-3 rounded-xl text-sm font-semibold">
      {checking ? (
        <Loader2 className="w-4 h-4 animate-spin" />
      ) : (
        <Icon className="w-4 h-4" style={{ color: 'var(--text-muted)' }} />
      )}
      <span style={{ color: 'var(--text-muted)' }}>{checking ? 'Generating…' : `${label} unavailable`}</span>
    </button>
  );
}
