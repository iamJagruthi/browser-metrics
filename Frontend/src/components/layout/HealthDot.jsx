import { Circle } from 'lucide-react';

export function HealthDot({ status }) {
  const label =
    status === 'online' ? 'API online' : status === 'offline' ? 'API unreachable' : 'Checking API…';
  const color = status === 'online' ? '#F5C518' : status === 'offline' ? '#EF6259' : 'rgba(255,255,255,0.4)';

  return (
    <div
      className="flex items-center gap-1.5 px-2.5 py-1 rounded-full"
      style={{ background: 'rgba(255,255,255,0.08)' }}
      title={label}
    >
      <Circle className={status === 'checking' ? 'dv-pulse' : ''} style={{ width: 8, height: 8, color, fill: color }} />
      <span className="text-[11px] text-white/60 hidden sm:inline">{label}</span>
    </div>
  );
}
