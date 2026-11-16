import { Radar } from 'lucide-react';

export function Logo({ className = '' }: { className?: string }) {
  return (
    <div className={`flex items-center gap-2.5 ${className}`}>
      <div className="relative">
        <div className="absolute inset-0 bg-gradient-to-br from-emerald-400 to-cyan-500 rounded-lg blur-sm opacity-60" />
        <div className="relative bg-gradient-to-br from-emerald-400 to-cyan-500 rounded-lg p-1.5">
          <Radar className="w-5 h-5 text-white" strokeWidth={2.5} />
        </div>
      </div>
      <span className="text-lg font-bold text-white tracking-tight">
        Lead<span className="text-emerald-400">Sweep</span>
      </span>
    </div>
  );
}
