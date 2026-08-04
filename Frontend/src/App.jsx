import { useState } from 'react';
import { 
  Gauge, 
  Globe, 
  Clock3, 
  Camera, 
  Server, 
  Activity, 
  AlertTriangle, 
  CheckCircle2, 
  BarChart3, 
  Monitor, 
  PlayCircle, 
  Loader2, 
  Search,
  ShieldCheck,
  AlertCircle
} from 'lucide-react';
import './App.css';

const API_URL = 'http://localhost:8000/api/validate';

// --- Reusable UI Components ---

function Header() {
  return (
    <div className="text-center mb-10 animate-in fade-in slide-in-from-top-4 duration-700">
      <div className="flex justify-center items-center gap-3 mb-3">
        <div className="p-3 bg-indigo-500/20 rounded-2xl border border-indigo-500/30 shadow-[0_0_15px_rgba(99,102,241,0.2)]">
          <Gauge className="w-8 h-8 text-indigo-400" />
        </div>
        <h1 className="text-4xl font-extrabold text-transparent bg-clip-text bg-gradient-to-r from-white via-slate-200 to-indigo-200">
          Dashboard Metrics Validator
        </h1>
      </div>
      <p className="text-lg text-slate-400 font-medium">
        Compare Power BI dashboards and validate performance metrics.
      </p>
    </div>
  );
}

function ValidationForm({ sourceUrl, setSourceUrl, targetUrl, setTargetUrl, handleSubmit, loading }) {
  return (
    <div className="bg-white/5 backdrop-blur-xl border border-white/10 p-6 md:p-8 rounded-3xl shadow-2xl animate-in fade-in zoom-in-95 duration-500">
      <form onSubmit={handleSubmit} className="space-y-6">
        <div className="grid md:grid-cols-2 gap-6">
          <div className="space-y-2">
            <label className="flex items-center gap-2 text-sm font-semibold text-slate-300 ml-1">
              <Monitor className="w-4 h-4 text-indigo-400" />
              Source Dashboard URL
            </label>
            <input
              type="text"
              value={sourceUrl}
              onChange={(e) => setSourceUrl(e.target.value)}
              placeholder="https://app.powerbi.com/..."
              className="w-full px-4 py-3 rounded-xl bg-slate-900/50 border border-slate-700/50 text-slate-100 placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-indigo-500/50 focus:border-indigo-500 transition-all duration-300 hover:bg-slate-900/80"
            />
          </div>

          <div className="space-y-2">
            <label className="flex items-center gap-2 text-sm font-semibold text-slate-300 ml-1">
              <Monitor className="w-4 h-4 text-indigo-400" />
              Target Dashboard URL
            </label>
            <input
              type="text"
              value={targetUrl}
              onChange={(e) => setTargetUrl(e.target.value)}
              placeholder="https://app.powerbi.com/..."
              className="w-full px-4 py-3 rounded-xl bg-slate-900/50 border border-slate-700/50 text-slate-100 placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-indigo-500/50 focus:border-indigo-500 transition-all duration-300 hover:bg-slate-900/80"
            />
          </div>
        </div>

        <div className="flex justify-center pt-2">
          <button
            type="submit"
            disabled={loading}
            className="group relative inline-flex items-center justify-center gap-2 px-8 py-3.5 bg-gradient-to-r from-indigo-500 to-indigo-600 hover:from-indigo-400 hover:to-indigo-500 text-white font-semibold rounded-xl transition-all duration-300 hover:scale-105 hover:shadow-[0_0_20px_rgba(99,102,241,0.4)] disabled:opacity-50 disabled:pointer-events-none w-full md:w-auto min-w-[200px]"
          >
            {loading ? (
              <>
                <Loader2 className="w-5 h-5 animate-spin" />
                <span>Validating Metrics...</span>
              </>
            ) : (
              <>
                <PlayCircle className="w-5 h-5 group-hover:scale-110 transition-transform duration-300" />
                <span>Run Validation</span>
              </>
            )}
          </button>
        </div>
      </form>
    </div>
  );
}

