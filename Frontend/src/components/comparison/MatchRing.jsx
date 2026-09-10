export function MatchRing({ percentage }) {
  return (
    <div className="flex-shrink-0 relative flex items-center justify-center w-32 h-32">
      <svg className="w-full h-full -rotate-90" viewBox="0 0 36 36">
        <path
          strokeWidth="3"
          stroke="var(--border)"
          fill="none"
          d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831"
        />
        <path
          className="transition-all duration-1000 ease-out"
          strokeDasharray={`${percentage}, 100`}
          strokeWidth="3"
          strokeLinecap="round"
          stroke="var(--accent)"
          fill="none"
          d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831"
        />
      </svg>
      <div className="absolute flex flex-col items-center justify-center">
        <span className="dv-font-mono text-2xl font-bold" style={{ color: 'var(--text)' }}>
          {percentage}%
        </span>
        <span className="text-[10px] uppercase font-bold tracking-wider" style={{ color: 'var(--text-muted)' }}>
          Match
        </span>
      </div>
    </div>
  );
}
