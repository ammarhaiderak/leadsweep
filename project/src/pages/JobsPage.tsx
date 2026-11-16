import { useEffect, useState } from 'react';
import {
  Search, Play, Pause, RotateCcw, Trash2, Filter, Download,
  MoreVertical, Clock, Calendar, ChevronDown, Eye, FileText, Table2, X, CheckCircle2,
  Heart, MessageSquare, Loader2, Send, AlertTriangle, // NEW FEATURE: Telegram Send icon
} from 'lucide-react';

import { jobs as mockJobs, platforms } from '@/data/mockData';
import { PlatformIcon, StatusBadge, formatNumber, timeAgo } from '@/components/ui';
import { api } from '@/api/client';
import { UpgradeSubscriptionModal } from '@/components/UpgradeSubscriptionModal';
import type { JobStatus, ScraperJob } from '@/types';
import type { PageId } from '@/App';

const statusFilters: (JobStatus | 'all')[] = ['all', 'running', 'completed', 'queued', 'failed', 'paused'];

export function JobsPage({ onNavigate, user }: { onNavigate: (page: PageId) => void; user?: any }) {
  const [jobsList, setJobsList] = useState<ScraperJob[]>([]);
  const [filter, setFilter] = useState<JobStatus | 'all'>('all');
  const [search, setSearch] = useState('');
  const [activeMenuJobId, setActiveMenuJobId] = useState<string | null>(null);
  const [viewingJob, setViewingJob] = useState<ScraperJob | null>(null);
  const [viewingItems, setViewingItems] = useState<any[]>([]);
  const [viewingLoading, setViewingLoading] = useState(false);
  const [now, setNow] = useState(Date.now());
  const [isUpgradeModalOpen, setIsUpgradeModalOpen] = useState(false);
  const [remainingCredits, setRemainingCredits] = useState<number>(10);
  const [exportFormat, setExportFormat] = useState<'csv' | 'xlsx' | 'json' | 'jsonl' | 'tsv'>(
    (localStorage.getItem('leadsweep_export_format') as any) || 'csv'
  );
  const [exportKind, setExportKind] = useState<'leads' | 'raw'>('leads');
  const [exportingJobId, setExportingJobId] = useState<string | null>(null);
  const [exportToast, setExportToast] = useState<string | null>(null);
  // NEW FEATURE (Phase 2): UI Noise suppression toggle & post text expander
  const [showLowRelevance, setShowLowRelevance] = useState(false);
  const [expandedItems, setExpandedItems] = useState<Record<string, boolean>>({});

  const storedUser = (() => {
    try {
      const s = localStorage.getItem('leadsweep_auth_user');
      return s ? JSON.parse(s) : null;
    } catch {
      return null;
    }
  })();
  const effectiveUser = user || storedUser;

  const isAdmin = Boolean(
    effectiveUser && (
      effectiveUser.role === 'admin' ||
      effectiveUser.role === 'owner'
    )
  );
  const userPlan = (effectiveUser?.plan || '').toLowerCase();
  const isUpgraded = userPlan.includes('pro') || userPlan.includes('enterprise');
  const userEmail = isAdmin ? undefined : effectiveUser?.email;

  useEffect(() => {
    if (effectiveUser?.email && !isAdmin && !isUpgraded) {
      api.getOverviewStats(effectiveUser.email).then((stats) => {
        const scraped = stats.itemsScraped || 0;
        setRemainingCredits(Math.max(0, 10 - scraped));
      }).catch(() => {});
    }
  }, [effectiveUser, isAdmin, isUpgraded]);

  useEffect(() => {
    let mounted = true;
    async function fetchJobs() {
      try {
        const liveJobs = await api.getJobs(undefined, userEmail);
        if (!mounted) return;
        setJobsList(liveJobs || []);
      } catch (err) {
        console.error('Failed to load jobs from API:', err);
        if (mounted) setJobsList([]);
      }
    }
    fetchJobs();
    
    // Fast 1.5s live polling stream
    const interval = setInterval(() => {
      fetchJobs();
      setNow(Date.now());
    }, 1500);

    return () => {
      mounted = false;
      clearInterval(interval);
    };
  }, [userEmail]);

  // UPDATED LOGIC (M6): Accurate duration for completed/terminal jobs
  const formatElapsed = (startedAt: string, completedAt?: string | null) => {
    const endMs = completedAt ? new Date(completedAt).getTime() : now;
    const diffMs = Math.max(0, endMs - new Date(startedAt).getTime());
    const totalSec = Math.floor(diffMs / 1000);
    const m = Math.floor(totalSec / 60);
    const s = totalSec % 60;
    return `${m}m ${s < 10 ? '0' : ''}${s}s`;
  };

  const calculateETA = (job: ScraperJob) => {
    if (!job.totalItems || job.totalItems <= 0 || job.itemsScraped <= 0) {
      return '~calculating...';
    }
    const remaining = Math.max(0, job.totalItems - job.itemsScraped);
    if (remaining === 0) return '0s';
    const elapsedSec = Math.max(1, (now - new Date(job.startedAt).getTime()) / 1000);
    const secPerItem = elapsedSec / job.itemsScraped;
    const estRemainingSec = Math.round(remaining * secPerItem);
    const rm = Math.floor(estRemainingSec / 60);
    const rs = estRemainingSec % 60;
    return rm > 0 ? `~${rm}m ${rs}s left` : `~${rs}s left`;
  };

  const scopedJobs = jobsList.filter((job) => {
    if (isAdmin) return true;
    const userIdentifier = (effectiveUser?.email || effectiveUser?.name || '').toLowerCase();
    const jobOwner = (job.owner || '').toLowerCase();
    if (!userIdentifier) return true;
    return jobOwner === userIdentifier || jobOwner.includes(userIdentifier.split('@')[0]) || jobOwner === 'user';
  });

  const filteredJobs = scopedJobs.filter((job) => {
    const matchesStatus = filter === 'all' || job.status === filter;
    const matchesSearch = job.name.toLowerCase().includes(search.toLowerCase()) || job.owner.toLowerCase().includes(search.toLowerCase());
    return matchesStatus && matchesSearch;
  });

  const counts: Record<string, number> = {
    all: scopedJobs.length,
    running: scopedJobs.filter((j) => j.status === 'running').length,
    completed: scopedJobs.filter((j) => j.status === 'completed').length,
    queued: scopedJobs.filter((j) => j.status === 'queued').length,
    failed: scopedJobs.filter((j) => j.status === 'failed').length,
    paused: scopedJobs.filter((j) => j.status === 'paused').length,
  };

  return (
    <div className="p-4 lg:p-6 space-y-6">
      <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-white">Scraper Jobs</h1>
          <p className="text-sm text-gray-400 mt-1">Monitor and manage all your scraping jobs</p>
        </div>
        <div className="flex items-center gap-2 flex-wrap">
          {/* Format and Scope Selector */}
          <select
            value={exportFormat}
            onChange={(e) => {
              const fmt = e.target.value as any;
              setExportFormat(fmt);
              localStorage.setItem('leadsweep_export_format', fmt);
            }}
            className="bg-gray-900 border border-gray-800 text-gray-200 text-xs rounded-xl px-2.5 py-2 outline-none focus:border-emerald-500/50 uppercase font-semibold"
            title="Choose Export Format"
          >
            <option value="csv">CSV</option>
            <option value="xlsx">XLSX</option>
            <option value="json">JSON</option>
            <option value="jsonl">JSONL</option>
            <option value="tsv">TSV</option>
          </select>

          <select
            value={exportKind}
            onChange={(e) => setExportKind(e.target.value as any)}
            className="bg-gray-900 border border-gray-800 text-gray-200 text-xs rounded-xl px-2.5 py-2 outline-none focus:border-emerald-500/50 font-medium"
            title="Export Data Type"
          >
            <option value="leads">Leads (Scored)</option>
            <option value="raw">Raw Data</option>
          </select>

          <button
            onClick={async () => {
              if (exportingJobId) return;
              try {
                setExportingJobId('all');
                setExportToast('Generating full system export...');
                const filename = await api.downloadExport({
                  scope: 'all',
                  format: exportFormat,
                  kind: exportKind,
                });
                setExportToast(`Downloaded: ${filename}`);
                setTimeout(() => setExportToast(null), 4000);
              } catch (err: any) {
                setExportToast(`Export failed: ${err.message || 'Unknown error'}`);
                setTimeout(() => setExportToast(null), 5000);
              } finally {
                setExportingJobId(null);
              }
            }}
            disabled={exportingJobId === 'all'}
            className="flex items-center gap-1.5 px-3 py-2 bg-gray-800 hover:bg-gray-700 text-gray-200 border border-gray-700 rounded-xl font-semibold text-xs transition-colors disabled:opacity-50"
            title="Export all jobs data into chosen format"
          >
            {exportingJobId === 'all' ? <Loader2 size={14} className="animate-spin text-emerald-400" /> : <Download size={14} className="text-emerald-400" />}
            <span>Export All Jobs</span>
          </button>

          <button
            onClick={() => {
              if (!isAdmin && !isUpgraded && remainingCredits <= 0) {
                setIsUpgradeModalOpen(true);
              } else {
                onNavigate('create');
              }
            }}
            className="flex items-center gap-2 bg-gradient-to-r from-emerald-500 to-cyan-500 hover:from-emerald-400 hover:to-cyan-400 px-4 py-2.5 rounded-xl font-semibold text-sm text-white transition-all shadow-lg shadow-emerald-500/20 cursor-pointer"
          >
            <Play size={16} /> New Job
          </button>
        </div>
      </div>

      {exportToast && (
        <div className="p-3 bg-emerald-500/10 border border-emerald-500/30 rounded-xl text-xs text-emerald-400 flex items-center justify-between animate-in fade-in">
          <span>{exportToast}</span>
          <button onClick={() => setExportToast(null)} className="text-gray-400 hover:text-white ml-2"><X size={14} /></button>
        </div>
      )}

      {/* Filter tabs */}
      <div className="flex items-center gap-2 overflow-x-auto pb-2">
        {statusFilters.map((s) => (
          <button
            key={s}
            onClick={() => setFilter(s)}
            className={`flex items-center gap-2 px-3.5 py-2 rounded-lg text-sm font-medium whitespace-nowrap transition-all ${
              filter === s
                ? 'bg-gray-800 text-white border border-gray-700'
                : 'text-gray-400 hover:text-white hover:bg-gray-800/50'
            }`}
          >
            <span className="capitalize">{s}</span>
            <span className={`text-xs px-1.5 py-0.5 rounded-full ${filter === s ? 'bg-emerald-500/20 text-emerald-400' : 'bg-gray-800 text-gray-500'}`}>
              {counts[s]}
            </span>
          </button>
        ))}
      </div>

      {/* Search bar */}
      <div className="flex items-center gap-3">
        <div className="flex items-center gap-2 bg-gray-900 border border-gray-800 rounded-lg px-3 py-2.5 flex-1">
          <Search size={16} className="text-gray-500" />
          <input
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search jobs by name or owner..."
            className="bg-transparent text-sm text-white placeholder-gray-500 outline-none flex-1"
          />
        </div>
        <button className="flex items-center gap-2 text-sm text-gray-400 hover:text-white bg-gray-900 border border-gray-800 rounded-lg px-3 py-2.5 transition-colors">
          <Filter size={16} /> Filters <ChevronDown size={14} />
        </button>
      </div>

      {/* Jobs table */}
      <div className="bg-gray-900 border border-gray-800 rounded-2xl overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full">
            <thead>
              <tr className="border-b border-gray-800 bg-gray-950/50">
                <th className="text-left text-xs font-semibold text-gray-500 uppercase tracking-wider px-4 py-3">Job</th>
                <th className="text-left text-xs font-semibold text-gray-500 uppercase tracking-wider px-4 py-3 hidden md:table-cell">Platform</th>
                <th className="text-left text-xs font-semibold text-gray-500 uppercase tracking-wider px-4 py-3">Status</th>
                <th className="text-left text-xs font-semibold text-gray-500 uppercase tracking-wider px-4 py-3 hidden lg:table-cell">Progress</th>
                <th className="text-left text-xs font-semibold text-gray-500 uppercase tracking-wider px-4 py-3 hidden sm:table-cell">Items</th>
                <th className="text-left text-xs font-semibold text-gray-500 uppercase tracking-wider px-4 py-3 hidden lg:table-cell">Started</th>
                <th className="text-right text-xs font-semibold text-gray-500 uppercase tracking-wider px-4 py-3">Actions</th>
              </tr>
            </thead>
            <tbody>
              {filteredJobs.map((job) => {
                const platform = platforms.find((p) => p.id === job.platform);
                return (
                  <tr key={job.id} className="border-b border-gray-800/50 hover:bg-gray-800/30 transition-colors group">
                    <td className="px-4 py-4">
                      <div className="flex items-center gap-2">
                        {job.scheduled && <Calendar size={12} className="text-emerald-400 flex-shrink-0" />}
                        <div className="min-w-0 max-w-[240px] sm:max-w-[320px]">
                          <div className="flex items-center gap-2">
                            <p className="text-sm font-medium text-white truncate" title={job.name}>{job.name}</p>
                            {(job as any).hasPinned && (
                              <span className="text-[10px] font-bold uppercase px-1.5 py-0.5 rounded bg-blue-500/20 text-blue-300 border border-blue-500/40 flex-shrink-0">
                                📌 Pinned
                              </span>
                            )}
                          </div>
                          <div className="flex items-center gap-2 mt-0.5">
                            <span className="text-xs text-gray-500 flex-shrink-0">{job.owner}</span>
                            {job.status !== 'completed' && ((job as any).errorDetail || (job as any).status_detail || job.error) && (
                              <span className="text-[10px] text-amber-400/90 font-mono bg-amber-500/10 px-1.5 py-0.5 rounded border border-amber-500/20 max-w-[200px] truncate inline-block cursor-help" title={(job as any).errorDetail || (job as any).status_detail || job.error}>
                                {(job as any).errorDetail || (job as any).status_detail || job.error}
                              </span>
                            )}
                          </div>
                        </div>
                      </div>
                    </td>
                    <td className="px-4 py-4 hidden md:table-cell">
                      <div className="flex items-center gap-2">
                        <div className={`w-7 h-7 rounded-lg ${platform?.bgColor} flex items-center justify-center`}>
                          <PlatformIcon platform={job.platform} className={`w-4 h-4 ${platform?.color}`} />
                        </div>
                        <span className="text-xs text-gray-400">{platform?.name}</span>
                      </div>
                    </td>
                    <td className="px-4 py-4">
                      <StatusBadge status={job.status} />
                    </td>
                    <td className="px-4 py-4 hidden lg:table-cell">
                      {job.status === 'running' || job.status === 'paused' ? (
                        <div className="w-36">
                          <div className="flex items-center justify-between mb-1">
                            <span className="text-xs text-emerald-400 font-semibold">{job.progress}%</span>
                            <span className="text-[10px] text-cyan-300 font-mono">{calculateETA(job)}</span>
                          </div>
                          <div className="h-2 bg-gray-800 rounded-full overflow-hidden">
                            <div
                              className="h-full rounded-full bg-gradient-to-r from-emerald-500 via-teal-400 to-cyan-500 animate-pulse transition-all duration-300"
                              style={{ width: `${Math.max(job.progress, 5)}%` }}
                            />
                          </div>
                          <div className="flex justify-between items-center mt-1">
                            <span className="text-[10px] text-gray-500">Elapsed: {formatElapsed(job.startedAt)}</span>
                          </div>
                        </div>
                      ) : (
                        <div className="text-xs text-gray-400">
                          {job.status === 'completed' ? (
                            <span className="text-sky-400 font-medium flex items-center gap-1">100% · Done</span>
                          ) : job.status === 'partial' ? (
                            <span
                              className="text-amber-400 font-medium cursor-help underline decoration-dotted decoration-amber-500/50"
                              title={job.error || (job as any).errorDetail || "Job partially completed with unevaluated items"}
                            >
                              {job.progress}% · Partial
                            </span>
                          ) : job.status === 'failed' ? (
                            <span
                              className="text-red-400 font-medium cursor-help underline decoration-dotted decoration-red-500/50"
                              title={job.error || (job as any).errorDetail || "Job terminated unexpectedly"}
                            >
                              0% · Terminated
                            </span>
                          ) : (
                            <span className="text-gray-500">—</span>
                          )}
                        </div>
                      )}
                    </td>
                    <td className="px-4 py-4 hidden sm:table-cell">
                      <span className="text-sm text-white font-medium">{formatNumber(job.itemsScraped)}</span>
                      {job.totalItems && <span className="text-xs text-gray-400 font-mono"> / {formatNumber(job.totalItems)}</span>}
                    </td>
                    <td className="px-4 py-4 hidden lg:table-cell">
                      <div className="text-xs text-gray-400 space-y-1">
                        <span className="flex items-center gap-1 text-gray-300 font-medium">
                          <Clock size={12} className="text-gray-400" /> {timeAgo(job.startedAt)}
                        </span>
                        {job.status === 'running' && (
                          <div className="flex items-center gap-1.5 px-2 py-0.5 rounded-full bg-emerald-500/10 border border-emerald-500/30 w-fit">
                            <span className="relative flex h-2 w-2">
                              <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75"></span>
                              <span className="relative inline-flex rounded-full h-2 w-2 bg-emerald-500"></span>
                            </span>
                            <span className="text-[10px] text-emerald-400 font-mono font-semibold tracking-wide">
                              Live: {formatElapsed(job.startedAt)}
                            </span>
                          </div>
                        )}
                        {job.status === 'completed' && job.completedAt && (
                          <span className="text-[10px] text-gray-500 block font-mono">
                            Took {formatElapsed(job.startedAt, job.completedAt)}
                          </span>
                        )}
                      </div>
                    </td>
                    <td className="px-4 py-4">
                      <div className="flex items-center justify-end gap-1.5">
                        {job.status === 'running' && (
                          <button
                            onClick={async () => { await api.pauseJob(job.id); const updated = await api.getJobs(); setJobsList(updated); }}
                            className="p-2 rounded-lg text-gray-400 hover:text-white hover:bg-gray-800 transition-colors"
                            title="Pause"
                          >
                            <Pause size={14} />
                          </button>
                        )}
                        {(job.status === 'paused' || job.status === 'failed') && (
                          <button
                            onClick={async () => { await api.resumeJob(job.id); const updated = await api.getJobs(); setJobsList(updated); }}
                            className="p-2 rounded-lg text-gray-400 hover:text-emerald-400 hover:bg-gray-800 transition-colors"
                            title="Resume"
                          >
                            <Play size={14} />
                          </button>
                        )}
                        {job.status === 'completed' && (
                          <button
                            onClick={async () => {
                              try {
                                await api.downloadExport({ job_id: job.id, format: exportFormat, kind: exportKind });
                                setExportToast(`Exported job ${job.name} successfully!`);
                              } catch (err: any) {
                                setExportToast(`Export failed: ${err.message}`);
                              }
                            }}
                            className="p-2 rounded-lg text-gray-400 hover:text-sky-400 hover:bg-gray-800 transition-colors"
                            title={`Download ${exportFormat.toUpperCase()} for this job`}
                          >
                            <Download size={14} />
                          </button>
                        )}
                        <button
                          onClick={async () => { await api.retryJob(job.id); const updated = await api.getJobs(); setJobsList(updated); }}
                          className="p-2 rounded-lg text-gray-400 hover:text-amber-400 hover:bg-gray-800 transition-colors"
                          title="Retry"
                        >
                          <RotateCcw size={14} />
                        </button>
                        <button
                          onClick={async () => { await api.deleteJob(job.id); setJobsList((prev) => prev.filter((j) => j.id !== job.id)); }}
                          className="p-2 rounded-lg text-gray-400 hover:text-red-400 hover:bg-gray-800 transition-colors"
                          title="Delete"
                        >
                          <Trash2 size={14} />
                        </button>

                        {/* Interactive 3-dots Action Menu */}
                        <div className="relative">
                          <button
                            onClick={() => setActiveMenuJobId(activeMenuJobId === job.id ? null : job.id)}
                            className="p-2 rounded-lg text-gray-400 hover:text-white hover:bg-gray-800 transition-colors"
                            title="More Actions"
                          >
                            <MoreVertical size={14} />
                          </button>

                          {activeMenuJobId === job.id && (
                            <div className="absolute right-0 mt-2 w-52 bg-gray-900 border border-gray-800 rounded-xl shadow-2xl py-1.5 z-40 text-left">
                              <button
                                onClick={async () => {
                                  setActiveMenuJobId(null);
                                  setViewingJob(job);
                                  const isSingleSource = ['profile', 'timeline', 'replies', 'user_tweets'].includes(job.type) ||
                                    (job.platform === 'telegram' && ['channel_messages', 'channel_info', 'search'].includes(job.type)) ||
                                    Boolean(job.name && (job.name.startsWith('@') || job.name.includes('x.com/') || job.name.startsWith('t.me/')));
                                  setShowLowRelevance(isSingleSource);
                                  setViewingLoading(true);
                                  try {
                                    const items = await api.getJobData(job.id);
                                    if (Array.isArray(items)) {
                                      setViewingItems(items);
                                    } else {
                                      setViewingItems([]);
                                    }
                                  } catch (err) {
                                    console.error("Failed to load real items for job:", err);
                                    setViewingItems([]);
                                  } finally {
                                    setViewingLoading(false);
                                  }
                                }}
                                className="w-full flex items-center gap-2.5 px-3.5 py-2 text-xs text-gray-300 hover:text-white hover:bg-gray-800/80 transition-colors"
                              >
                                <Eye size={14} className="text-emerald-400" />
                                <span>View Leads in App</span>
                              </button>

                              <button
                                onClick={async () => {
                                  setActiveMenuJobId(null);
                                  try {
                                    await api.downloadExport({ job_id: job.id, format: 'csv', kind: exportKind });
                                  } catch (err: any) {
                                    setExportToast(`Export failed: ${err.message}`);
                                  }
                                }}
                                className="w-full flex items-center gap-2.5 px-3.5 py-2 text-xs text-gray-300 hover:text-white hover:bg-gray-800/80 transition-colors"
                              >
                                <Download size={14} className="text-sky-400" />
                                <span>Download Leads (CSV)</span>
                              </button>

                              <button
                                onClick={async () => {
                                  setActiveMenuJobId(null);
                                  try {
                                    await api.downloadExport({ job_id: job.id, format: 'json', kind: exportKind });
                                  } catch (err: any) {
                                    setExportToast(`Export failed: ${err.message}`);
                                  }
                                }}
                                className="w-full flex items-center gap-2.5 px-3.5 py-2 text-xs text-gray-300 hover:text-white hover:bg-gray-800/80 transition-colors"
                              >
                                <FileText size={14} className="text-purple-400" />
                                <span>Export Full Data (JSON)</span>
                              </button>

                              <button
                                onClick={() => {
                                  setActiveMenuJobId(null);
                                  onNavigate('data');
                                }}
                                className="w-full flex items-center gap-2.5 px-3.5 py-2 text-xs text-gray-300 hover:text-white hover:bg-gray-800/80 transition-colors"
                              >
                                <Table2 size={14} className="text-cyan-400" />
                                <span>Open in Data Explorer</span>
                              </button>

                              <div className="my-1 border-t border-gray-800" />

                              <button
                                onClick={async () => {
                                  setActiveMenuJobId(null);
                                  await api.deleteJob(job.id);
                                  setJobsList((prev) => prev.filter((j) => j.id !== job.id));
                                }}
                                className="w-full flex items-center gap-2.5 px-3.5 py-2 text-xs text-red-400 hover:bg-red-500/10 transition-colors"
                              >
                                <Trash2 size={14} />
                                <span>Delete Scrape Job</span>
                              </button>
                            </div>
                          )}
                        </div>
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>

        {filteredJobs.length === 0 && (
          <div className="py-16 text-center">
            <p className="text-gray-500 text-sm">No jobs found matching your filters.</p>
          </div>
        )}
      </div>

      {/* In-App Scraped Leads Viewer Modal */}
      {viewingJob && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/75 backdrop-blur-sm animate-in fade-in duration-200">
          <div className="relative w-full max-w-4xl bg-gray-900 border border-gray-800 rounded-3xl p-6 shadow-2xl flex flex-col max-h-[85vh]">
            <div className="flex items-center justify-between pb-4 border-b border-gray-800 shrink-0">
              <div className="flex items-center gap-3">
                <div className="w-10 h-10 rounded-xl bg-emerald-500/10 border border-emerald-500/30 flex items-center justify-center text-emerald-400">
                  <Table2 size={20} />
                </div>
                <div>
                  <h3 className="text-base font-bold text-white flex items-center gap-2">
                    <span>Leads for: {viewingJob.name}</span>
                    <span className="text-xs px-2 py-0.5 rounded-full bg-emerald-500/20 text-emerald-400 border border-emerald-500/30">
                      {viewingItems.length} items
                    </span>
                  </h3>
                  <p className="text-xs text-gray-400 mt-0.5">Scraped directly into your local database</p>
                </div>
              </div>
              <div className="flex items-center gap-2">
                <button
                  onClick={async () => {
                    try {
                      await api.downloadExport({ job_id: viewingJob.id, format: exportFormat, kind: exportKind });
                      setExportToast(`Exported job ${viewingJob.name} successfully!`);
                    } catch (err: any) {
                      setExportToast(`Export failed: ${err.message}`);
                    }
                  }}
                  className="flex items-center gap-1.5 px-3 py-1.5 bg-emerald-500/10 hover:bg-emerald-500/20 text-emerald-400 border border-emerald-500/30 rounded-xl text-xs font-semibold transition-colors"
                >
                  <Download size={14} /> Download {exportFormat.toUpperCase()}
                </button>
                <button
                  onClick={() => setViewingJob(null)}
                  className="p-2 text-gray-400 hover:text-white rounded-xl hover:bg-gray-800 transition-colors"
                >
                  <X size={18} />
                </button>
              </div>
            </div>

            <div className="flex-1 overflow-y-auto py-4 space-y-3">
              {(() => {
                const isProfileRun = viewingJob.type === 'profile' || (viewingItems.length > 0 && Boolean(viewingItems[0].is_profile || viewingItems[0].type === 'profile'));
                const isTimelineRun = viewingJob.type === 'timeline' || viewingJob.type === 'user_tweets';
                const isUnevaluated = (it: any) => !isProfileRun && !it.is_profile && (it.evaluator === 'unevaluated' || it.leadScore === null || it.leadCategory === 'unevaluated');
                const unevaluatedCount = isProfileRun ? 0 : viewingItems.filter(isUnevaluated).length;
                const isIrrelevantOrLow = (it: any) => !isProfileRun && !it.is_profile && !isTimelineRun && !isUnevaluated(it) && ((it.leadScore !== undefined && it.leadScore < 40) || it.leadCategory === 'IRRELEVANT' || it.category === 'IRRELEVANT');
                const lowCount = isProfileRun || isTimelineRun ? 0 : viewingItems.filter(isIrrelevantOrLow).length;
                const visibleItems = (showLowRelevance || isTimelineRun || isProfileRun) ? viewingItems : viewingItems.filter((it) => !isIrrelevantOrLow(it));

                return (
                  <>
                    {/* NEW FEATURE (N3): Visible AI evaluation unavailable banner */}
                    {unevaluatedCount > 0 && (
                      <div className="flex items-center justify-between p-3 rounded-xl bg-amber-500/10 border border-amber-500/30 text-xs text-amber-300">
                        <span className="flex items-center gap-2">
                          <span>⚠️</span>
                          <span><strong>AI evaluation unavailable:</strong> {unevaluatedCount} item{unevaluatedCount > 1 ? 's' : ''} left unevaluated. Status: {viewingJob.status.toUpperCase()}.</span>
                        </span>
                        <span className="text-[11px] font-mono text-amber-400/80 bg-amber-500/20 px-2 py-0.5 rounded">
                          {(viewingJob as any).errorDetail ? (viewingJob as any).errorDetail.slice(0, 45) + '...' : 'LLM Key/Budget Inactive'}
                        </span>
                      </div>
                    )}

                    {/* Noise filter banner */}
                    {lowCount > 0 && (
                      <div className="flex items-center justify-between p-3 rounded-xl bg-gray-950 border border-gray-800 text-xs">
                        <span className="text-gray-400">
                          🎯 <strong className="text-white">{lowCount}</strong> low-relevance / noise item{lowCount > 1 ? 's' : ''} {showLowRelevance ? 'shown' : 'hidden'}
                        </span>
                        <button
                          onClick={() => setShowLowRelevance(!showLowRelevance)}
                          className="px-2.5 py-1 rounded-lg bg-gray-800 hover:bg-gray-700 text-gray-300 hover:text-white font-medium transition-colors"
                        >
                          {showLowRelevance ? 'Hide Low Relevance' : 'Show All Items'}
                        </button>
                      </div>
                    )}

                    {viewingLoading ? (
                      <div className="py-20 text-center text-sm text-gray-400">
                        Loading leads from database...
                      </div>
                    ) : visibleItems.length === 0 ? (
                      viewingItems.length > 0 ? (
                        <div className="py-16 text-center space-y-3">
                          <p className="text-gray-400 text-sm">{viewingItems.length} low-relevance items hidden</p>
                          <button
                            onClick={() => setShowLowRelevance(true)}
                            className="px-4 py-2 bg-emerald-500/20 hover:bg-emerald-500/30 text-emerald-400 border border-emerald-500/40 rounded-xl text-xs font-semibold transition-colors"
                          >
                            Show All Items
                          </button>
                        </div>
                      ) : (
                        <div className="py-16 text-center space-y-3">
                          <div className={`w-12 h-12 mx-auto rounded-2xl flex items-center justify-center ${
                            viewingJob.status === 'failed' ? 'bg-red-500/10 border border-red-500/30 text-red-400' : 'bg-gray-800/50 border border-gray-700 text-gray-400'
                          }`}>
                            <AlertTriangle size={24} />
                          </div>
                          <p className="text-sm font-semibold text-white">
                            {viewingJob.status === 'failed' ? 'Job Failed' : 'No Items Scraped'}
                          </p>
                          {((viewingJob as any).errorDetail || viewingJob.error) && (
                            <div className="text-xs text-amber-300 font-mono bg-amber-500/10 border border-amber-500/20 px-3 py-2 rounded-xl max-w-md mx-auto text-left break-words">
                              <span className="font-bold text-amber-400 block mb-0.5">Status Detail:</span>
                              {(viewingJob as any).errorDetail || viewingJob.error}
                            </div>
                          )}
                          {!((viewingJob as any).errorDetail || viewingJob.error) && (
                            <p className="text-xs text-gray-400">
                              {viewingJob.status === 'running' ? 'Job is currently running and scraping items...' : 'Zero items returned for this query.'}
                            </p>
                          )}
                        </div>
                      )
                    ) : (
                      visibleItems.map((item, idx) => {
                        const itemKey = item.id || `idx_${idx}`;
                        const isExpanded = Boolean(expandedItems[itemKey]);
                        const isProfileItem = Boolean(isProfileRun || item.is_profile || item.type === 'profile');
                        const rawContent = isProfileItem ? (item.bio || item.text || item.content || '—') : (item.text || item.content || item.bio || '—');
                        const shouldTruncate = rawContent.length > 200;
                        const displayText = !shouldTruncate || isExpanded ? rawContent : `${rawContent.slice(0, 190)}...`;

                        if (isProfileItem) {
                          const displayName = item.name || item.displayName || item.author_name || '—';
                          const handleStr = item.handle || item.author_username || item.username;
                          return (
                            <div key={idx} className="p-4 bg-gray-950/70 border border-gray-800/80 rounded-2xl hover:border-gray-700 transition-colors">
                              <div className="flex items-center justify-between">
                                <div className="flex items-center gap-2">
                                  <span className="text-xs uppercase font-bold px-2 py-0.5 rounded bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
                                    Profile
                                  </span>
                                  <span className="text-sm font-semibold text-white">{displayName}</span>
                                  {handleStr && (
                                    <span className="text-xs text-gray-400">@{handleStr}</span>
                                  )}
                                  {(item.is_blue_verified || item.verified) && (
                                    <span className="text-sky-400 text-xs font-bold" title="Verified">✓</span>
                                  )}
                                </div>
                                {item.url && (
                                  <a
                                    href={item.url}
                                    target="_blank"
                                    rel="noopener noreferrer"
                                    className="text-xs text-sky-400 hover:underline flex items-center gap-1 font-medium"
                                  >
                                    Source Profile ↗
                                  </a>
                                )}
                              </div>
                              <div className="mt-2">
                                <p className="text-xs text-gray-300 whitespace-pre-wrap leading-relaxed">
                                  {displayText}
                                </p>
                                {shouldTruncate && (
                                  <button
                                    onClick={() => setExpandedItems((prev) => ({ ...prev, [itemKey]: !isExpanded }))}
                                    className="text-[11px] text-sky-400 hover:text-sky-300 mt-1 font-medium"
                                  >
                                    {isExpanded ? 'Show less' : 'Show full bio'}
                                  </button>
                                )}
                              </div>
                              <div className="flex flex-wrap items-center gap-4 mt-3 pt-2.5 border-t border-gray-900 text-xs text-gray-400">
                                <span>Location: <strong className="text-gray-200">{item.location || '—'}</strong></span>
                                <span>Website: {item.website ? <a href={item.website.startsWith('http') ? item.website : `https://${item.website}`} target="_blank" rel="noopener noreferrer" className="text-sky-400 hover:underline">{item.website}</a> : <strong className="text-gray-200">—</strong>}</span>
                                <span>Followers: <strong className="text-gray-200">{item.followers !== undefined && item.followers !== null ? Number(item.followers).toLocaleString() : '—'}</strong></span>
                                <span>Following: <strong className="text-gray-200">{item.following !== undefined && item.following !== null ? Number(item.following).toLocaleString() : '—'}</strong></span>
                                <span>Posts: <strong className="text-gray-200">{item.posts_count !== undefined && item.posts_count !== null ? Number(item.posts_count).toLocaleString() : (item.posts !== undefined && item.posts !== null ? Number(item.posts).toLocaleString() : '—')}</strong></span>
                                {item.joined ? (
                                  <span>Joined: <strong className="text-gray-200">{item.joined}</strong></span>
                                ) : null}
                                <span>Fetched: <strong className="text-gray-200 font-mono">{String(item.fetched_at || item.created_at || '').slice(0, 10) || '—'}</strong></span>
                              </div>
                            </div>
                          );
                        }

                        return (
                          <div key={idx} className="p-4 bg-gray-950/70 border border-gray-800/80 rounded-2xl hover:border-gray-700 transition-colors">
                            <div className="flex items-center justify-between">
                              <div className="flex items-center gap-2">
                                <span className="text-xs uppercase font-bold px-2 py-0.5 rounded bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
                                  {item.platform || viewingJob.platform || 'twitter'}
                                </span>
                                <span className="text-sm font-semibold text-white">{item.author_name || item.displayName || item.author_username || 'Lead'}</span>
                                {(item.author_username || item.username) && (
                                  <span className="text-xs text-gray-400">@{item.author_username || item.username}</span>
                                )}
                                {(item.is_pinned || item.isPinned || (item.signals && item.signals.is_pinned)) && (
                                  <span className="text-[10px] font-bold uppercase px-1.5 py-0.5 rounded bg-blue-500/20 text-blue-300 border border-blue-500/40">
                                    📌 Pinned
                                  </span>
                                )}
                                {item.leadScore !== undefined && item.leadScore !== null && !isUnevaluated(item) ? (
                                  <span className={`text-[11px] font-bold font-mono ml-1 px-2 py-0.5 rounded border ${
                                    item.leadScore >= 70
                                      ? 'bg-emerald-500/10 text-emerald-400 border-emerald-500/30'
                                      : item.leadScore >= 40
                                      ? 'bg-amber-500/10 text-amber-400 border-amber-500/30'
                                      : 'bg-rose-500/10 text-rose-400 border-rose-500/30'
                                  }`}>
                                    Score: {item.leadScore}/100
                                  </span>
                                ) : (
                                  <span className="text-[11px] font-bold font-mono ml-1 px-2 py-0.5 rounded border bg-gray-800 text-gray-400 border-gray-700">
                                    Unevaluated
                                  </span>
                                )}
                                {item.leadCategory && (
                                  <span className="text-[10px] uppercase font-semibold text-gray-400 border border-gray-800 bg-gray-900 px-1.5 py-0.5 rounded">
                                    {item.leadCategory === 'unevaluated' ? 'Unevaluated' : item.leadCategory}
                                  </span>
                                )}
                                {item.evaluator && (
                                  <span className={`text-[10px] font-mono uppercase px-1.5 py-0.5 rounded border ${
                                    item.evaluator === 'llm'
                                      ? 'bg-purple-500/10 text-purple-400 border-purple-500/30'
                                      : 'bg-gray-800 text-gray-400 border-gray-700'
                                  }`}>
                                    {item.evaluator === 'unevaluated' ? 'Unevaluated' : item.evaluator}
                                  </span>
                                )}
                              </div>
                              {item.url && (
                                <a
                                  href={item.url}
                                  target="_blank"
                                  rel="noopener noreferrer"
                                  className="text-xs text-sky-400 hover:underline flex items-center gap-1 font-medium"
                                >
                                  Source Profile ↗
                                </a>
                              )}
                            </div>
                            {item.evaluator === 'llm' && item.leadReason && (
                              <div className="mt-2 px-2.5 py-1.5 rounded-lg bg-sky-950/40 border border-sky-800/40 text-[11px] text-sky-300 flex items-center gap-1.5">
                                <span className="font-semibold text-sky-400">AI Agent:</span> {item.leadReason}
                              </div>
                            )}
                            {item.evaluator === 'rule' && item.leadReason && (
                              <div className="mt-2 px-2.5 py-1.5 rounded-lg bg-amber-950/30 border border-amber-800/30 text-[11px] text-amber-300 flex items-center gap-1.5">
                                <span className="font-semibold text-amber-400">Rule filter:</span> {item.leadReason.replace(/^(?:Rule filter:\s*)+/i, '')}
                              </div>
                            )}
                            {(item.evaluator !== 'llm' && item.evaluator !== 'rule' && item.evaluator !== 'unevaluated') && item.leadReason && (
                              <div className="mt-2 px-2.5 py-1.5 rounded-lg bg-sky-950/40 border border-sky-800/40 text-[11px] text-sky-300 flex items-center gap-1.5">
                                <span className="font-semibold text-sky-400">AI Agent:</span> {item.leadReason}
                              </div>
                            )}
                            {item.evaluator === 'llm' && item.evidenceSpans && item.evidenceSpans.length > 0 && (
                              <div className="mt-1.5 px-2.5 py-1 rounded-lg bg-emerald-950/40 border border-emerald-800/40 text-[11px] text-emerald-300 font-mono">
                                <span className="font-semibold text-emerald-400">Evidence:</span> "{item.evidenceSpans[0]}"
                              </div>
                            )}
                            <div className="mt-2">
                              <p className="text-xs text-gray-300 whitespace-pre-wrap leading-relaxed">
                                {displayText}
                              </p>
                              {shouldTruncate && (
                                <button
                                  onClick={() => setExpandedItems((prev) => ({ ...prev, [itemKey]: !isExpanded }))}
                                  className="text-[11px] text-sky-400 hover:text-sky-300 mt-1 font-medium"
                                >
                                  {isExpanded ? 'Show less' : 'Show full post'}
                                </button>
                              )}
                            </div>
                            <div className="flex flex-wrap items-center gap-4 mt-3 pt-2.5 border-t border-gray-900 text-xs text-gray-500">
                      {/* NEW FEATURE: Verifiable Result Metrics with NULL as "—" */}
                      {(item.platform === 'telegram' || viewingJob.platform === 'telegram') ? (
                        <>
                          <span className="flex items-center gap-1 text-gray-400">
                            <Eye size={13} className="text-cyan-400/80" />
                            <span>Views: <strong className="text-gray-200">{(item.views !== undefined && item.views !== null) ? item.views : (item.view_count !== undefined && item.view_count !== null ? item.view_count : '—')}</strong></span>
                          </span>
                          <span className="flex items-center gap-1 text-gray-400">
                            <Send size={13} className="text-sky-400/80" />
                            <span>Forwards: <strong className="text-gray-200">{(item.forwards !== undefined && item.forwards !== null) ? item.forwards : (item.retweet_count !== undefined && item.retweet_count !== null ? item.retweet_count : '—')}</strong></span>
                          </span>
                          <span className="flex items-center gap-1 text-gray-400">
                            <Heart size={13} className="text-rose-400/80" />
                            <span>Reactions: <strong className="text-gray-200">{(item.reactions !== undefined && item.reactions !== null) ? item.reactions : (item.like_count !== undefined && item.like_count !== null ? item.like_count : (item.likes !== undefined && item.likes !== null ? item.likes : '—'))}</strong></span>
                          </span>
                          {item.channel && (
                            <span className="text-gray-400">Channel: <strong className="text-gray-200">@{item.channel}</strong></span>
                          )}
                        </>
                      ) : (
                        <>
                          <span className="flex items-center gap-1 text-gray-400">
                            <Heart size={13} className="text-rose-400/80" />
                            <span>Likes: <strong className="text-gray-200">{(item.like_count !== undefined && item.like_count !== null) ? item.like_count : (item.likes !== undefined && item.likes !== null ? item.likes : '—')}</strong></span>
                          </span>
                          <span className="flex items-center gap-1 text-gray-400">
                            <MessageSquare size={13} className="text-sky-400/80" />
                            <span>Comments: <strong className="text-gray-200">{(item.reply_count !== undefined && item.reply_count !== null) ? item.reply_count : (item.replies !== undefined && item.replies !== null ? item.replies : '—')}</strong></span>
                          </span>
                          <span className="flex items-center gap-1 text-gray-400">
                            <RotateCcw size={13} className="text-emerald-400/80" />
                            <span>Retweets: <strong className="text-gray-200">{(item.retweet_count !== undefined && item.retweet_count !== null) ? item.retweet_count : (item.retweets !== undefined && item.retweets !== null ? item.retweets : '—')}</strong></span>
                          </span>
                        </>
                      )}
                      <span>Followers / Members: <strong className="text-gray-200">{(item.author_followers !== undefined && item.author_followers !== null) ? item.author_followers : (item.followers !== undefined && item.followers !== null ? item.followers : '—')}</strong></span>
                      {item.created_at && (
                        <span className="text-gray-400 font-mono">Posted: {String(item.created_at).slice(0, 10)}</span>
                      )}
                      </div>
                    </div>
                  );

                })
              )}
            </>
          );
        })()}
      </div>

            <div className="pt-3 border-t border-gray-800 flex justify-end shrink-0">
              <button
                onClick={() => setViewingJob(null)}
                className="px-4 py-2 bg-gray-800 hover:bg-gray-700 text-xs font-semibold text-white rounded-xl transition-colors"
              >
                Close
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Subscription Upgrade Modal */}
      <UpgradeSubscriptionModal
        isOpen={isUpgradeModalOpen}
        onClose={() => setIsUpgradeModalOpen(false)}
        userEmail={user?.email}
      />
    </div>
  );
}
