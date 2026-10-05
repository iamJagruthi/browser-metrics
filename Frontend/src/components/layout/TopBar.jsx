import { Sun, Moon } from 'lucide-react';
import { BrandMark } from './BrandMark';
import { HealthDot } from './HealthDot';

export function TopBar({ theme, onToggleTheme, apiStatus }) {
  return (
    <div className="dv-topbar sticky top-0 z-20">
      <div className="max-w-6xl mx-auto px-4 sm:px-8 py-2 flex items-center justify-between">
        <div className="flex items-center gap-2.5">
          <div className="p-1 bg-white rounded">
            <BrandMark size={20} />
          </div>
          <p className="dv-font-display text-white font-bold text-base leading-none">Wiz Match</p>
          <span className="hidden sm:block w-px h-4 bg-white/30" aria-hidden="true" />
          <p className="hidden sm:block text-xs text-white/80 leading-none">SpartanNash - C&amp;S</p>
        </div>

        <div className="flex items-center gap-2.5">
          <HealthDot status={apiStatus} />
          <button
            onClick={onToggleTheme}
            aria-label="Toggle dark mode"
            className="dv-toggle flex items-center gap-2 px-2.5 py-1.5 rounded-full text-xs font-medium transition-colors duration-200"
          >
            {theme === 'dark' ? <Sun className="w-4 h-4" /> : <Moon className="w-4 h-4" />}
            <span className="hidden sm:inline">{theme === 'dark' ? 'Light' : 'Dark'}</span>
          </button>
        </div>
      </div>
    </div>
  );
}