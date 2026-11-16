import { useState, useEffect } from 'react';
import {
  Calendar, Clock, Play, Plus,
  CheckCircle2, AlertCircle, RefreshCw,
} from 'lucide-react';
import { platforms } from '@/data/mockData';
import { PlatformIcon, formatDate } from '@/components/ui';
import type { PageId } from '@/App';
import { api } from '@/api/client';
import type { ScheduledTask } from '@/types';

export function SchedulePage({ onNavigate, user }: { onNavigate: (page: PageId) => void; user?: any }) {
  const [tasks, setTasks] = useState<ScheduledTask[]>([]);
  const [loading, setLoading] = useState(true);

  const userEmail = user?.email;

  const loadSchedules = () => {
    setLoading(true);
    api.getSchedules(userEmail)
      .then((data) => {
        setTasks(data || []);
      })
      .catch(() => {
        setTasks([]);
      })
      .finally(() => {
        setLoading(false);
      });
  };

  useEffect(() => {
    loadSchedules();
  }, [userEmail]);

  const toggleEnabled = (id: string) => {
    setTasks(tasks.map((t) => (t.id === id ? { ...t, enabled: !t.enabled } : t)));
  };

  const enabledCount = tasks.filter((t) => t.enabled).length;
  const totalRuns = tasks.reduce((sum, t) => sum + (t.lastRun ? 1 : 0), 0);
  const successRuns = tasks.filter((t) => t.lastStatus === 'completed').length;
  const failedRuns = tasks.filter((t) => t.lastStatus === 'failed').length;
  const successRate = totalRuns > 0 ? Math.round((successRuns / totalRuns) * 100) : 100;

  return (
    <div className="p-4 lg:p-6 space-y-6">
      <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-white">Scheduled Tasks</h1>
          <p className="text-sm text-gray-400 mt-1">
            {enabledCount} active · {tasks.length} total scheduled scrapers
          </p>
        </div>
        <div className="flex items-center gap-3">
          <button
            onClick={loadSchedules}
            disabled={loading}
            className="p-2.5 rounded-xl bg-gray-900 hover:bg-gray-800 text-gray-400 hover:text-white border border-gray-800 transition-colors"
            title="Refresh Schedules"
          >
            <RefreshCw size={16} className={loading ? 'animate-spin text-emerald-400' : ''} />
          </button>
          <button
            onClick={() => onNavigate('create')}
            className="flex items-center gap-2 bg-gradient-to-r from-emerald-500 to-cyan-500 hover:from-emerald-400 hover:to-cyan-400 px-4 py-2.5 rounded-xl font-semibold text-sm text-white transition-all shadow-lg shadow-emerald-500/20"
          >
            <Plus size={16} /> New Schedule
          </button>
        </div>
      </div>

      {/* Quick stats */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        {[
          { label: 'Active Schedules', value: enabledCount.toString(), icon: Calendar, color: 'text-emerald-400' },
          { label: 'Total Runs', value: totalRuns.toString(), icon: Play, color: 'text-cyan-400' },
          { label: 'Success Rate', value: `${successRate}%`, icon: CheckCircle2, color: 'text-sky-400' },
          { label: 'Failed Runs', value: failedRuns.toString(), icon: AlertCircle, color: 'text-amber-400' },
        ].map((stat) => {
          const Icon = stat.icon;
          return (
            <div key={stat.label} className="bg-gray-900 border border-gray-800 rounded-2xl p-5">
              <Icon className={`w-5 h-5 ${stat.color} mb-3`} />
              <p className="text-2xl font-bold text-white">{stat.value}</p>
              <p className="text-xs text-gray-400 mt-1">{stat.label}</p>
            </div>
          );
        })}
      </div>

      {/* Schedule list */}
      <div className="bg-gray-900 border border-gray-800 rounded-2xl overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full">
            <thead>
              <tr className="border-b border-gray-800 bg-gray-950/50">
                <th className="text-left text-xs font-semibold text-gray-500 uppercase tracking-wider px-4 py-3">Task Name</th>
                <th className="text-left text-xs font-semibold text-gray-500 uppercase tracking-wider px-4 py-3 hidden md:table-cell">Platform</th>
                <th className="text-left text-xs font-semibold text-gray-500 uppercase tracking-wider px-4 py-3">Interval</th>
                <th className="text-left text-xs font-semibold text-gray-500 uppercase tracking-wider px-4 py-3 hidden lg:table-cell">Next Run</th>
                <th className="text-left text-xs font-semibold text-gray-500 uppercase tracking-wider px-4 py-3 hidden sm:table-cell">Last Run</th>
                <th className="text-left text-xs font-semibold text-gray-500 uppercase tracking-wider px-4 py-3">Status</th>
              </tr>
            </thead>
            <tbody>
              {loading && tasks.length === 0 ? (
                <tr>
                  <td colSpan={6} className="py-12 text-center text-gray-500">
                    <RefreshCw className="animate-spin mx-auto mb-2 text-emerald-400" size={20} />
                    Loading your scheduled tasks...
                  </td>
                </tr>
              ) : tasks.length === 0 ? (
                <tr>
                  <td colSpan={6} className="py-12 text-center text-gray-500">
                    <Calendar className="mx-auto mb-3 text-gray-600" size={32} />
                    <p className="text-sm font-medium text-gray-400">No scheduled scrapers yet</p>
                    <p className="text-xs text-gray-500 mt-1">Create a schedule or run a scraping job to see it listed here.</p>
                  </td>
                </tr>
              ) : (
                tasks.map((task) => {
                  const platform = platforms.find((p) => p.id === task.platform);
                  return (
                    <tr key={task.id} className="border-b border-gray-800/50 hover:bg-gray-800/30 transition-colors">
                      <td className="px-4 py-4">
                        <div className="flex items-center gap-2">
                          <Calendar size={14} className={task.enabled ? 'text-emerald-400' : 'text-gray-600'} />
                          <div>
                            <p className="text-sm font-medium text-white">{task.name}</p>
                            <p className="text-xs text-gray-500">{task.itemsPerRun.toLocaleString()} items/run</p>
                          </div>
                        </div>
                      </td>
                      <td className="px-4 py-4 hidden md:table-cell">
                        <div className="flex items-center gap-2">
                          <div className={`w-7 h-7 rounded-lg ${platform?.bgColor} flex items-center justify-center`}>
                            <PlatformIcon platform={task.platform} className={`w-4 h-4 ${platform?.color}`} />
                          </div>
                          <span className="text-xs text-gray-400">{platform?.name}</span>
                        </div>
                      </td>
                      <td className="px-4 py-4">
                        <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md bg-gray-800 text-xs font-medium text-white capitalize">
                          <Clock size={12} className="text-gray-400" />{task.interval}
                        </span>
                      </td>
                      <td className="px-4 py-4 hidden lg:table-cell">
                        <span className="text-xs text-gray-300">{formatDate(task.nextRun)}</span>
                      </td>
                      <td className="px-4 py-4 hidden sm:table-cell">
                        {task.lastRun ? (
                          <div className="flex items-center gap-2">
                            <span className="text-xs text-gray-300">{formatDate(task.lastRun)}</span>
                            {task.lastStatus === 'completed' ? <CheckCircle2 size={12} className="text-emerald-400" /> : null}
                          </div>
                        ) : (
                          <span className="text-xs text-gray-500">Never</span>
                        )}
                      </td>
                      <td className="px-4 py-4">
                        <button
                          onClick={() => toggleEnabled(task.id)}
                          className={`relative w-11 h-6 rounded-full transition-colors ${task.enabled ? 'bg-emerald-500' : 'bg-gray-700'}`}
                        >
                          <div className="absolute top-0.5 w-5 h-5 rounded-full bg-white transition-transform" style={{ transform: task.enabled ? 'translateX(22px)' : 'translateX(2px)' }} />
                        </button>
                      </td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
