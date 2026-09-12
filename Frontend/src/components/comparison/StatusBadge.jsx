import { CheckCircle2, AlertTriangle, AlertCircle } from 'lucide-react';

export function StatusBadge({ status }) {
  const isMatch = status === 'Match';
  const isNearMatch = status === 'Near Match';

  const style = isMatch
    ? { background: 'var(--success-bg)', color: 'var(--success)', border: '1px solid var(--success-border)' }
    : isNearMatch
    ? { background: 'var(--accent-bg)', color: 'var(--accent-text)', border: '1px solid var(--accent-border)' }
    : { background: 'var(--danger-bg)', color: 'var(--danger)', border: '1px solid var(--danger-border)' };

  return (
    <div className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-semibold" style={style}>
      {isMatch ? (
        <CheckCircle2 className="w-3.5 h-3.5" />
      ) : isNearMatch ? (
        <AlertTriangle className="w-3.5 h-3.5" />
      ) : (
        <AlertCircle className="w-3.5 h-3.5" />
      )}
      {status}
    </div>
  );
}