function MetricCard({ icon: Icon, label, value, unit = '', alert = false }) {
  return (
    <div className="bg-white/5 border border-white/5 p-4 rounded-2xl hover:bg-white/10 hover:scale-[1.02] hover:shadow-xl transition-all duration-300 group flex items-start gap-4">
      <div className={`p-2.5 rounded-xl border ${alert ? 'bg-red-500/10 border-red-500/20 text-red-400' : 'bg-slate-800/50 border-slate-700/50 text-indigo-400'} group-hover:scale-110 transition-transform duration-300`}>
        <Icon className="w-5 h-5" />
      </div>
      <div>
        <p className="text-xs font-medium text-slate-400 mb-1">{label}</p>
        <p className={`text-lg font-bold ${alert ? 'text-red-400' : 'text-slate-100'}`}>
          {value}
          <span className="text-sm font-normal text-slate-500 ml-1">{unit}</span>
        </p>
      </div>
    </div>
  );
}

function MetricsSection({ metrics }) {
  return (
    <div className="space-y-6 animate-in fade-in slide-in-from-bottom-8 duration-700 delay-100 fill-mode-both">
      <div className="flex items-center gap-2 mb-6">
        <BarChart3 className="w-6 h-6 text-indigo-400" />
        <h2 className="text-2xl font-bold text-slate-100">Performance Metrics</h2>
      </div>
      
      <div className="grid lg:grid-cols-2 gap-6">
        {metrics.map((m, i) => (
          <div key={i} className="bg-white/5 backdrop-blur-xl border border-white/10 p-6 rounded-3xl shadow-xl hover:border-indigo-500/30 transition-colors duration-500">
            {m ? (
              <>
                <div className="flex items-center gap-3 mb-6 pb-4 border-b border-white/10">
                  <div className="p-2 bg-indigo-500/20 rounded-lg">
                    <Monitor className="w-5 h-5 text-indigo-300" />
                  </div>
                  <div>
                    <h3 className="text-lg font-bold text-white leading-tight">
                      {m.dashboard_name || `Dashboard ${i + 1}`}
                    </h3>
                    <p className="text-sm text-slate-400 truncate max-w-[250px]" title={m.page_title}>
                      {m.page_title}
                    </p>
                  </div>
                </div>

                <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                  <MetricCard icon={Server} label="HTTP Status" value={m.http_status} />
                  <MetricCard icon={Globe} label="Browser Launch" value={m.browser_launch_seconds} unit="s" />
                  <MetricCard icon={Clock3} label="Page Load" value={m.page_load_seconds} unit="s" />
                  <MetricCard icon={Monitor} label="Dashboard Render" value={m.dashboard_render_seconds} unit="s" />
                  <MetricCard icon={Camera} label="Screenshot Time" value={m.screenshot_seconds} unit="s" />
                  <MetricCard icon={Activity} label="Total Execution" value={m.total_execution_seconds} unit="s" />
                  <MetricCard icon={BarChart3} label="Total Requests" value={m.total_requests} />
                  <MetricCard icon={AlertTriangle} label="Failed Requests" value={m.failed_requests} alert={m.failed_requests > 0} />
                  <MetricCard icon={Search} label="Console Messages" value={m.console_messages} />
                  <MetricCard icon={AlertCircle} label="Page Errors" value={m.page_errors} alert={m.page_errors > 0} />
                </div>
              </>
            ) : (
              <div className="h-full flex flex-col items-center justify-center p-8 text-center bg-red-500/5 rounded-2xl border border-red-500/10">
                <AlertTriangle className="w-12 h-12 text-red-400 mb-4 opacity-80" />
                <h3 className="text-lg font-bold text-red-400 mb-2">Validation Failed</h3>
                <p className="text-sm text-red-400/80">
                  Dashboard {i + 1} failed to run. Check the backend logs for more details.
                </p>
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

function StatusBadge({ status }) {
  const isMatch = status === 'Match';
  const isNearMatch = status === 'Near Match';
  
  return (
    <div className={`inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-semibold border ${
      isMatch ? 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20' : 
      isNearMatch ? 'bg-amber-500/10 text-amber-400 border-amber-500/20' : 
      'bg-red-500/10 text-red-400 border-red-500/20'
    }`}>
      {isMatch ? <CheckCircle2 className="w-3.5 h-3.5" /> : 
       isNearMatch ? <AlertTriangle className="w-3.5 h-3.5" /> : 
       <AlertCircle className="w-3.5 h-3.5" />}
      {status}
    </div>
  );
}

function ComparisonSection({ comparison }) {
  return (
    <div className="space-y-8 animate-in fade-in slide-in-from-bottom-8 duration-700 delay-200 fill-mode-both">
      <div className="flex flex-col md:flex-row gap-6 items-center bg-white/5 backdrop-blur-xl border border-white/10 p-6 rounded-3xl shadow-xl">
        <div className="flex-shrink-0 relative flex items-center justify-center w-32 h-32">
          <svg className="w-full h-full -rotate-90" viewBox="0 0 36 36">
            <path
              className="text-slate-800"
              strokeWidth="3"
              stroke="currentColor"
              fill="none"
              d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831"
            />
            <path
              className="text-indigo-500 transition-all duration-1000 ease-out"
              strokeDasharray={`${comparison.match_percentage}, 100`}
              strokeWidth="3"
              strokeLinecap="round"
              stroke="currentColor"
              fill="none"
              d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831"
            />
          </svg>
          <div className="absolute flex flex-col items-center justify-center">
            <span className="text-3xl font-extrabold text-white">{comparison.match_percentage}%</span>
            <span className="text-[10px] uppercase font-bold tracking-wider text-slate-400">Match</span>
          </div>
        </div>
        
        <div>
          <h2 className="text-2xl font-bold text-white mb-2 flex items-center gap-2">
            <ShieldCheck className="w-6 h-6 text-indigo-400" />
            KPI Comparison
          </h2>
          <p className="text-slate-400 text-sm leading-relaxed max-w-2xl">
            Detailed breakdown of metric comparisons between the source and target dashboards. 
            Green indicates identical values, yellow highlights minor variances, and red signifies significant discrepancies.
          </p>
        </div>
      </div>

      <div className="bg-white/5 backdrop-blur-xl border border-white/10 rounded-3xl shadow-xl overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-sm text-left">
            <thead className="bg-slate-900/80 backdrop-blur-md text-slate-300 border-b border-white/10">
              <tr>
                <th className="p-5 font-semibold">KPI / Metric Name</th>
                <th className="p-5 font-semibold">Source Dashboard</th>
                <th className="p-5 font-semibold">Target Dashboard</th>
                <th className="p-5 font-semibold">Validation Status</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-white/5">
              {comparison.results.map((r, i) => (
                <tr key={i} className="group hover:bg-white/[0.02] transition-colors duration-200">
                  <td className="p-5 font-medium text-slate-200">{r.kpi}</td>
                  <td className="p-5 text-slate-400">{r.source ?? '—'}</td>
                  <td className="p-5 text-slate-400">{r.target ?? '—'}</td>
                  <td className="p-5">
                    <StatusBadge status={r.status} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

// --- Main App Component ---

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
      console.log(result,"surya");
    } catch (err) {
      setError(err.message || 'Something went wrong while validating.');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-950 via-slate-900 to-indigo-950 text-slate-100 p-4 sm:p-8 font-sans selection:bg-indigo-500/30">
      <div className="max-w-6xl mx-auto space-y-8">
        
        <Header />

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

        {error && (
          <div className="max-w-4xl mx-auto animate-in fade-in slide-in-from-top-2 duration-300">
            <div className="flex items-center gap-3 p-4 bg-red-500/10 border border-red-500/20 rounded-2xl text-red-200">
              <AlertTriangle className="w-5 h-5 text-red-400 flex-shrink-0" />
              <p className="font-medium text-sm">{error}</p>
            </div>
          </div>
        )}

        {result && (
          <div className="mt-12 space-y-12">
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

export default App;