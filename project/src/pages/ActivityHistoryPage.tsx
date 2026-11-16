import { useState, useEffect } from 'react';
import {
  History, Search, Filter, Calendar, CheckCircle2, AlertCircle, Clock,
  ArrowRight, RefreshCw, Database, Terminal, Shield, Zap, Users, User,
  Play, ExternalLink, ChevronRight, Activity, Award
} from 'lucide-react';
import { api, type ActivityEvent } from '@/api/client';
import { timeAgo, formatNumber } from '@/components/ui';

interface UserDirectoryItem {
  id: string;
  email: string;
  name: string;
  role: string;
  plan: string;
  status: string;
  credits: number;
  jobsCount: number;
  itemsScraped: number;
  activityCount: number;
  lastActive: string;
  createdAt: string;
  isOwner: boolean;
}

export function ActivityHistoryPage({ user }: { user?: any }) {
  const [usersList, setUsersList] = useState<UserDirectoryItem[]>([]);
  const [selectedUserEmail, setSelectedUserEmail] = useState<string>(
    user?.email || ''
  );
  const [events, setEvents] = useState<ActivityEvent[]>([]);
  const [loading, setLoading] = useState(true);
  const [usersLoading, setUsersLoading] = useState(false);
  const [categoryFilter, setCategoryFilter] = useState('all');
  const [search, setSearch] = useState('');
  const [userSearch, setUserSearch] = useState('');
  const [totalCount, setTotalCount] = useState(0);

  const isAdmin = Boolean(user && (user.role === 'admin' || user.role === 'owner'));

  // Load registered users directory for admin
  const loadUsersDirectory = async () => {
    if (!isAdmin) return;
    setUsersLoading(true);
    try {
      const data = await api.getUsers();
      if (data && data.length > 0) {
        setUsersList(data);
      }
    } catch (err) {
      console.error('Failed to load users directory:', err);
    } finally {
      setUsersLoading(false);
    }
  };

  // Load activity events for selected user
  const loadActivity = async () => {
    setLoading(true);
    try {
      const res = await api.getActivity({
        user_email: selectedUserEmail,
        category: categoryFilter !== 'all' ? categoryFilter : undefined,
        limit: 100,
      });
      setEvents(res.events || []);
      setTotalCount(res.total || 0);
    } catch (err) {
      console.error('Failed to load user activity:', err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadUsersDirectory();
  }, [isAdmin]);

  useEffect(() => {
    loadActivity();
  }, [selectedUserEmail, categoryFilter]);

  const activeSelectedUser = usersList.find(
    (u) => u.email.toLowerCase() === selectedUserEmail.toLowerCase()
  ) || {
    id: 'active_usr',
    email: selectedUserEmail,
    name: selectedUserEmail.split('@')[0],
    role: isAdmin ? 'owner' : 'user',
    plan: isAdmin ? 'Enterprise Admin' : 'Free Trial',
    status: 'APPROVED',
    credits: isAdmin ? 999999 : 10,
    jobsCount: 0,
    itemsScraped: 0,
    activityCount: totalCount,
    lastActive: new Date().toISOString(),
    createdAt: new Date().toISOString(),
    isOwner: isAdmin,
  };

  const filteredUsers = usersList.filter((u) => {
    if (!userSearch) return true;
    const q = userSearch.toLowerCase();
    return (
      u.email.toLowerCase().includes(q) ||
      u.name.toLowerCase().includes(q) ||
      u.plan.toLowerCase().includes(q)
    );
  });

  const filteredEvents = events.filter((e) => {
    if (!search) return true;
    const q = search.toLowerCase();
    return (
      e.description.toLowerCase().includes(q) ||
      e.eventType.toLowerCase().includes(q) ||
      e.category.toLowerCase().includes(q)
    );
  });

  const getCategoryBadge = (category: string) => {
    switch (category) {
      case 'scraping':
        return <span className="px-2 py-0.5 rounded-full text-[11px] font-semibold bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">Scraping</span>;
      case 'auth':
        return <span className="px-2 py-0.5 rounded-full text-[11px] font-semibold bg-cyan-500/10 text-cyan-400 border border-cyan-500/20">Account</span>;
      case 'schedule':
        return <span className="px-2 py-0.5 rounded-full text-[11px] font-semibold bg-amber-500/10 text-amber-400 border border-amber-500/20">Schedule</span>;
      case 'export':
        return <span className="px-2 py-0.5 rounded-full text-[11px] font-semibold bg-purple-500/10 text-purple-400 border border-purple-500/20">Export</span>;
      default:
        return <span className="px-2 py-0.5 rounded-full text-[11px] font-semibold bg-gray-500/10 text-gray-400 border border-gray-500/20">{category}</span>;
    }
  };

  const getStatusIcon = (status: string) => {
    if (status === 'completed' || status === 'succeeded') {
      return <CheckCircle2 size={15} className="text-emerald-400 shrink-0" />;
    }
    if (status === 'running') {
      return <RefreshCw size={15} className="text-cyan-400 animate-spin shrink-0" />;
    }
    return <AlertCircle size={15} className="text-rose-400 shrink-0" />;
  };

  return (
    <div className="p-4 lg:p-6 space-y-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-white flex items-center gap-2.5">
            <History className="text-emerald-400" size={24} />
            User Activity & Work Tracking
          </h1>
          <p className="text-sm text-gray-400 mt-1">
            {isAdmin
              ? 'Real-time multi-tenant monitoring ledger: inspect accounts, scrape workloads, and full audit logs for any user.'
              : 'Complete persistent lifetime record of all scraping jobs, searches, and workflows on your account.'}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => { loadUsersDirectory(); loadActivity(); }}
            disabled={loading || usersLoading}
            className="flex items-center gap-2 px-3.5 py-2 rounded-xl bg-gray-900 border border-gray-800 hover:border-gray-700 text-xs font-semibold text-gray-200 transition-all hover:bg-gray-800 disabled:opacity-50 cursor-pointer"
          >
            <RefreshCw size={13} className={loading || usersLoading ? 'animate-spin' : ''} />
            Refresh
          </button>
        </div>
      </div>

      {/* ADMIN TRACKING DIRECTORY TABLE (ADMIN ONLY) */}
      {isAdmin && (
        <div className="bg-gray-900 border border-gray-800 rounded-2xl overflow-hidden shadow-xl">
          <div className="p-4 sm:p-5 border-b border-gray-800 flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3 bg-gray-950/60">
            <div>
              <div className="flex items-center gap-2">
                <Users className="text-cyan-400" size={18} />
                <h2 className="text-base font-bold text-white">System Accounts Directory</h2>
                <span className="text-[11px] px-2 py-0.5 rounded-full bg-cyan-500/10 text-cyan-400 border border-cyan-500/20 font-semibold">
                  {usersList.length} Accounts Registered
                </span>
              </div>
              <p className="text-xs text-gray-400 mt-0.5">
                Click any user row to view their complete live working ledger, jobs, and history below.
              </p>
            </div>
            <div className="relative w-full sm:w-64">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-500" size={13} />
              <input
                type="text"
                value={userSearch}
                onChange={(e) => setUserSearch(e.target.value)}
                placeholder="Search by email or name..."
                className="w-full bg-gray-900 border border-gray-800 focus:border-cyan-500 rounded-xl pl-8 pr-3 py-1.5 text-xs text-white placeholder-gray-500 outline-none transition-colors"
              />
            </div>
          </div>

          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs">
              <thead className="bg-gray-950/80 text-gray-400 uppercase tracking-wider font-semibold border-b border-gray-800">
                <tr>
                  <th className="py-3 px-4">User / Account</th>
                  <th className="py-3 px-4">Role & Plan</th>
                  <th className="py-3 px-4">Scraping Jobs</th>
                  <th className="py-3 px-4">Items Scraped</th>
                  <th className="py-3 px-4">Credits</th>
                  <th className="py-3 px-4">Last Activity</th>
                  <th className="py-3 px-4 text-right">Inspect History</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-800/80">
                {filteredUsers.map((u, idx) => {
                  const isSelected = u.email.toLowerCase() === selectedUserEmail.toLowerCase();
                  return (
                    <tr
                      key={u.id || u.email}
                      onClick={() => setSelectedUserEmail(u.email)}
                      className={`cursor-pointer transition-colors ${
                        isSelected
                          ? 'bg-emerald-500/10 border-l-4 border-l-emerald-400'
                          : u.isOwner
                          ? 'bg-gray-950/40 hover:bg-gray-800/50'
                          : 'hover:bg-gray-800/30'
                      }`}
                    >
                      <td className="py-3.5 px-4">
                        <div className="flex items-center gap-2.5">
                          <div className={`w-7 h-7 rounded-lg flex items-center justify-center font-bold text-xs ${
                            u.isOwner
                              ? 'bg-gradient-to-br from-amber-500 to-orange-500 text-white shadow-md shadow-orange-500/20'
                              : 'bg-emerald-500/20 text-emerald-400 border border-emerald-500/30'
                          }`}>
                            {u.name[0]?.toUpperCase() || 'U'}
                          </div>
                          <div className="min-w-0">
                            <div className="flex items-center gap-1.5">
                              <span className="font-semibold text-white truncate">{u.name}</span>
                              {u.isOwner && (
                                <span className="px-1.5 py-0.2 rounded bg-amber-500/10 border border-amber-500/30 text-[10px] font-bold text-amber-400 uppercase">
                                  Owner
                                </span>
                              )}
                            </div>
                            <span className="text-[11px] text-gray-400 block font-mono truncate">{u.email}</span>
                          </div>
                        </div>
                      </td>

                      <td className="py-3.5 px-4">
                        <div className="space-y-0.5">
                          <span className={`inline-block px-2 py-0.5 rounded text-[10px] font-bold tracking-wide uppercase ${
                            u.isOwner
                              ? 'bg-purple-500/10 text-purple-400 border border-purple-500/20'
                              : 'bg-cyan-500/10 text-cyan-400 border border-cyan-500/20'
                          }`}>
                            {u.plan}
                          </span>
                          <span className="text-[10px] text-gray-500 block">Status: {u.status}</span>
                        </div>
                      </td>

                      <td className="py-3.5 px-4 font-mono font-medium text-white">
                        {u.jobsCount} jobs
                      </td>

                      <td className="py-3.5 px-4 font-mono font-medium text-emerald-400">
                        {formatNumber(u.itemsScraped)} items
                      </td>

                      <td className="py-3.5 px-4 font-mono">
                        {u.isOwner ? (
                          <span className="text-amber-400 font-semibold">Unlimited (∞)</span>
                        ) : (
                          <span className="text-gray-300">{u.credits}</span>
                        )}
                      </td>

                      <td className="py-3.5 px-4 text-gray-400 font-mono">
                        {u.lastActive ? timeAgo(u.lastActive) : 'Recently'}
                      </td>

                      <td className="py-3.5 px-4 text-right">
                        <button
                          onClick={(e) => {
                            e.stopPropagation();
                            setSelectedUserEmail(u.email);
                          }}
                          className={`px-2.5 py-1 rounded-lg text-xs font-semibold transition-all flex items-center gap-1 ml-auto cursor-pointer ${
                            isSelected
                              ? 'bg-emerald-500 text-gray-950 shadow-md shadow-emerald-500/20'
                              : 'bg-gray-800 text-gray-300 hover:text-white hover:bg-gray-700'
                          }`}
                        >
                          {isSelected ? 'Inspecting' : 'View Work'}
                          <ChevronRight size={13} />
                        </button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Filter and Search Bar for Activities */}
      <div className="bg-gray-900 border border-gray-800 rounded-2xl p-4 flex flex-col md:flex-row items-center justify-between gap-4">
        <div className="relative w-full md:w-80">
          <Search className="absolute left-3.5 top-1/2 -translate-y-1/2 text-gray-500" size={15} />
          <input
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search activity events..."
            className="w-full bg-gray-950 border border-gray-800 focus:border-emerald-500 rounded-xl pl-9 pr-3.5 py-2 text-xs text-white placeholder-gray-500 outline-none transition-colors"
          />
        </div>

        <div className="flex items-center gap-2 w-full md:w-auto overflow-x-auto pb-1 md:pb-0">
          {[
            { id: 'all', label: 'All Activities' },
            { id: 'scraping', label: 'Scraping Jobs' },
            { id: 'schedule', label: 'Schedules' },
            { id: 'auth', label: 'Account' },
          ].map((cat) => (
            <button
              key={cat.id}
              onClick={() => setCategoryFilter(cat.id)}
              className={`px-3 py-1.5 rounded-lg text-xs font-semibold whitespace-nowrap transition-colors cursor-pointer ${
                categoryFilter === cat.id
                  ? 'bg-emerald-500/20 text-emerald-400 border border-emerald-500/30'
                  : 'text-gray-400 hover:text-white bg-gray-950 border border-gray-800'
              }`}
            >
              {cat.label}
            </button>
          ))}
        </div>
      </div>

      {/* Activity Timeline List for Selected User */}
      <div className="bg-gray-900 border border-gray-800 rounded-2xl overflow-hidden shadow-xl">
        <div className="p-4 border-b border-gray-800 flex flex-col sm:flex-row items-start sm:items-center justify-between gap-2 bg-gray-950/40">
          <div className="flex items-center gap-2.5">
            <span className="text-xs font-semibold text-gray-400 uppercase tracking-wider">
              {filteredEvents.length} Recorded Events ({totalCount} total)
            </span>
            <span className="text-gray-600">·</span>
            <span className="text-xs font-mono font-medium text-emerald-400 bg-emerald-500/10 px-2 py-0.5 rounded border border-emerald-500/20">
              Tracking: {selectedUserEmail}
            </span>
          </div>

          <div className="flex items-center gap-2 text-xs text-gray-400">
            <span>Plan: <b className="text-gray-200">{activeSelectedUser.plan}</b></span>
            <span>·</span>
            <span>Scraped: <b className="text-emerald-400">{formatNumber(activeSelectedUser.itemsScraped)}</b></span>
          </div>
        </div>

        {loading ? (
          <div className="p-12 text-center text-gray-500 flex flex-col items-center justify-center gap-2">
            <RefreshCw size={20} className="animate-spin text-emerald-400" />
            <span className="text-xs">Loading activity ledger from database...</span>
          </div>
        ) : filteredEvents.length === 0 ? (
          <div className="p-12 text-center text-gray-500 space-y-2">
            <History size={32} className="mx-auto text-gray-600 mb-2" />
            <p className="text-sm font-semibold text-gray-300">No activity events found for {selectedUserEmail}</p>
            <p className="text-xs text-gray-500 max-w-sm mx-auto">
              {search
                ? 'No activities match your query. Try broadening your filter.'
                : 'Activities appear here automatically whenever scrapers are launched, queries are run, or credentials change.'}
            </p>
          </div>
        ) : (
          <div className="divide-y divide-gray-800/80">
            {filteredEvents.map((ev) => (
              <div key={ev.id} className="p-4 sm:p-5 hover:bg-gray-800/30 transition-colors flex items-start gap-4">
                <div className="mt-0.5">{getStatusIcon(ev.status)}</div>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2.5 flex-wrap mb-1">
                    {getCategoryBadge(ev.category)}
                    <span className="text-xs font-semibold text-white">{ev.eventType}</span>
                    {ev.resourceId && (
                      <span className="text-[10px] text-gray-500 font-mono bg-gray-950 px-1.5 py-0.5 rounded border border-gray-800">
                        {ev.resourceId}
                      </span>
                    )}
                  </div>
                  <p className="text-xs sm:text-sm text-gray-300 leading-relaxed font-normal">{ev.description}</p>
                </div>
                <div className="text-right shrink-0">
                  <div className="text-xs text-gray-400 font-mono">{timeAgo(ev.createdAt)}</div>
                  <div className="text-[10px] text-gray-600 mt-0.5">
                    {new Date(ev.createdAt).toLocaleDateString()}
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

