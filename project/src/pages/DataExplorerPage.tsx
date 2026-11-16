import { useState, useMemo, useEffect } from 'react';
import {
  Search, Download, Filter, Table2, LayoutGrid, CheckCircle2,
  TrendingUp, MessageSquare, Eye, Heart, ChevronLeft, ChevronRight,
  Send, // NEW FEATURE: Telegram Send icon
} from 'lucide-react';
import { scrapedItems as mockItems, platforms } from '@/data/mockData';
import { PlatformIcon, formatNumber, timeAgo } from '@/components/ui';
import { api } from '@/api/client';
import type { Platform, ScrapedItem } from '@/types';

const sentimentColors: Record<string, string> = {
  positive: 'text-emerald-400 bg-emerald-500/10 border-emerald-500/20',
  neutral: 'text-gray-400 bg-gray-500/10 border-gray-500/20',
  negative: 'text-red-400 bg-red-500/10 border-red-500/20',
};


export function DataExplorerPage({ user }: { user?: any }) {
  const isAdmin = Boolean(user && (user.role === 'admin' || user.role === 'owner'));
  const [items, setItems] = useState<ScrapedItem[]>([]);
  const [search, setSearch] = useState('');
  const [platformFilter, setPlatformFilter] = useState<Platform | 'all'>('all');
  const [sentimentFilter, setSentimentFilter] = useState<string>('all');
  const [onlyLeads, setOnlyLeads] = useState<boolean>(false);
  const [view, setView] = useState<'table' | 'grid'>('table');
  const [page, setPage] = useState(1);
  const [limit, setLimit] = useState(25);
  const [totalCount, setTotalCount] = useState(0);
  const [totalPages, setTotalPages] = useState(1);
  const [loading, setLoading] = useState(false);
  const [selected, setSelected] = useState<Set<string>>(new Set());

  useEffect(() => {
    let mounted = true;
    async function loadData() {
      setLoading(true);
      try {
        const res = await api.getScrapedData({
          page,
          limit,
          search: search.trim() || undefined,
          platform: platformFilter !== 'all' ? platformFilter : undefined,
          sentiment: sentimentFilter !== 'all' ? sentimentFilter : undefined,
          user_email: user?.email,
        });
        if (!mounted) return;
        if (res.items && res.items.length > 0) {
          setItems(res.items);
          setTotalCount(res.total);
          setTotalPages(res.totalPages || Math.ceil(res.total / limit));
        } else {
          // Zero ghost reads: When database is purged or empty, accurately reflect empty state
          setItems([]);
          setTotalCount(0);
          setTotalPages(1);
        }
      } catch (err) {
        console.error('Failed to load scraped data from API:', err);
      } finally {
        if (mounted) setLoading(false);
      }
    }
    loadData();
    return () => {
      mounted = false;
    };
  }, [page, limit, search, platformFilter, sentimentFilter]);

  // When filters change, reset to page 1
  const handleFilterChange = (setter: (v: any) => void, val: any) => {
    setter(val);
    setPage(1);
  };

  const displayedItems = useMemo(() => {
    if (!onlyLeads) return items;
    return items.filter((it) => it.isLead === true);
  }, [items, onlyLeads]);

  const toggleSelect = (id: string) => {
    const next = new Set(selected);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    setSelected(next);
  };

  const toggleSelectAll = () => {
    if (selected.size === displayedItems.length) setSelected(new Set());
    else setSelected(new Set(displayedItems.map((i) => i.id)));
  };

  return (
    <div className="p-4 lg:p-6 space-y-6">
      <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-white flex items-center gap-2">
            Data Explorer
            {loading && <span className="text-xs px-2 py-0.5 rounded-full bg-emerald-500/20 text-emerald-400 font-normal animate-pulse">Syncing...</span>}
          </h1>
          <p className="text-sm text-gray-400 mt-1">
            {totalCount.toLocaleString()} total verified records {onlyLeads && <span className="text-emerald-400 font-medium">(Filtered to qualified leads)</span>} · {selected.size} selected
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => setOnlyLeads(!onlyLeads)}
            className={`flex items-center gap-2 px-3 py-2 rounded-xl text-xs font-semibold border transition-all ${
              onlyLeads
                ? 'bg-emerald-500/20 text-emerald-300 border-emerald-500/40 shadow-lg shadow-emerald-500/10'
                : 'bg-gray-900 text-gray-400 border-gray-800 hover:text-white'
            }`}
          >
            <CheckCircle2 size={14} className={onlyLeads ? "text-emerald-400" : "text-gray-500"} />
            {onlyLeads ? "Showing High-Intent Leads Only" : "Filter Qualified Leads"}
          </button>
          <div className="flex items-center gap-1 bg-gray-900 border border-gray-800 rounded-lg p-1">
            <button onClick={() => setView('table')} className={`p-2 rounded-md transition-colors ${view === 'table' ? 'bg-gray-800 text-white' : 'text-gray-500 hover:text-white'}`}>
              <Table2 size={16} />
            </button>
            <button onClick={() => setView('grid')} className={`p-2 rounded-md transition-colors ${view === 'grid' ? 'bg-gray-800 text-white' : 'text-gray-500 hover:text-white'}`}>
              <LayoutGrid size={16} />
            </button>
          </div>
          <button
            onClick={async () => {
              try {
                await api.downloadExport({ format: 'csv', q: search || undefined });
              } catch (err: any) {
                console.error("Export error:", err);
              }
            }}
            className="flex items-center gap-2 bg-gradient-to-r from-emerald-500 to-cyan-500 hover:from-emerald-400 hover:to-cyan-400 px-4 py-2.5 rounded-xl font-semibold text-sm text-white transition-all shadow-lg shadow-emerald-500/20"
          >
            <Download size={16} /> Export
          </button>
        </div>
      </div>

      {/* Filters */}
      <div className="flex flex-col lg:flex-row items-stretch lg:items-center gap-3">
        <div className="flex items-center gap-2 bg-gray-900 border border-gray-800 rounded-lg px-3 py-2.5 flex-1">
          <Search size={16} className="text-gray-500" />
          <input
            type="text"
            value={search}
            onChange={(e) => handleFilterChange(setSearch, e.target.value)}
            placeholder="Search content, username, or display name..."
            className="bg-transparent text-sm text-white placeholder-gray-500 outline-none flex-1"
          />
        </div>
        <select
          value={platformFilter}
          onChange={(e) => handleFilterChange(setPlatformFilter, e.target.value as Platform | 'all')}
          className="bg-gray-900 border border-gray-800 rounded-lg px-3 py-2.5 text-sm text-white outline-none focus:border-emerald-500/50"
        >
          <option value="all" className="bg-gray-900">All Platforms</option>
          {platforms.map((p) => (
            <option key={p.id} value={p.id} className="bg-gray-900">{p.name}</option>
          ))}
        </select>
        <select
          value={sentimentFilter}
          onChange={(e) => handleFilterChange(setSentimentFilter, e.target.value)}
          className="bg-gray-900 border border-gray-800 rounded-lg px-3 py-2.5 text-sm text-white outline-none focus:border-emerald-500/50"
        >
          <option value="all" className="bg-gray-900">All Sentiments / Intents</option>
          <option value="positive" className="bg-gray-900">Positive (Qualified Leads)</option>
          <option value="neutral" className="bg-gray-900">Neutral (Discussion / Community)</option>
          <option value="negative" className="bg-gray-900">Negative (Noise / Promos)</option>
        </select>
        <select
          value={limit}
          onChange={(e) => { setLimit(Number(e.target.value)); setPage(1); }}
          className="bg-gray-900 border border-gray-800 rounded-lg px-3 py-2.5 text-sm text-gray-300 outline-none focus:border-emerald-500/50"
        >
          <option value={12}>12 per page</option>
          <option value={25}>25 per page</option>
          <option value={50}>50 per page</option>
          <option value={100}>100 per page</option>
        </select>
      </div>

      {/* Export bar when items selected */}
      {selected.size > 0 && (
        <div className="flex items-center justify-between bg-emerald-500/10 border border-emerald-500/30 rounded-xl px-4 py-3">
          <span className="text-sm text-emerald-400 font-medium">{selected.size} items selected</span>
          <div className="flex items-center gap-2">
            <button
              onClick={async () => {
                try {
                  await api.downloadExport({ format: 'json', q: search || undefined });
                } catch (err: any) {
                  console.error("Export error:", err);
                }
              }}
              className="text-xs text-gray-300 hover:text-white px-3 py-1.5 rounded-lg bg-gray-800 hover:bg-gray-700 transition-colors"
            >
              Export JSON
            </button>
            <button
              onClick={async () => {
                try {
                  await api.downloadExport({ format: 'csv', q: search || undefined });
                } catch (err: any) {
                  console.error("Export error:", err);
                }
              }}
              className="text-xs text-gray-300 hover:text-white px-3 py-1.5 rounded-lg bg-gray-800 hover:bg-gray-700 transition-colors"
            >
              Export CSV
            </button>
            <button onClick={() => setSelected(new Set())} className="text-xs text-gray-400 hover:text-white px-3 py-1.5">Clear</button>
          </div>
        </div>
      )}

      {/* Data view */}
      {view === 'table' ? (
        <div className="bg-gray-900 border border-gray-800 rounded-2xl overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full">
              <thead>
                <tr className="border-b border-gray-800 bg-gray-950/50">
                  <th className="px-4 py-3">
                    <input
                      type="checkbox"
                      checked={selected.size === displayedItems.length && displayedItems.length > 0}
                      onChange={toggleSelectAll}
                      className="w-4 h-4 rounded border-gray-600 bg-gray-800 text-emerald-500 focus:ring-emerald-500/50"
                    />
                  </th>
                  <th className="text-left text-xs font-semibold text-gray-500 uppercase tracking-wider px-4 py-3">User</th>
                  <th className="text-left text-xs font-semibold text-gray-500 uppercase tracking-wider px-4 py-3">Content</th>
                  <th className="text-left text-xs font-semibold text-gray-500 uppercase tracking-wider px-4 py-3">AI Buying Intent</th>
                  <th className="text-left text-xs font-semibold text-gray-500 uppercase tracking-wider px-4 py-3 hidden md:table-cell">Platform</th>
                  <th className="text-right text-xs font-semibold text-gray-500 uppercase tracking-wider px-4 py-3 hidden sm:table-cell">Engagement</th>
                  <th className="text-left text-xs font-semibold text-gray-500 uppercase tracking-wider px-4 py-3 hidden xl:table-cell">Scraped</th>
                </tr>
              </thead>
              <tbody>
                {displayedItems.length === 0 ? (
                  <tr>
                    <td colSpan={7} className="px-6 py-16 text-center">
                      <div className="max-w-sm mx-auto space-y-2">
                        <p className="text-sm font-semibold text-gray-300">No Matching Leads or Scraped Records Found</p>
                        <p className="text-xs text-gray-500 leading-relaxed">
                          Try clearing search filters or launching a new scraper across one of the 8 supported platforms.
                        </p>
                      </div>
                    </td>
                  </tr>
                ) : (
                  displayedItems.map((item) => {
                  const platform = platforms.find((p) => p.id === item.platform);
                  const isLead = item.isLead === true;
                  const badgeLabel = item.leadBadge || (isLead ? "QUALIFIED BUYER" : (item.leadCategory || "NON-BUYER / DISCUSSION"));
                  return (
                    <tr key={item.id} className="border-b border-gray-800/50 hover:bg-gray-800/30 transition-colors">
                      <td className="px-4 py-4">
                        <input
                          type="checkbox"
                          checked={selected.has(item.id)}
                          onChange={() => toggleSelect(item.id)}
                          className="w-4 h-4 rounded border-gray-600 bg-gray-800 text-emerald-500 focus:ring-emerald-500/50"
                        />
                      </td>
                      <td className="px-4 py-4">
                        <div className="flex items-center gap-2.5">
                          <div className="w-8 h-8 rounded-full bg-gradient-to-br from-gray-700 to-gray-800 flex items-center justify-center text-xs font-bold text-white flex-shrink-0">
                            {(item.displayName || item.username || '?')[0]?.toUpperCase() || '?'}
                          </div>
                          <div className="min-w-0">
                            <div className="flex items-center gap-1">
                              <span className="text-sm font-medium text-white truncate">{item.displayName}</span>
                              {item.isVerified && <CheckCircle2 size={12} className="text-sky-400 flex-shrink-0" />}
                            </div>
                            <span className="text-xs text-gray-500">
                              {item.platform === 'reddit' && item.subreddit
                                ? `r/${item.subreddit} · @${item.username}`
                                : item.platform === 'telegram' && item.channel
                                ? `@${item.channel}`
                                : `@${item.username}`}
                            </span>
                          </div>
                        </div>
                      </td>
                      <td className="px-4 py-4 max-w-xs">
                        <p className="text-sm text-gray-300 line-clamp-2" title={item.content}>{item.content}</p>
                        {item.evidenceSpans && item.evidenceSpans.length > 0 && (
                          <p className="text-[11px] text-emerald-400/90 font-mono mt-1 line-clamp-1">
                            Evidence: {item.evidenceSpans[0]}
                          </p>
                        )}
                      </td>
                      <td className="px-4 py-4">
                        <div className="space-y-1">
                          <span
                            className={`inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-[11px] font-bold border tracking-wide ${
                              isLead
                                ? 'bg-emerald-500/15 text-emerald-400 border-emerald-500/30 shadow-sm shadow-emerald-500/20'
                                : 'bg-gray-800/60 text-gray-400 border-gray-700/50'
                            }`}
                          >
                            <span className={`w-1.5 h-1.5 rounded-full ${isLead ? 'bg-emerald-400 animate-pulse' : 'bg-gray-500'}`} />
                            {badgeLabel}
                          </span>
                          {item.leadScore !== undefined && (
                            <p className="text-[10px] text-gray-400 font-mono">
                              Intent Score: <span className={isLead ? 'text-emerald-400 font-bold' : 'text-gray-400'}>{item.leadScore}/100</span>
                            </p>
                          )}
                        </div>
                      </td>
                      <td className="px-4 py-4 hidden md:table-cell">
                        <div className={`inline-flex items-center gap-1.5 px-2 py-1 rounded-md ${platform?.bgColor}`}>
                          <PlatformIcon platform={item.platform} className={`w-3.5 h-3.5 ${platform?.color}`} />
                          <span className="text-xs text-white">{platform?.name}</span>
                        </div>
                      </td>
                      <td className="px-4 py-4 hidden sm:table-cell">
                        {/* NEW FEATURE: Telegram Specific Metrics in Table */}
                        {item.platform === 'telegram' ? (
                          <div className="flex items-center justify-end gap-3 text-xs text-gray-400">
                            <span className="flex items-center gap-1" title="Views"><Eye size={12} className="text-cyan-400" />{formatNumber(item.views)}</span>
                            <span className="flex items-center gap-1" title="Forwards"><Send size={12} className="text-sky-400" />{formatNumber(item.forwards ?? item.retweets ?? 0)}</span>
                            <span className="flex items-center gap-1" title="Reactions"><Heart size={12} className="text-rose-400" />{formatNumber(item.reactions ?? item.likes ?? 0)}</span>
                          </div>
                        ) : (
                          <div className="flex items-center justify-end gap-3 text-xs text-gray-400">
                            <span className="flex items-center gap-1" title="Likes"><Heart size={12} />{formatNumber(item.likes)}</span>
                            <span className="flex items-center gap-1" title="Replies"><MessageSquare size={12} />{formatNumber(item.replies)}</span>
                            <span className="flex items-center gap-1" title="Views"><Eye size={12} />{formatNumber(item.views)}</span>
                          </div>
                        )}
                      </td>
                      <td className="px-4 py-4 hidden xl:table-cell">
                        <span className="text-xs text-gray-400">{timeAgo(item.scrapedAt)}</span>
                      </td>
                    </tr>
                  );

                }))}
              </tbody>
            </table>
          </div>
        </div>
      ) : displayedItems.length === 0 ? (
        <div className="bg-gray-900 border border-gray-800 rounded-2xl p-12 text-center">
          <div className="max-w-sm mx-auto space-y-2">
            <p className="text-sm font-semibold text-gray-300">No Matching Leads or Records</p>
            <p className="text-xs text-gray-500 leading-relaxed">
              No scraped items match your current filter selection. Reset filters or run a scraper job.
            </p>
          </div>
        </div>
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {displayedItems.map((item) => {
            const platform = platforms.find((p) => p.id === item.platform);
            return (
              <div key={item.id} className="bg-gray-900 border border-gray-800 rounded-2xl p-5 hover:border-gray-700 transition-colors">
                <div className="flex items-start gap-3 mb-3">
                  <div className="w-10 h-10 rounded-full bg-gradient-to-br from-gray-700 to-gray-800 flex items-center justify-center text-sm font-bold text-white flex-shrink-0">
                    {(item.displayName || item.username || '?')[0]?.toUpperCase() || '?'}
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-1">
                      <span className="text-sm font-medium text-white truncate">{item.displayName}</span>
                      {item.isVerified && <CheckCircle2 size={12} className="text-sky-400 flex-shrink-0" />}
                    </div>
                    <span className="text-xs text-gray-500">@{item.username}</span>
                  </div>
                  <div className={`w-7 h-7 rounded-lg ${platform?.bgColor} flex items-center justify-center flex-shrink-0`}>
                    <PlatformIcon platform={item.platform} className={`w-3.5 h-3.5 ${platform?.color}`} />
                  </div>
                </div>
                <p className="text-sm text-gray-300 leading-relaxed mb-4 line-clamp-3">{item.content}</p>
                <div className="flex items-center justify-between pt-3 border-t border-gray-800">
                  <div className="flex items-center gap-3 text-xs text-gray-400">
                    <span className="flex items-center gap-1"><Heart size={12} />{formatNumber(item.likes)}</span>
                    <span className="flex items-center gap-1"><MessageSquare size={12} />{formatNumber(item.replies)}</span>
                    <span className="flex items-center gap-1"><TrendingUp size={12} />{formatNumber(item.views)}</span>
                  </div>
                  {(() => {
                    const isLead = item.isLead === true;
                    const badgeLabel = item.leadBadge || (isLead ? "QUALIFIED BUYER" : (item.leadCategory || "NON-BUYER"));
                    return (
                      <span
                        className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-bold border ${
                          isLead
                            ? 'bg-emerald-500/15 text-emerald-400 border-emerald-500/30'
                            : 'bg-gray-800/60 text-gray-400 border-gray-700/50'
                        }`}
                      >
                        <span className={`w-1 h-1 rounded-full ${isLead ? 'bg-emerald-400 animate-pulse' : 'bg-gray-500'}`} />
                        {badgeLabel}
                      </span>
                    );
                  })()}
                </div>
              </div>
            );
          })}
        </div>
      )}

      {/* Pagination & Load More */}
      <div className="flex flex-col sm:flex-row items-center justify-between gap-4 pt-4 border-t border-gray-800/60">
        <p className="text-xs text-gray-500">
          Showing page <span className="text-white font-medium">{page}</span> of <span className="text-white font-medium">{totalPages}</span> ({totalCount.toLocaleString()} total items)
        </p>
        <div className="flex items-center gap-2">
          <button
            onClick={() => setPage(Math.max(1, page - 1))}
            disabled={page === 1}
            className="flex items-center gap-1 text-sm text-gray-400 hover:text-white disabled:opacity-40 disabled:cursor-not-allowed px-3 py-2 rounded-lg bg-gray-900 border border-gray-800 transition-colors"
          >
            <ChevronLeft size={14} /> Prev
          </button>
          <div className="flex items-center gap-1">
            {Array.from({ length: Math.min(totalPages, 5) }, (_, i) => {
              const p = i + 1;
              return (
                <button
                  key={p}
                  onClick={() => setPage(p)}
                  className={`w-9 h-9 rounded-lg text-sm font-medium transition-colors ${
                    page === p ? 'bg-emerald-500 text-white' : 'text-gray-400 hover:text-white bg-gray-900 border border-gray-800'
                  }`}
                >
                  {p}
                </button>
              );
            })}
            {totalPages > 5 && <span className="text-gray-600 px-1 text-xs">...</span>}
          </div>
          <button
            onClick={() => setPage(Math.min(totalPages, page + 1))}
            disabled={page >= totalPages}
            className="flex items-center gap-1 text-sm text-gray-400 hover:text-white disabled:opacity-40 disabled:cursor-not-allowed px-3 py-2 rounded-lg bg-gray-900 border border-gray-800 transition-colors"
          >
            Next <ChevronRight size={14} />
          </button>
        </div>
      </div>
    </div>
  );
}
