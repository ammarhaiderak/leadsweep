import { useState, useEffect } from 'react';
import {
  TrendingUp, Heart, MessageSquare, Eye, BarChart3,
  Users, Activity, Smile, Frown, Meh, ShieldAlert, Globe2, User, RefreshCw, Zap
} from 'lucide-react';
import { api } from '@/api/client';
import { formatNumber } from '@/components/ui';

export function AnalyticsPage({ user }: { user?: any }) {
  const isAdmin = Boolean(user && (user.role === 'admin' || user.role === 'owner'));
  
  // Regular users are strictly locked to 'user' scope. Admin defaults to global or can toggle.
  const [scope, setScope] = useState<'user' | 'global'>(isAdmin ? 'global' : 'user');
  const [loading, setLoading] = useState(true);
  const [analytics, setAnalytics] = useState<{
    scope: 'user' | 'global';
    totalLikes: number;
    totalReplies: number;
    totalViews: number;
    totalReach: number;
    totalScraped: number;
    sentimentCounts: { positive: number; neutral: number; negative: number };
    trendData: Array<{ day: string; value: number }>;
    creditsRemaining: number;
    creditsTotal: number;
  }>({
    scope: 'user',
    totalLikes: 0,
    totalReplies: 0,
    totalViews: 0,
    totalReach: 0,
    totalScraped: 0,
    sentimentCounts: { positive: 0, neutral: 0, negative: 0 },
    trendData: [
      { day: 'Mon', value: 0 },
      { day: 'Tue', value: 0 },
      { day: 'Wed', value: 0 },
      { day: 'Thu', value: 0 },
      { day: 'Fri', value: 0 },
      { day: 'Sat', value: 0 },
      { day: 'Sun', value: 0 },
    ],
    creditsRemaining: 1000,
    creditsTotal: 1000,
  });

  const loadData = async (targetScope: 'user' | 'global') => {
    setLoading(true);
    try {
      // Regular users are forced to scope='user' and send their own user email
      const activeScope = isAdmin ? targetScope : 'user';
      const data = await api.getAnalytics(activeScope, user?.email);
      setAnalytics(data);
    } catch (err) {
      console.error('Failed to load analytics:', err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    // Force non-admins to user scope only
    if (!isAdmin && scope !== 'user') {
      setScope('user');
    }
    loadData(isAdmin ? scope : 'user');
  }, [scope, user?.email, isAdmin]);

  const sentimentTotal =
    analytics.sentimentCounts.positive +
    analytics.sentimentCounts.neutral +
    analytics.sentimentCounts.negative || 1;

  const maxTrend = Math.max(...analytics.trendData.map((d) => d.value), 1);
  const creditsUsed = Math.max(0, analytics.creditsTotal - analytics.creditsRemaining);
  const creditsPercent = Math.min(100, Math.round((creditsUsed / analytics.creditsTotal) * 100));

  return (
    <div className="p-4 lg:p-6 space-y-6 max-w-7xl mx-auto">
      {/* Header with Title and Scope Switcher */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div>
          <div className="flex items-center gap-3">
            <h1 className="text-2xl font-bold text-white tracking-tight">Analytics Dashboard</h1>
            <span
              className={`px-2.5 py-0.5 rounded-full text-xs font-semibold uppercase tracking-wider ${
                scope === 'global'
                  ? 'bg-amber-500/10 text-amber-400 border border-amber-500/30'
                  : 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/30'
              }`}
            >
              {scope === 'global' ? 'System Master View' : 'Personal Workspace'}
            </span>
          </div>
          <p className="text-sm text-gray-400 mt-1">
            {scope === 'global'
              ? 'Real-time global throughput, platform metrics, and overall infrastructure data.'
              : 'Strictly isolated metrics for your active scraping jobs, records, and monthly quota.'}
          </p>
        </div>

        {/* Admin Scope Toggle (Strictly hidden from non-admin users) */}
        <div className="flex items-center gap-3">
          {isAdmin && (
            <div className="flex items-center bg-gray-900 border border-gray-800 rounded-xl p-1 shadow-inner">
              <button
                onClick={() => setScope('user')}
                className={`flex items-center gap-2 px-3 py-1.5 rounded-lg text-xs font-semibold transition-all ${
                  scope === 'user'
                    ? 'bg-emerald-500/20 text-emerald-400 border border-emerald-500/40 shadow-sm'
                    : 'text-gray-400 hover:text-white'
                }`}
              >
                <User size={13} /> My Workspace
              </button>
              <button
                onClick={() => setScope('global')}
                className={`flex items-center gap-2 px-3 py-1.5 rounded-lg text-xs font-semibold transition-all ${
                  scope === 'global'
                    ? 'bg-amber-500/20 text-amber-400 border border-amber-500/40 shadow-sm'
                    : 'text-gray-400 hover:text-white'
                }`}
              >
                <Globe2 size={13} /> Global System
              </button>
            </div>
          )}
          <button
            onClick={() => loadData(scope)}
            disabled={loading}
            className="p-2 rounded-xl bg-gray-900 hover:bg-gray-800 text-gray-400 hover:text-white border border-gray-800 transition-colors"
            title="Refresh Metrics"
          >
            <RefreshCw size={16} className={loading ? 'animate-spin text-emerald-400' : ''} />
          </button>
        </div>
      </div>

      {/* Usage Quota Card for Regular User Context */}
      {scope === 'user' && (
        <div className="bg-gradient-to-r from-gray-900 via-gray-900/90 to-emerald-950/30 border border-emerald-500/20 rounded-2xl p-5 shadow-lg relative overflow-hidden">
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
            <div className="flex items-center gap-3.5">
              <div className="w-10 h-10 rounded-xl bg-emerald-500/10 border border-emerald-500/20 flex items-center justify-center text-emerald-400">
                <Zap size={20} />
              </div>
              <div>
                <div className="flex items-center gap-2">
                  <h3 className="text-base font-bold text-white">Free Trial Active</h3>
                  <span className="text-xs bg-emerald-500/10 text-emerald-400 px-2 py-0.5 rounded-md font-mono">
                    10 items one-time
                  </span>
                </div>
                <p className="text-xs text-gray-400 mt-0.5">
                  Your evaluation plan includes 10 free scraped items. Total items scraped:{' '}
                  <span className="text-white font-semibold">{analytics.totalScraped}</span>
                </p>
              </div>
            </div>

            <div className="w-full sm:w-64">
              <div className="flex justify-between text-xs mb-1.5">
                <span className="text-gray-400">Trial Usage</span>
                <span className="font-semibold text-emerald-400">
                  {Math.max(0, 10 - analytics.totalScraped)} items remaining
                </span>
              </div>
              <div className="h-2.5 bg-gray-800 rounded-full overflow-hidden p-0.5 border border-gray-700/50">
                <div
                  className="h-full rounded-full bg-gradient-to-r from-emerald-500 to-cyan-400 transition-all duration-500"
                  style={{ width: `${creditsPercent}%` }}
                />
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Key metrics cards */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        {[
          {
            label: scope === 'global' ? 'Total Platform Likes' : 'Total Extracted Likes',
            value: formatNumber(analytics.totalLikes),
            icon: Heart,
            color: 'from-rose-500/20 to-rose-500/5',
            text: 'text-rose-400',
            border: 'border-rose-500/20',
          },
          {
            label: scope === 'global' ? 'Total System Replies' : 'Replies Captured',
            value: formatNumber(analytics.totalReplies),
            icon: MessageSquare,
            color: 'from-sky-500/20 to-sky-500/5',
            text: 'text-sky-400',
            border: 'border-sky-500/20',
          },
          {
            label: scope === 'global' ? 'Total Global Views' : 'Total Lead Views',
            value: formatNumber(analytics.totalViews),
            icon: Eye,
            color: 'from-cyan-500/20 to-cyan-500/5',
            text: 'text-cyan-400',
            border: 'border-cyan-500/20',
          },
          {
            label: scope === 'global' ? 'Total Audience Reach' : 'Estimated Target Reach',
            value: formatNumber(analytics.totalReach),
            icon: Users,
            color: 'from-emerald-500/20 to-emerald-500/5',
            text: 'text-emerald-400',
            border: 'border-emerald-500/20',
          },
        ].map((stat) => {
          const Icon = stat.icon;
          return (
            <div key={stat.label} className={`bg-gradient-to-br ${stat.color} border ${stat.border} rounded-2xl p-5 shadow-sm`}>
              <Icon className={`w-5 h-5 ${stat.text} mb-3`} />
              <p className="text-2xl font-bold text-white">{stat.value}</p>
              <p className="text-xs text-gray-400 mt-1">{stat.label}</p>
            </div>
          );
        })}
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Weekly scraping activity graph */}
        <div className="lg:col-span-2 bg-gray-900 border border-gray-800 rounded-2xl p-6 shadow-sm">
          <div className="flex items-center justify-between mb-5">
            <h2 className="text-base font-bold text-white flex items-center gap-2">
              <BarChart3 size={18} className="text-emerald-400" />
              {scope === 'global' ? 'Global Scraping Volume (7 days)' : 'Your Scraping Activity (7 days)'}
            </h2>
            <span className="text-xs text-gray-400">Updated Hourly</span>
          </div>
          <div className="flex items-end justify-between gap-3 h-48 pt-4">
            {analytics.trendData.map((d) => (
              <div key={d.day} className="flex flex-col items-center gap-2 flex-1">
                <span className="text-xs text-gray-400 font-medium">{d.value}</span>
                <div className="w-full flex items-end justify-center" style={{ height: '140px' }}>
                  <div
                    className="w-full max-w-[40px] bg-gradient-to-t from-emerald-500 to-cyan-400 rounded-t-md transition-all duration-300 hover:opacity-80 cursor-pointer relative group"
                    style={{ height: `${Math.max(4, (d.value / maxTrend) * 100)}%` }}
                  >
                    <div className="absolute inset-0 bg-gradient-to-t from-transparent to-white/20 rounded-t-md" />
                  </div>
                </div>
                <span className="text-xs text-gray-500">{d.day}</span>
              </div>
            ))}
          </div>
        </div>

        {/* Sentiment Analysis Ratio */}
        <div className="bg-gray-900 border border-gray-800 rounded-2xl p-6 shadow-sm">
          <h2 className="text-base font-bold text-white flex items-center gap-2 mb-5">
            <Activity size={18} className="text-cyan-400" />
            {scope === 'global' ? 'System Sentiment Overview' : 'Target Query Sentiment'}
          </h2>
          <div className="flex items-center justify-center mb-6">
            <div className="relative w-40 h-40">
              <svg className="w-full h-full -rotate-90" viewBox="0 0 100 100">
                <circle cx="50" cy="50" r="40" fill="none" stroke="#1f2937" strokeWidth="12" />
                <circle
                  cx="50"
                  cy="50"
                  r="40"
                  fill="none"
                  stroke="#10b981"
                  strokeWidth="12"
                  strokeDasharray={`${(analytics.sentimentCounts.positive / sentimentTotal) * 251.2} 251.2`}
                  strokeLinecap="round"
                />
                <circle
                  cx="50"
                  cy="50"
                  r="40"
                  fill="none"
                  stroke="#6b7280"
                  strokeWidth="12"
                  strokeDasharray={`${(analytics.sentimentCounts.neutral / sentimentTotal) * 251.2} 251.2`}
                  strokeDashoffset={`-${(analytics.sentimentCounts.positive / sentimentTotal) * 251.2}`}
                  strokeLinecap="round"
                />
                <circle
                  cx="50"
                  cy="50"
                  r="40"
                  fill="none"
                  stroke="#ef4444"
                  strokeWidth="12"
                  strokeDasharray={`${(analytics.sentimentCounts.negative / sentimentTotal) * 251.2} 251.2`}
                  strokeDashoffset={`-${((analytics.sentimentCounts.positive + analytics.sentimentCounts.neutral) / sentimentTotal) * 251.2}`}
                  strokeLinecap="round"
                />
              </svg>
              <div className="absolute inset-0 flex flex-col items-center justify-center">
                <p className="text-2xl font-bold text-white">
                  {Math.round((analytics.sentimentCounts.positive / sentimentTotal) * 100)}%
                </p>
                <p className="text-xs text-gray-400">Positive</p>
              </div>
            </div>
          </div>
          <div className="space-y-2.5">
            {[
              {
                label: 'Positive',
                count: analytics.sentimentCounts.positive,
                icon: Smile,
                color: 'text-emerald-400 bg-emerald-500/10',
              },
              {
                label: 'Neutral',
                count: analytics.sentimentCounts.neutral,
                icon: Meh,
                color: 'text-gray-400 bg-gray-500/10',
              },
              {
                label: 'Negative',
                count: analytics.sentimentCounts.negative,
                icon: Frown,
                color: 'text-red-400 bg-red-500/10',
              },
            ].map((s) => {
              const Icon = s.icon;
              return (
                <div key={s.label} className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <div className={`w-7 h-7 rounded-lg ${s.color} flex items-center justify-center`}>
                      <Icon size={14} />
                    </div>
                    <span className="text-sm text-gray-300">{s.label}</span>
                  </div>
                  <span className="text-sm font-medium text-white">
                    {s.count} ({Math.round((s.count / sentimentTotal) * 100)}%)
                  </span>
                </div>
              );
            })}
          </div>
        </div>
      </div>
    </div>
  );
}
