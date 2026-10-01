import { CheckCircle2, Loader2, XCircle, Circle } from 'lucide-react';

const STATE_ICON = {
  done: CheckCircle2,
  active: Loader2,
  error: XCircle,
  pending: Circle,
};

export function ProgressSteps({ steps }) {
  if (!steps || steps.length === 0) return null;

  return (
    <div
      className="p-5 rounded-2xl animate-in fade-in zoom-in-95 duration-300"
      style={{ background: 'var(--surface-alt)', border: '1px solid var(--border)' }}
    >
      <p className="text-xs font-bold uppercase tracking-wider mb-4" style={{ color: 'var(--text-muted)' }}>
        Validation progress
      </p>
      <ul className="space-y-3">
        {steps.map((step) => {
          const Icon = STATE_ICON[step.state] || Circle;
          const isActive = step.state === 'active';
          const isError = step.state === 'error';
          const isPending = step.state === 'pending';
          return (
            <li key={step.key} className="flex items-center gap-3">
              <Icon
                className={`w-4 h-4 flex-shrink-0 ${isActive ? 'animate-spin' : ''}`}
                style={{
                  color: isError
                    ? 'var(--danger)'
                    : isActive
                      ? 'var(--accent-text)'
                      : isPending
                        ? 'var(--text-muted)'
                        : 'var(--success)',
                }}
              />
              <span
                className="text-sm font-medium"
                style={{
                  color: isPending ? 'var(--text-muted)' : 'var(--text)',
                  opacity: isPending ? 0.6 : 1,
                }}
              >
                {step.label}
              </span>
            </li>
          );
        })}
      </ul>
    </div>
  );
}