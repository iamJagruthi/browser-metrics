import { Sun, Moon } from 'lucide-react';
import { BrandMark } from './BrandMark';
import { HealthDot } from './HealthDot';

export function TopBar({ theme, onToggleTheme, apiStatus }) {
  return (
    <div className="dv-topbar sticky top-0 z-20">
      <div className="max-w-6xl mx-auto px-4 sm:px-8 py-3.5 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="p-1.5 bg-white/10 rounded-lg border border-white/15">
            <BrandMark />
          </div>
          <div>
            <p className="dv-font-display text-white font-semibold text-base leading-none">Dashboard Validator</p>
            <p className="text-[11px] text-white/60 mt-1 tracking-wide uppercase">
              SpartanNash · Talent Acquisition BI
            </p>
          </div>
        </div>

        <div className="flex items-center gap-3">
          <HealthDot status={apiStatus} />
          <button
            onClick={onToggleTheme}
            aria-label="Toggle dark mode"
            className="dv-toggle flex items-center gap-2 px-3 py-2 rounded-full text-xs font-medium transition-colors duration-200"
          >
            {theme === 'dark' ? <Sun className="w-4 h-4" /> : <Moon className="w-4 h-4" />}
            <span className="hidden sm:inline">{theme === 'dark' ? 'Light' : 'Dark'}</span>
          </button>
        </div>
      </div>
    </div>
  );
}
