import { useState } from 'react';
import './App.css';

const API_URL = 'http://localhost:8000/api/validate';

function App() {
  const [sourceUrl, setSourceUrl] = useState('');
  const [targetUrl, setTargetUrl] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [result, setResult] = useState(null);

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
        throw new Error(
          errData.detail || `Request failed with status ${response.status}`
        );
      }

      const data = await response.json();
      setResult(data);
    } catch (err) {
      setError(err.message || 'Something went wrong while validating.');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen bg-slate-900 text-slate-100 p-8">
      <div className="max-w-4xl mx-auto">
        <h1 className="text-3xl font-bold text-green-400 mb-6">
          Dashboard Metrics Validator
        </h1>

        <form
          onSubmit={handleSubmit}
          className="bg-slate-800 p-6 rounded-lg space-y-4"
        >
          <div>
            <label className="block mb-1 text-sm text-slate-300">
              Source Dashboard URL
            </label>
            <input
              type="text"
              value={sourceUrl}
              onChange={(e) => setSourceUrl(e.target.value)}
              placeholder="https://app.powerbi.com/..."
              className="w-full p-2 rounded bg-slate-700 border border-slate-600 focus:outline-none focus:ring-2 focus:ring-green-400"
            />
          </div>

          <div>
            <label className="block mb-1 text-sm text-slate-300">
              Target Dashboard URL
            </label>
            <input
              type="text"
              value={targetUrl}
              onChange={(e) => setTargetUrl(e.target.value)}
              placeholder="https://app.powerbi.com/..."
              className="w-full p-2 rounded bg-slate-700 border border-slate-600 focus:outline-none focus:ring-2 focus:ring-green-400"
            />
          </div>

          <button
            type="submit"
            disabled={loading}
            className="bg-green-500 hover:bg-green-600 disabled:opacity-50 text-slate-900 font-semibold px-4 py-2 rounded transition-colors"
          >
            {loading ? 'Validating...' : 'Run Validation'}
          </button>
        </form>

        {error && (
          <div className="mt-4 p-3 bg-red-900/50 border border-red-500 rounded text-red-200">
            {error}
          </div>
        )}

        {result && (
          <div className="mt-8 space-y-8">
            <MetricsSection metrics={result.metrics} />
            {result.comparison && (
              <ComparisonSection comparison={result.comparison} />
            )}
          </div>
        )}
      </div>
    </div>
  );
}

function MetricsSection({ metrics }) {
  return (
    <div>
      <h2 className="text-xl font-semibold text-green-400 mb-3">Metrics</h2>
      <div className="grid md:grid-cols-2 gap-4">
        {metrics.map((m, i) => (
          <div key={i} className="bg-slate-800 p-4 rounded-lg">
            {m ? (
              <>
                <h3 className="font-semibold text-slate-100 mb-2">
                  {m.dashboard_name}
                </h3>
                <ul className="text-sm text-slate-300 space-y-1">
                  <li>Page Title: {m.page_title}</li>
                  <li>HTTP Status: {m.http_status}</li>
                  <li>Browser Launch: {m.browser_launch_seconds}s</li>
                  <li>Page Load: {m.page_load_seconds}s</li>
                  <li>Render: {m.dashboard_render_seconds}s</li>
                  <li>Screenshot: {m.screenshot_seconds}s</li>
                  <li>Total Execution: {m.total_execution_seconds}s</li>
                  <li>Total Requests: {m.total_requests}</li>
                  <li>Failed Requests: {m.failed_requests}</li>
                  <li>Console Messages: {m.console_messages}</li>
                  <li>Page Errors: {m.page_errors}</li>
                </ul>
              </>
            ) : (
              <p className="text-red-300">
                Dashboard {i + 1} failed to run. Check the backend logs.
              </p>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

function ComparisonSection({ comparison }) {
  return (
    <div>
      <h2 className="text-xl font-semibold text-green-400 mb-3">
        KPI Comparison — {comparison.match_percentage}% match
      </h2>
      <div className="overflow-x-auto bg-slate-800 rounded-lg">
        <table className="w-full text-sm text-left">
          <thead className="bg-slate-700 text-slate-200">
            <tr>
              <th className="p-3">KPI</th>
              <th className="p-3">Source</th>
              <th className="p-3">Target</th>
              <th className="p-3">Status</th>
            </tr>
          </thead>
          <tbody>
            {comparison.results.map((r, i) => (
              <tr key={i} className="border-t border-slate-700">
                <td className="p-3">{r.kpi}</td>
                <td className="p-3">{r.source ?? '—'}</td>
                <td className="p-3">{r.target ?? '—'}</td>
                <td
                  className={`p-3 font-medium ${
                    r.status === 'Match'
                      ? 'text-green-400'
                      : r.status === 'Near Match'
                      ? 'text-yellow-400'
                      : 'text-red-400'
                  }`}
                >
                  {r.status}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export default App;