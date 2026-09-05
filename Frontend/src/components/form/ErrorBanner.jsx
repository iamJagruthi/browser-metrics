import { AlertTriangle } from 'lucide-react';

export function ErrorBanner({ message }) {
  if (!message) return null;

  return (
    <div className="max-w-4xl mx-auto mt-6 animate-in fade-in slide-in-from-top-2 duration-300">
      <div
        className="flex items-center gap-3 p-4 rounded-2xl"
        style={{ background: 'var(--danger-bg)', border: '1px solid var(--danger-border)' }}
      >
        <AlertTriangle className="w-5 h-5 flex-shrink-0" style={{ color: 'var(--danger)' }} />
        <p className="font-medium text-sm" style={{ color: 'var(--danger)' }}>
          {message}
        </p>
      </div>
    </div>
  );
}
