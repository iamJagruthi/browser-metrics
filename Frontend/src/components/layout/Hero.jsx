export function Hero() {
  return (
    <div className="text-center mb-10 mt-10 animate-in fade-in slide-in-from-top-4 duration-700">
      <p className="dv-font-mono text-xs tracking-[0.2em] uppercase mb-3" style={{ color: 'var(--accent-text)' }}>
        Power BI · Pipeline QA
      </p>
      <h1 className="dv-font-display text-4xl sm:text-5xl font-bold mb-3" style={{ color: 'var(--text)' }}>
        Dashboard Metrics Validator
      </h1>
      <p className="text-base" style={{ color: 'var(--text-muted)' }}>
        Run two Power BI dashboards side by side and confirm the KPIs still match.
      </p>
    </div>
  );
}
