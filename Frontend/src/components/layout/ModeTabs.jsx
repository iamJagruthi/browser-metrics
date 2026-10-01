import { LayoutDashboard, FileSpreadsheet } from 'lucide-react';

export function ModeTabs({ mode, onModeChange }) {
  const base = 'inline-flex items-center gap-2 px-5 py-2.5 text-sm font-semibold rounded-xl transition-all duration-200';
  return (
    <div
      className="inline-flex p-1 rounded-2xl mb-8"
      style={{ background: 'var(--surface-alt)', border: '1px solid var(--border)' }}
      role="tablist"
    >
      <button
        type="button"
        role="tab"
        aria-selected={mode === 'dashboard'}
        onClick={() => onModeChange('dashboard')}
        className={`${base} ${mode === 'dashboard' ? 'dv-btn-primary' : ''}`}
        style={mode !== 'dashboard' ? { color: 'var(--text-muted)' } : undefined}
      >
        <LayoutDashboard className="w-4 h-4" />
        Dashboard Validation
      </button>
      <button
        type="button"
        role="tab"
        aria-selected={mode === 'excel'}
        onClick={() => onModeChange('excel')}
        className={`${base} ${mode === 'excel' ? 'dv-btn-primary' : ''}`}
        style={mode !== 'excel' ? { color: 'var(--text-muted)' } : undefined}
      >
        <FileSpreadsheet className="w-4 h-4" />
        Excel Validation
      </button>
    </div>
  );
}