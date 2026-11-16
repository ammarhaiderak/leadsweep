import { useState, useEffect } from 'react';
import {
  ShieldAlert, Search, Filter, RefreshCw, AlertTriangle,
  Info, CheckCircle2, XCircle, Terminal, User, Clock, ChevronLeft, ChevronRight
} from 'lucide-react';
import { api } from '@/api/client';

interface AuditLogEntry {
  id: string;
  actor: string;
  action: string;
  target_type?: string;
  target_id?: string;
  user_email?: string;
  severity?: string;
  ip_address?: string;
  metadata_json?: string;
  created_at: string;
}

export function AdminAuditLogsPage() {
  const [logs, setLogs] = useState<AuditLogEntry[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Filters
  const [severityFilter, setSeverityFilter] = useState<string>('all');
  const [searchQuery, setSearchQuery] = useState('');
  const [emailFilter, setEmailFilter] = useState('');
  const [page, setPage] = useState(1);
  const limit = 25;

  const fetchLogs = async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await api.getAdminAuditLogs({
        severity: severityFilter,
        search: searchQuery || undefined,
        user_email: emailFilter || undefined,
        limit,
        offset: (page - 1) * limit,
      });
      setLogs(data.logs || []);
      setTotal(data.total || 0);
    } catch (err: any) {
      setError(err.message || 'Failed to fetch admin audit logs');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchLogs();
  }, [severityFilter, page]);

  const handleSearchSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    setPage(1);
    fetchLogs();
  };

  const totalPages = Math.max(1, Math.ceil(total / limit));

  const getSeverityBadge = (sev?: string) => {
    const s = (sev || 'info').toUpperCase();
    if (s === 'CRITICAL' || s === 'ERROR') {
      return (
        <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-semibold bg-rose-500/10 text-rose-400 border border-rose-500/30">
          <AlertTriangle size={11} /> {s}
        </span>
      );
    }
    if (s === 'WARN' || s === 'WARNING') {
      return (
        <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-semibold bg-amber-500/10 text-amber-400 border border-amber-500/30">
          <AlertTriangle size={11} /> {s}
        </span>
      );
    }
    return (
      <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-semibold bg-emerald-500/10 text-emerald-400 border border-emerald-500/30">
        <Info size={11} /> INFO
      </span>
    );
  };

  return (
    <div className="p-4 lg:p-6 space-y-6 max-w-7xl mx-auto">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4 border-b border-gray-800 pb-5">
        <div>
          <div className="flex items-center gap-3">
            <h1 className="text-2xl font-bold text-white flex items-center gap-2">
              <ShieldAlert className="text-emerald-400" size={24} />
              System Audit Logs
            </h1>
            <span className="px-2.5 py-0.5 rounded-full text-xs font-semibold bg-emerald-500/10 text-emerald-400 border border-emerald-500/30">
              Admin Exclusive
            </span>
          </div>
          <p className="text-sm text-gray-400 mt-1">
            Tamper-evident system-wide audit trail of user access, security events, scraper operations, and approvals.
          </p>
        </div>

        <button
          onClick={fetchLogs}
          disabled={loading}
          className="flex items-center gap-2 px-4 py-2 bg-gray-900 hover:bg-gray-800 text-gray-300 hover:text-white rounded-xl border border-gray-800 text-sm font-medium transition-colors"
        >
          <RefreshCw size={14} className={loading ? 'animate-spin text-emerald-400' : ''} />
          Refresh Stream
        </button>
      </div>

      {/* Filter and Search Bar */}
      <div className="bg-gray-900 border border-gray-800 rounded-2xl p-4 shadow-sm">
        <form onSubmit={handleSearchSubmit} className="grid grid-cols-1 md:grid-cols-4 gap-3">
          {/* Search Action / ID */}
          <div className="relative md:col-span-2">
            <Search className="absolute left-3.5 top-1/2 -translate-y-1/2 text-gray-500" size={16} />
            <input
              type="text"
              placeholder="Search action type, target ID, metadata..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="w-full bg-gray-950 border border-gray-800 rounded-xl pl-9 pr-4 py-2 text-sm text-white placeholder-gray-500 focus:outline-none focus:border-emerald-500/50"
            />
          </div>

          {/* User Email Filter */}
          <div className="relative">
            <User className="absolute left-3.5 top-1/2 -translate-y-1/2 text-gray-500" size={16} />
            <input
              type="text"
              placeholder="Filter by User Email"
              value={emailFilter}
              onChange={(e) => setEmailFilter(e.target.value)}
              className="w-full bg-gray-950 border border-gray-800 rounded-xl pl-9 pr-4 py-2 text-sm text-white placeholder-gray-500 focus:outline-none focus:border-emerald-500/50"
            />
          </div>

          {/* Severity Dropdown */}
          <div className="flex gap-2">
            <select
              value={severityFilter}
              onChange={(e) => {
                setSeverityFilter(e.target.value);
                setPage(1);
              }}
              className="flex-1 bg-gray-950 border border-gray-800 rounded-xl px-3 py-2 text-sm text-white focus:outline-none focus:border-emerald-500/50"
            >
              <option value="all">All Severities</option>
              <option value="INFO">INFO Only</option>
              <option value="WARN">WARN Only</option>
              <option value="ERROR">ERROR / Critical</option>
            </select>
            <button
              type="submit"
              className="px-4 py-2 bg-emerald-500 hover:bg-emerald-600 text-gray-950 rounded-xl font-medium text-sm transition-colors"
            >
              Filter
            </button>
          </div>
        </form>
      </div>

      {/* Audit Log Table */}
      <div className="bg-gray-900 border border-gray-800 rounded-2xl overflow-hidden shadow-sm">
        {error && (
          <div className="p-4 bg-rose-500/10 border-b border-rose-500/20 text-rose-400 text-sm flex items-center gap-2">
            <AlertTriangle size={16} />
            {error}
          </div>
        )}

        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead className="bg-gray-950/60 text-xs font-semibold uppercase text-gray-400 border-b border-gray-800">
              <tr>
                <th className="py-3 px-4">Timestamp</th>
                <th className="py-3 px-4">Severity</th>
                <th className="py-3 px-4">Action Event</th>
                <th className="py-3 px-4">Actor / Email</th>
                <th className="py-3 px-4">IP Address</th>
                <th className="py-3 px-4">Target Details</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-800/60 font-mono text-xs">
              {loading && logs.length === 0 ? (
                <tr>
                  <td colSpan={6} className="py-12 text-center text-gray-500 font-sans">
                    <RefreshCw className="animate-spin mx-auto mb-2 text-emerald-400" size={20} />
                    Loading system audit records...
                  </td>
                </tr>
              ) : logs.length === 0 ? (
                <tr>
                  <td colSpan={6} className="py-12 text-center text-gray-500 font-sans">
                    No audit records match the selected criteria.
                  </td>
                </tr>
              ) : (
                logs.map((log) => {
                  let meta: any = null;
                  try {
                    if (log.metadata_json) meta = JSON.parse(log.metadata_json);
                  } catch {}

                  return (
                    <tr key={log.id} className="hover:bg-gray-800/30 transition-colors">
                      <td className="py-3 px-4 text-gray-400 whitespace-nowrap">
                        {(() => {
                          const rawDate = (log as any).created_at || (log as any).createdAt || (log as any).timestamp;
                          if (!rawDate) return 'Just now';
                          const d = new Date(rawDate);
                          return isNaN(d.getTime()) ? String(rawDate) : d.toLocaleString();
                        })()}
                      </td>
                      <td className="py-3 px-4 whitespace-nowrap font-sans">
                        {getSeverityBadge(log.severity)}
                      </td>
                      <td className="py-3 px-4 font-semibold text-white whitespace-nowrap">
                        <span className="text-emerald-400 bg-emerald-500/10 px-2 py-0.5 rounded border border-emerald-500/20">
                          {log.action}
                        </span>
                      </td>
                      <td className="py-3 px-4 text-gray-300 font-sans">
                        <div className="flex flex-col">
                          <span className="font-medium text-white">{log.actor}</span>
                          {log.user_email && log.user_email !== log.actor && (
                            <span className="text-xs text-gray-500">{log.user_email}</span>
                          )}
                        </div>
                      </td>
                      <td className="py-3 px-4 text-gray-400 whitespace-nowrap">
                        {log.ip_address || '127.0.0.1'}
                      </td>
                      <td className="py-3 px-4 text-gray-300 max-w-xs truncate font-sans">
                        {log.target_id ? (
                          <span className="text-gray-400">
                            [{log.target_type || 'ref'}]: {log.target_id}
                          </span>
                        ) : meta ? (
                          <span className="text-gray-400 truncate">
                            {JSON.stringify(meta).slice(0, 50)}...
                          </span>
                        ) : (
                          '—'
                        )}
                      </td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>

        {/* Pagination Footer */}
        <div className="p-4 bg-gray-950/40 border-t border-gray-800 flex items-center justify-between text-xs text-gray-400 font-sans">
          <span>
            Showing {logs.length} of {total} events
          </span>
          <div className="flex items-center gap-2">
            <button
              onClick={() => setPage((p) => Math.max(1, p - 1))}
              disabled={page <= 1 || loading}
              className="p-1.5 rounded-lg bg-gray-800 hover:bg-gray-700 disabled:opacity-40 disabled:cursor-not-allowed text-white"
            >
              <ChevronLeft size={16} />
            </button>
            <span>
              Page {page} of {totalPages}
            </span>
            <button
              onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
              disabled={page >= totalPages || loading}
              className="p-1.5 rounded-lg bg-gray-800 hover:bg-gray-700 disabled:opacity-40 disabled:cursor-not-allowed text-white"
            >
              <ChevronRight size={16} />
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
