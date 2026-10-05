import { useState } from 'react';
import { useTheme } from './hooks/useTheme.js';
import { useApiHealth } from './hooks/useApiHealth.js';

import { TopBar } from './components/layout/TopBar.jsx';
import { Hero } from './components/layout/Hero.jsx';
import { ModeTabs } from './components/layout/ModeTabs.jsx';
import { DashboardValidation } from './components/dashboard/DashboardValidation.jsx';
import { ExcelValidation } from './components/excel/ExcelValidation.jsx';

import './App.css';

function App() {
  const [mode, setMode] = useState('dashboard');
  const [theme, toggleTheme] = useTheme();
  const apiStatus = useApiHealth();

  return (
    <div className="dv-app" data-theme={theme}>
      <TopBar theme={theme} onToggleTheme={toggleTheme} apiStatus={apiStatus} />

      <div className="max-w-6xl mx-auto px-4 sm:px-8 pb-16">
        <Hero />

        <div className="max-w-4xl mx-auto">
          <div className="flex justify-center">
            <ModeTabs mode={mode} onModeChange={setMode} />
          </div>

          {mode === 'dashboard' ? <DashboardValidation /> : <ExcelValidation />}
        </div>
      </div>
    </div>
  );
}

export default App;

// #changes