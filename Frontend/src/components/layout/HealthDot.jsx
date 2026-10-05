import { Circle } from 'lucide-react';

export function HealthDot({ status }) {
  const label =
    status === 'online' ? 'API online' : status === 'offline' ? 'API unreachable' : 'Checking API…';
  const color = status === 'online' ? '#8DF0B0' : status === 'offline' ? '#FFE08A' : 'rgba(255,255,255,0.6)';

  return (
    <div
      className="flex items-center gap-1.5 px-2.5 py-1 rounded-full"
      style={{ background: 'rgba(0,0,0,0.18)' }}
      title={label}
    >
      <Circle className={status === 'checking' ? 'dv-pulse' : ''} style={{ width: 8, height: 8, color, fill: color }} />
      <span className="text-[11px] text-white/90 hidden sm:inline">{label}</span>
    </div>
  );
}