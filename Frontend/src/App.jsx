import { useState } from 'react';
import { API_URL } from './config';
import { useTheme } from './hooks/useTheme.js';
import { useApiHealth } from './hooks/useApiHealth.js';
import { useMismatchFallback } from './hooks/useMismatchFallback.js';

import { TopBar } from './components/layout/TopBar.jsx';
import { Hero } from './components/layout/Hero.jsx';
import { ValidationForm } from './components/form/ValidationForm.jsx';
import { ErrorBanner } from './components/form/ErrorBanner.jsx';
import { MetricsSection } from './components/metrics/MetricsSection.jsx';
import { AppliedFiltersSection } from './components/comparison/AppliedFiltersSection.jsx';
import { TablesComparisonSection } from './components/comparison/TablesComparisonSection.jsx';
import { VisualResultsSection } from './components/comparison/VisualResultsSection.jsx';

import './App.css';

function App() {
  const [sourceUrl, setSourceUrl] = useState('');
  const [targetUrl, setTargetUrl] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [result, setResult] = useState(null);

  const [theme, toggleTheme] = useTheme();
  const apiStatus = useApiHealth();
  useMismatchFallback(result, setResult);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError('');
    setResult(null);

    if (!sourceUrl.trim() || !targetUrl.trim()) {
      setError('Please enter both dashboard URLs.');
      return;
    }

    setLoading(true);
    try {
      const response = await fetch(API_URL, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          source_url: sourceUrl.trim(),
          target_url: targetUrl.trim(),
        }),
      });

      if (!response.ok) {
        const errData = await response.json().catch(() => ({}));
        throw new Error(errData.detail || `Request failed with status ${response.status}`);
      }

      const data = await response.json();
      console.log('Validation result:', data);
      setResult(data);
    } catch (err) {
      setError(err.message || 'Something went wrong while validating.');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="dv-app" data-theme={theme}>
      <TopBar theme={theme} onToggleTheme={toggleTheme} apiStatus={apiStatus} />

      <div className="max-w-6xl mx-auto px-4 sm:px-8 pb-16">
        <Hero />

        <div className="max-w-4xl mx-auto">
          <ValidationForm
            sourceUrl={sourceUrl}
            setSourceUrl={setSourceUrl}
            targetUrl={targetUrl}
            setTargetUrl={setTargetUrl}
            handleSubmit={handleSubmit}
            loading={loading}
          />
        </div>

        <ErrorBanner message={error} />

        {result && (
          <div className="mt-12 space-y-12">
            <MetricsSection metrics={result.metrics} />

            {result.applied_filter_selections && (
              <AppliedFiltersSection
                appliedFilters={result.applied_filter_selections}
                mismatches={result.mismatches}
              />
            )}

            {result.comparison?.tables && (
              <TablesComparisonSection tables={result.comparison.tables} />
            )}

            {(result.visual_results || result.kpis) && (
              <VisualResultsSection
                visualResults={result.visual_results}
                kpis={result.kpis}
                comparisonVisuals={result.comparison?.visuals}
              />
            )}
          </div>
        )}
      </div>
    </div>
  );
}

export default App;