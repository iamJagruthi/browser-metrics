import { LayoutDashboard, FileSpreadsheet } from 'lucide-react';

const TABS = [
  { key: 'dashboard', label: 'Dashboard Validation', Icon: LayoutDashboard },
  { key: 'excel', label: 'Excel Validation', Icon: FileSpreadsheet },
];

export function ModeTabs({ mode, onModeChange }) {
  return (
    <div
      className="inline-flex gap-4 sm:gap-8 mb-8 border-b"
      style={{ borderColor: 'var(--border)' }}
      role="tablist"
    >
      {TABS.map(({ key, label, Icon }) => {
        const active = mode === key;
        return (
          <button
            key={key}
            type="button"
            role="tab"
            aria-selected={active}
            onClick={() => onModeChange(key)}
            className="inline-flex items-center gap-2 px-1 pb-3 -mb-px text-sm font-semibold border-b-[3px] transition-colors duration-200"
            style={{
              color: active ? 'var(--text)' : 'var(--text-muted)',
              borderColor: active ? 'var(--accent)' : 'transparent',
            }}
          >
            <Icon className="w-4 h-4 hidden sm:block" />
            {label}
          </button>
        );
      })}
    </div>
  );
}