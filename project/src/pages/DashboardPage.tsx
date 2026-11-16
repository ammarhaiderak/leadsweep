import { useEffect, useState } from 'react';
import {
  Database, Activity, TrendingUp, Zap, ArrowRight, Clock, Users,
  Play, Pause, AlertCircle, CheckCircle2, Loader2, BarChart3,
} from 'lucide-react';
import { platforms } from '@/data/mockData';
import { PlatformIcon, StatusBadge, formatNumber, timeAgo } from '@/components/ui';
import { api, type OverviewStats } from '@/api/client';
import type { ScraperJob, ScrapedItem } from '@/types';
import type { PageId } from '@/App';

export function DashboardPage({ onNavigate, user }: { onNavigate: (page: PageId) => void; user?: any }) {
  const [statsData, setStatsData] = useState<OverviewStats>({
    totalJobs: 0,
    activeJobs: 0,
    itemsScraped: 0,
    platformsConnected: 8,
    successRate: 0,
    monthlyCost: 0,
    computeUsed: 0,
    computeLimit: 10,
    storageUsed: 0,
    storageLimit: 10,
  });
  const [jobsData, setJobsData] = useState<ScraperJob[]>([]);
  const [itemsData, setItemsData] = useState<ScrapedItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [now, setNow] = useState(Date.now());

  const userEmail = user?.email;
  const displayName = user?.name || (userEmail ? userEmail.split('@')[0] : 'User');

  useEffect(() => {
    let mounted = true;
    async function loadData() {
      try {
        const [statsRes, jobsRes, dataRes] = await Promise.all([
          api.getOverviewStats(userEmail),
          api.getJobs(undefined, userEmail),
          api.getScrapedData({ limit: 5, user_email: userEmail }),
        ]);
        if (!mounted) return;
        setStatsData(statsRes);
        setJobsData(jobsRes || []);
        setItemsData(dataRes.items || []);
        setNow(Date.now());
      } catch (err) {
        console.error('Failed to load dashboard data from backend:', err);
      } finally {
        if (mounted) setLoading(false);
      }
    }
    loadData();
    const interval = setInterval(loadData, 2000);
    return () => {
      mounted = false;
      clearInterval(interval);
    };
  }, [userEmail]);

  const formatElapsed = (startedAt: string) => {
    const diffMs = Math.max(0, now - new Date(startedAt).getTime());
    const totalSec = Math.floor(diffMs / 1000);
    const m = Math.floor(totalSec / 60);
    const s = totalSec % 60;
    return `${m}m ${s < 10 ? '0' : ''}${s}s`;
  };

  const runningJobs = jobsData.filter((j) => j.status === 'running');
  const recentJobs = jobsData.slice(0, 6);
  const recentItems = itemsData.slice(0, 5);

  const isAdmin = Boolean(user && (user.role === 'admin' || user.role === 'owner'));

  return (
    <div className="p-4 lg:p-6 space-y-6">
      {/* Welcome banner */}
      <div className={`relative bg-gradient-to-br ${isAdmin ? 'from-emerald-500/15 via-cyan-500/10 to-blue-500/5 border-emerald-500/30' : 'from-emerald-500/10 to-cyan-500/5 border-emerald-500/20'} border rounded-2xl p-6 overflow-hidden`}>
        <div className="absolute inset-0 bg-[linear-gradient(rgba(255,255,255,0.02)_1px,transparent_1px),linear-gradient(90deg,rgba(255,255,255,0.02)_1px,transparent_1px)] bg-[size:24px_24px]" />
        <div className="relative flex flex-col lg:flex-row items-start lg:items-center justify-between gap-4">
          <div>
            <div className="flex items-center gap-2 mb-1.5">
              <h1 className="text-2xl font-bold text-white">Welcome back, {displayName}</h1>
              {isAdmin ? (
                <span className="px-2.5 py-0.5 rounded-full text-xs font-semibold bg-emerald-500/20 text-emerald-300 border border-emerald-500/30 uppercase tracking-wide">
                  System Master View
                </span>
              ) : (
                <span className="px-2.5 py-0.5 rounded-full text-xs font-semibold bg-cyan-500/20 text-cyan-300 border border-cyan-500/30">
                  Personal Workspace
                </span>
              )}
            </div>
            <p className="text-sm text-gray-400">
              {isAdmin ? (
                <>
                  Platform Infrastructure: <span className="text-emerald-400 font-semibold">{runningJobs.length} active jobs</span>,{' '}
                  <span className="text-cyan-400 font-semibold">{formatNumber(statsData.itemsScraped)} records collected</span> across{' '}
                  <span className="text-white font-medium">{statsData.totalJobs} total platform runs</span>.
                </>
              ) : (
                <>
                  Your workspace has <span className="text-emerald-400 font-medium">{runningJobs.length} active jobs</span> and{' '}
                  <span className="text-cyan-400 font-medium">{formatNumber(statsData.itemsScraped)} records</span> collected total.
                </>
              )}
            </p>
          </div>
          <div className="flex items-center gap-3">
            <button
              onClick={() => onNavigate('activity')}
              className="flex items-center gap-2 bg-gray-900 hover:bg-gray-800 border border-gray-800 hover:border-gray-700 px-4 py-2.5 rounded-xl font-semibold text-xs text-gray-200 transition-all cursor-pointer"
            >
              Activity History
            </button>
            <button
              onClick={() => onNavigate('create')}
              className="flex items-center gap-2 bg-gradient-to-r from-emerald-500 to-cyan-500 hover:from-emerald-400 hover:to-cyan-400 px-5 py-2.5 rounded-xl font-semibold text-sm text-white transition-all shadow-lg shadow-emerald-500/20 cursor-pointer"
            >
              New Scraper <ArrowRight size={16} />
            </button>
          </div>
        </div>
      </div>

      {/* Stat cards */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        {[
          { 
            label: isAdmin ? 'Platform Records' : 'Items Scraped', 
            value: formatNumber(statsData.itemsScraped), 
            icon: Database, 
            color: 'from-emerald-500/20 to-emerald-500/5', 
            text: 'text-emerald-400', 
            border: 'border-emerald-500/20',
            sub: isAdmin ? 'Total Scraped Data' : 'Your Scraped Records'
          },
          { 
            label: isAdmin ? 'Platform Runs' : 'Active Jobs', 
            value: isAdmin ? statsData.totalJobs.toString() : statsData.activeJobs.toString(), 
            icon: Activity, 
            color: 'from-cyan-500/20 to-cyan-500/5', 
            text: 'text-cyan-400', 
            border: 'border-cyan-500/20',
            sub: isAdmin ? `${statsData.activeJobs} Currently Running` : 'In Progress'
          },
          { 
            label: 'Success Rate', 
            value: `${statsData.successRate}%`, 
            icon: TrendingUp, 
            color: 'from-sky-500/20 to-sky-500/5', 
            text: 'text-sky-400', 
            border: 'border-sky-500/20',
            sub: 'Pipeline Reliability'
          },
          { 
            label: isAdmin ? 'System Compute' : 'Monthly Cost', 
            value: isAdmin ? `${statsData.computeUsed} CU` : '$0', 
            icon: Zap, 
            color: 'from-amber-500/20 to-amber-500/5', 
            text: 'text-amber-400', 
            border: 'border-amber-500/20',
            sub: isAdmin ? 'Unlimited Enterprise Tier' : 'Free Trial Tier'
          },
        ].map((stat) => {
          const Icon = stat.icon;
          return (
            <div key={stat.label} className={`bg-gradient-to-br ${stat.color} border ${stat.border} rounded-2xl p-5`}>
              <div className="flex items-center justify-between mb-3">
                <Icon className={`w-5 h-5 ${stat.text}`} />
                <span className="text-xs text-gray-400">Live</span>
              </div>
              <p className="text-2xl font-bold text-white">{stat.value}</p>
              <p className="text-xs font-medium text-gray-300 mt-1">{stat.label}</p>
              <p className="text-[11px] text-gray-500 mt-0.5">{stat.sub}</p>
            </div>
          );
        })}
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Active scraping jobs */}
        <div className="lg:col-span-2 bg-gray-900 border border-gray-800 rounded-2xl p-6">
          <div className="flex items-center justify-between mb-5">
            <h2 className="text-base font-bold text-white flex items-center gap-2">
              <Activity size={18} className="text-emerald-400" /> Active Jobs
            </h2>
            <button onClick={() => onNavigate('jobs')} className="text-xs text-emerald-400 hover:text-emerald-300 flex items-center gap-1">
              View all <ArrowRight size={12} />
            </button>
          </div>
          <div className="space-y-3">
            {recentJobs.length === 0 ? (
              <div className="py-8 text-center text-gray-500">
                <Activity className="mx-auto mb-2 text-gray-600" size={24} />
                <p className="text-sm font-medium text-gray-400">No scraping jobs yet</p>
                <p className="text-xs text-gray-500 mt-0.5">Click 'New Scraper' to launch your first job.</p>
              </div>
            ) : (
              recentJobs.map((job) => (
                <div key={job.id} className="flex items-center justify-between p-3.5 rounded-xl bg-gray-950/50 border border-gray-800/80 hover:border-gray-700 transition-colors">
                  <div className="flex items-center gap-3 min-w-0">
                    <div className="w-8 h-8 rounded-lg bg-gray-800 flex items-center justify-center flex-shrink-0">
                      <PlatformIcon platform={job.platform} className="w-4 h-4 text-white" />
                    </div>
                    <div className="min-w-0">
                      <p className="text-sm font-medium text-white truncate">{job.name}</p>
                      <div className="flex items-center gap-2 mt-0.5">
                        <StatusBadge status={job.status} />
                        <span className="text-xs text-gray-500">{job.itemsScraped} items</span>
                      </div>
                    </div>
                  </div>
                  {job.status === 'running' && (
                    <div className="flex items-center gap-3">
                      <div className="flex flex-col items-end">
                        <div className="flex items-center gap-1.5 px-2 py-0.5 rounded-full bg-emerald-500/10 border border-emerald-500/30">
                          <span className="relative flex h-2 w-2">
                            <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75"></span>
                            <span className="relative inline-flex rounded-full h-2 w-2 bg-emerald-500"></span>
                          </span>
                          <span className="text-[10px] text-emerald-400 font-mono font-semibold">
                            Live {formatElapsed(job.startedAt)}
                          </span>
                        </div>
                        <span className="text-[10px] text-gray-500 mt-0.5 font-mono">{job.progress}% scraped</span>
                      </div>
                      <Loader2 size={16} className="text-emerald-400 animate-spin flex-shrink-0" />
                    </div>
                  )}
                </div>
              ))
            )}
          </div>
        </div>

        {/* Weekly trend chart */}
        <div className="bg-gray-900 border border-gray-800 rounded-2xl p-6">
          <h2 className="text-base font-bold text-white flex items-center gap-2 mb-5">
            <BarChart3 size={18} className="text-cyan-400" /> Weekly Activity
          </h2>
          <div className="flex items-end justify-between gap-2 h-40">
            {['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'].map((day) => {
              const val = Math.max(0, Math.round(statsData.itemsScraped * 0.14));
              const heightPct = statsData.itemsScraped > 0 ? 30 : 4;
              return (
                <div key={day} className="flex flex-col items-center gap-2 flex-1">
                  <div className="w-full flex items-end justify-center" style={{ height: '120px' }}>
                    <div
                      className="w-full max-w-[32px] bg-gradient-to-t from-emerald-500 to-cyan-400 rounded-t-md transition-all hover:opacity-80 cursor-pointer"
                      style={{ height: `${heightPct}%` }}
                      title={`${val} items`}
                    />
                  </div>
                  <span className="text-xs text-gray-500">{day}</span>
                </div>
              );
            })}
          </div>
          <div className="mt-4 pt-4 border-t border-gray-800">
            <div className="flex items-center justify-between text-sm">
              <span className="text-gray-400">This week</span>
              <span className="text-white font-medium">{statsData.itemsScraped.toLocaleString()} items</span>
            </div>
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Recent data */}
        <div className="lg:col-span-2 bg-gray-900 border border-gray-800 rounded-2xl p-6">
          <div className="flex items-center justify-between mb-5">
            <h2 className="text-base font-bold text-white flex items-center gap-2">
              <Database size={18} className="text-sky-400" /> Latest Scraped Data
            </h2>
            <button onClick={() => onNavigate('data')} className="text-xs text-emerald-400 hover:text-emerald-300 flex items-center gap-1">
              Open Explorer <ArrowRight size={12} />
            </button>
          </div>
          <div className="space-y-2">
            {recentItems.length === 0 ? (
              <div className="py-8 text-center text-gray-500">
                <Database className="mx-auto mb-2 text-gray-600" size={24} />
                <p className="text-sm font-medium text-gray-400">No scraped records yet</p>
                <p className="text-xs text-gray-500 mt-0.5">Records will appear as your scrapers complete.</p>
              </div>
            ) : (
              recentItems.map((item) => (
                <div key={item.id} className="flex items-center gap-3 p-3 rounded-xl hover:bg-gray-800/30 transition-colors">
                  <div className="w-9 h-9 rounded-full bg-gradient-to-br from-gray-700 to-gray-800 flex items-center justify-center text-xs font-bold text-white flex-shrink-0">
                    {item.displayName[0] || 'U'}
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-1.5">
                      <span className="text-sm font-medium text-white truncate">{item.displayName}</span>
                      {item.isVerified && <CheckCircle2 size={12} className="text-sky-400 flex-shrink-0" />}
                    </div>
                    <p className="text-xs text-gray-500 truncate">{item.content}</p>
                  </div>
                  <div className="flex items-center gap-3 text-xs text-gray-400 flex-shrink-0">
                    <span className="flex items-center gap-1"><TrendingUp size={12} />{formatNumber(item.likes)}</span>
                    <span className="flex items-center gap-1"><Clock size={12} />{timeAgo(item.scrapedAt)}</span>
                  </div>
                </div>
              ))
            )}
          </div>
        </div>

        {/* Platform breakdown */}
        <div className="bg-gray-900 border border-gray-800 rounded-2xl p-6">
          <h2 className="text-base font-bold text-white flex items-center gap-2 mb-5">
            <Users size={18} className="text-amber-400" /> Platform Usage
          </h2>
          <div className="space-y-4">
            {platforms.slice(0, 6).map((p) => {
              const platformItems = statsData.itemsScraped > 0 ? Math.round(statsData.itemsScraped / 6) : 0;
              const pct = statsData.itemsScraped > 0 ? 16 : 0;
              return (
                <div key={p.id}>
                  <div className="flex items-center justify-between mb-1.5">
                    <div className="flex items-center gap-2">
                      <PlatformIcon platform={p.id} className={`w-4 h-4 ${p.color}`} />
                      <span className="text-sm text-white">{p.name}</span>
                    </div>
                    <span className="text-xs text-gray-400">{pct}%</span>
                  </div>
                  <div className="h-2 bg-gray-800 rounded-full overflow-hidden">
                    <div
                      className="h-full rounded-full bg-gradient-to-r from-emerald-500 to-cyan-500"
                      style={{ width: `${pct}%` }}
                    />
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      </div>

      {/* Quick actions */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        {[
          { label: 'New Scraper', icon: Zap, page: 'create' as PageId, color: 'from-emerald-500/20 to-emerald-500/5 border-emerald-500/20' },
          { label: 'View Data Explorer', icon: Database, page: 'data' as PageId, color: 'from-cyan-500/20 to-cyan-500/5 border-cyan-500/20' },
          { label: 'Schedules', icon: Clock, page: 'schedule' as PageId, color: 'from-sky-500/20 to-sky-500/5 border-sky-500/20' },
          { label: 'Settings', icon: Users, page: 'settings' as PageId, color: 'from-amber-500/20 to-amber-500/5 border-amber-500/20' },
        ].map((action) => {
          const Icon = action.icon;
          return (
            <button
              key={action.label}
              onClick={() => onNavigate(action.page)}
              className={`p-4 rounded-2xl bg-gradient-to-br ${action.color} border text-left hover:scale-[1.02] transition-transform`}
            >
              <Icon className="w-5 h-5 text-white mb-2" />
              <p className="text-sm font-semibold text-white">{action.label}</p>
            </button>
          );
        })}
      </div>
    </div>
  );
}
