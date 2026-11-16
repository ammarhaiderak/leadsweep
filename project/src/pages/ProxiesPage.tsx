import { useState, useEffect } from 'react';
import { Globe, Activity, Zap, Shield, TrendingUp, Server } from 'lucide-react';
import { proxies as mockProxies } from '@/data/mockData';
import { api } from '@/api/client';
import type { ProxyNode } from '@/types';

export function ProxiesPage() {
  const [proxyList, setProxyList] = useState<ProxyNode[]>(mockProxies);

  useEffect(() => {
    let mounted = true;
    async function load() {
      try {
        const live = await api.getProxies();
        if (mounted && live && live.length > 0) {
          setProxyList(live);
        }
      } catch (err) {
        console.error('Failed to load live proxies:', err);
      }
    }
    load();
    return () => { mounted = false; };
  }, []);

  const activeCount = proxyList.filter((p) => p.status === 'active').length;
  const idleCount = proxyList.filter((p) => p.status === 'idle').length;
  const errorCount = proxyList.filter((p) => p.status === 'error').length;
  const totalRequests = proxyList.reduce((a, b) => a + b.requests, 0);
  const avgSuccess = (proxyList.reduce((a, b) => a + b.successRate, 0) / Math.max(proxyList.length, 1)).toFixed(1);

  const statusConfig: Record<string, { label: string; color: string; dot: string }> = {
    active: { label: 'Active', color: 'text-emerald-400 bg-emerald-500/10 border-emerald-500/30', dot: 'bg-emerald-400 animate-pulse' },
    idle: { label: 'Idle', color: 'text-amber-400 bg-amber-500/10 border-amber-500/30', dot: 'bg-amber-400' },
    error: { label: 'Error', color: 'text-red-400 bg-red-500/10 border-red-500/30', dot: 'bg-red-400' },
  };

  return (
    <div className="p-4 lg:p-6 space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-white">Proxy Network</h1>
        <p className="text-sm text-gray-400 mt-1">Monitor your proxy pool across 50+ regions worldwide</p>
      </div>

      {/* Stats */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        {[
          { label: 'Active Nodes', value: activeCount.toString(), icon: Activity, color: 'from-emerald-500/20 to-emerald-500/5', text: 'text-emerald-400', border: 'border-emerald-500/20' },
          { label: 'Total Requests', value: (totalRequests / 1000).toFixed(1) + 'K', icon: Zap, color: 'from-cyan-500/20 to-cyan-500/5', text: 'text-cyan-400', border: 'border-cyan-500/20' },
          { label: 'Avg Success Rate', value: `${avgSuccess}%`, icon: TrendingUp, color: 'from-sky-500/20 to-sky-500/5', text: 'text-sky-400', border: 'border-sky-500/20' },
          { label: 'Error Nodes', value: errorCount.toString(), icon: Shield, color: 'from-red-500/20 to-red-500/5', text: 'text-red-400', border: 'border-red-500/20' },
        ].map((stat) => {
          const Icon = stat.icon;
          return (
            <div key={stat.label} className={`bg-gradient-to-br ${stat.color} border ${stat.border} rounded-2xl p-5`}>
              <Icon className={`w-5 h-5 ${stat.text} mb-3`} />
              <p className="text-2xl font-bold text-white">{stat.value}</p>
              <p className="text-xs text-gray-400 mt-1">{stat.label}</p>
            </div>
          );
        })}
      </div>

      {/* World map placeholder with region dots */}
      <div className="bg-gray-900 border border-gray-800 rounded-2xl p-6">
        <h2 className="text-base font-bold text-white flex items-center gap-2 mb-5">
          <Globe size={18} className="text-emerald-400" /> Global Proxy Map
        </h2>
        <div className="relative h-64 bg-gray-950 rounded-xl overflow-hidden flex items-center justify-center">
          <div className="absolute inset-0 bg-[linear-gradient(rgba(255,255,255,0.03)_1px,transparent_1px),linear-gradient(90deg,rgba(255,255,255,0.03)_1px,transparent_1px)] bg-[size:30px_30px]" />
          {/* Region dots */}
          {proxyList.map((p, i) => {
            const positions = [
              { top: '35%', left: '25%' }, { top: '38%', left: '18%' }, { top: '30%', left: '50%' },
              { top: '25%', left: '52%' }, { top: '40%', left: '80%' }, { top: '50%', left: '72%' },
              { top: '65%', left: '35%' }, { top: '75%', left: '82%' }, { top: '28%', left: '47%' },
              { top: '35%', left: '28%' },
            ];
            const pos = positions[i] || { top: '50%', left: '50%' };
            const colors = { active: 'bg-emerald-400', idle: 'bg-amber-400', error: 'bg-red-400' };
            return (
              <div key={p.id} className="absolute group" style={pos}>
                <div className={`w-3 h-3 rounded-full ${colors[p.status]} ${p.status === 'active' ? 'animate-pulse' : ''} ring-4 ring-opacity-20`} style={{ boxShadow: `0 0 12px ${p.status === 'active' ? 'rgba(52,211,153,0.4)' : p.status === 'error' ? 'rgba(248,113,113,0.4)' : 'rgba(251,191,36,0.3)'}` }} />
                <div className="absolute bottom-full left-1/2 -translate-x-1/2 mb-2 hidden group-hover:block whitespace-nowrap bg-gray-950 border border-gray-700 rounded-lg px-2.5 py-1.5 text-xs text-white z-10">
                  {p.city}, {p.region}
                </div>
              </div>
            );
          })}
          <div className="relative text-center">
            <Server className="w-12 h-12 text-gray-800 mx-auto mb-2" />
            <p className="text-xs text-gray-600">Hover over nodes for details</p>
          </div>
        </div>
      </div>

      {/* Proxy nodes table */}
      <div className="bg-gray-900 border border-gray-800 rounded-2xl overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full">
            <thead>
              <tr className="border-b border-gray-800 bg-gray-950/50">
                <th className="text-left text-xs font-semibold text-gray-500 uppercase tracking-wider px-4 py-3">Region</th>
                <th className="text-left text-xs font-semibold text-gray-500 uppercase tracking-wider px-4 py-3 hidden sm:table-cell">City</th>
                <th className="text-left text-xs font-semibold text-gray-500 uppercase tracking-wider px-4 py-3">Status</th>
                <th className="text-right text-xs font-semibold text-gray-500 uppercase tracking-wider px-4 py-3">Requests</th>
                <th className="text-right text-xs font-semibold text-gray-500 uppercase tracking-wider px-4 py-3 hidden md:table-cell">Success Rate</th>
                <th className="text-right text-xs font-semibold text-gray-500 uppercase tracking-wider px-4 py-3 hidden lg:table-cell">Avg Latency</th>
              </tr>
            </thead>
            <tbody>
              {proxyList.map((p) => {
                const config = statusConfig[p.status];
                return (
                  <tr key={p.id} className="border-b border-gray-800/50 hover:bg-gray-800/30 transition-colors">
                    <td className="px-4 py-4">
                      <div className="flex items-center gap-2">
                        <Globe size={14} className="text-gray-500" />
                        <span className="text-sm font-medium text-white">{p.region}</span>
                      </div>
                    </td>
                    <td className="px-4 py-4 hidden sm:table-cell">
                      <span className="text-sm text-gray-400">{p.city}</span>
                    </td>
                    <td className="px-4 py-4">
                      <span className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium border ${config.color}`}>
                        <span className={`w-1.5 h-1.5 rounded-full ${config.dot}`} />
                        {config.label}
                      </span>
                    </td>
                    <td className="px-4 py-4 text-right">
                      <span className="text-sm text-white font-medium">{p.requests.toLocaleString()}</span>
                    </td>
                    <td className="px-4 py-4 text-right hidden md:table-cell">
                      <div className="flex items-center justify-end gap-2">
                        <div className="w-16 h-1.5 bg-gray-800 rounded-full overflow-hidden">
                          <div className={`h-full rounded-full ${p.successRate > 99 ? 'bg-emerald-500' : p.successRate > 95 ? 'bg-amber-500' : 'bg-red-500'}`} style={{ width: `${p.successRate}%` }} />
                        </div>
                        <span className="text-xs text-gray-300 w-12">{p.successRate}%</span>
                      </div>
                    </td>
                    <td className="px-4 py-4 text-right hidden lg:table-cell">
                      <span className="text-sm text-gray-400">{p.avgLatency}ms</span>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
