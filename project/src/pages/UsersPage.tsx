import { useState, useEffect, useCallback } from 'react';
import { Users, CheckCircle2, AlertTriangle, RefreshCw, UserPlus, Trash2 } from 'lucide-react';
import { api } from '@/api/client';

interface PlatformUser {
  id: string;
  email: string;
  name: string;
  role: string;
  company?: string;
  created_at?: string;
}

const emptyNewUser = { name: '', email: '', password: '', role: 'user', company: '' };

function formatDate(iso?: string) {
  if (!iso) return '—';
  try {
    return new Date(iso).toLocaleString('en-US', {
      month: 'short',
      day: 'numeric',
      year: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    });
  } catch {
    return iso;
  }
}

/** Owner-only page for managing who can sign in to this LeadSweep instance. */
export function UsersPage() {
  const [users, setUsers] = useState<PlatformUser[]>([]);
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState<{ text: string; type: 'success' | 'error' } | null>(null);
  const [showAddModal, setShowAddModal] = useState(false);
  const [newUser, setNewUser] = useState(emptyNewUser);
  const [adding, setAdding] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<PlatformUser | null>(null);
  const [deleting, setDeleting] = useState(false);

  const fetchUsers = useCallback(async () => {
    setLoading(true);
    try {
      setUsers((await api.adminGetUsers()) || []);
    } catch (err: any) {
      setMessage({ text: err.message || 'Failed to load users', type: 'error' });
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchUsers();
  }, [fetchUsers]);

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newUser.email || !newUser.password || !newUser.name) return;
    setAdding(true);
    try {
      await api.adminCreateUser(newUser);
      setMessage({ text: `User ${newUser.email} created. Share the password with them directly.`, type: 'success' });
      setShowAddModal(false);
      setNewUser(emptyNewUser);
      await fetchUsers();
    } catch (err: any) {
      setMessage({ text: err.message || 'Failed to create user', type: 'error' });
    } finally {
      setAdding(false);
    }
  };

  const handleDelete = async () => {
    if (!deleteTarget) return;
    setDeleting(true);
    try {
      await api.adminDeleteUser(deleteTarget.email);
      setMessage({ text: `User ${deleteTarget.email} was removed.`, type: 'success' });
      setDeleteTarget(null);
      await fetchUsers();
    } catch (err: any) {
      setMessage({ text: err.message || 'Failed to remove user', type: 'error' });
    } finally {
      setDeleting(false);
    }
  };

  const inputClass =
    'w-full bg-gray-950 border border-gray-800 rounded-lg px-3 py-2 text-white focus:outline-none focus:border-emerald-500';

  return (
    <div className="min-h-screen bg-gray-950 text-gray-100 p-4 sm:p-6 lg:p-8">
      <div className="max-w-7xl mx-auto space-y-6">
        <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4 border-b border-gray-800/80 pb-6">
          <div>
            <span className="px-2.5 py-0.5 rounded text-[11px] font-bold uppercase tracking-wider bg-emerald-500/10 text-emerald-400 border border-emerald-500/30">
              Owner Only
            </span>
            <h1 className="text-2xl sm:text-3xl font-bold tracking-tight text-white mt-1">Users</h1>
            <p className="text-sm text-gray-400 mt-1">
              Add teammates who can sign in to this LeadSweep instance, or remove their access.
            </p>
          </div>
          <div className="flex items-center gap-3">
            <button
              onClick={() => setShowAddModal(true)}
              className="flex items-center gap-2 px-3.5 py-2 rounded-lg bg-emerald-600 hover:bg-emerald-500 text-sm font-semibold text-white shadow-lg shadow-emerald-950 transition-all cursor-pointer"
            >
              <UserPlus size={15} /> Add User
            </button>
            <button
              onClick={fetchUsers}
              disabled={loading}
              className="flex items-center gap-2 px-3.5 py-2 rounded-lg bg-gray-900 border border-gray-800 text-sm font-medium text-gray-300 hover:text-white hover:bg-gray-800 transition-all cursor-pointer disabled:opacity-50"
            >
              <RefreshCw size={15} className={loading ? 'animate-spin text-emerald-400' : ''} /> Refresh
            </button>
          </div>
        </div>

        {message && (
          <div
            className={`p-4 rounded-xl border flex items-center justify-between ${
              message.type === 'success'
                ? 'bg-emerald-950/30 border-emerald-500/30 text-emerald-300'
                : 'bg-rose-950/30 border-rose-500/30 text-rose-300'
            }`}
          >
            <div className="flex items-center gap-3 text-sm font-medium">
              {message.type === 'success' ? <CheckCircle2 size={18} /> : <AlertTriangle size={18} />}
              <span>{message.text}</span>
            </div>
            <button onClick={() => setMessage(null)} className="text-xs opacity-75 hover:opacity-100 underline ml-4 cursor-pointer">
              Dismiss
            </button>
          </div>
        )}

        {loading && users.length === 0 ? (
          <div className="bg-gray-900/30 border border-gray-800/80 rounded-2xl p-12 text-center space-y-3">
            <RefreshCw size={28} className="mx-auto text-emerald-400 animate-spin" />
            <p className="text-sm text-gray-400">Loading users...</p>
          </div>
        ) : users.length === 0 ? (
          <div className="bg-gray-900/20 border border-gray-800/80 rounded-2xl p-12 text-center space-y-3">
            <Users size={36} className="mx-auto text-gray-600" />
            <h3 className="text-base font-medium text-gray-300">No users yet</h3>
          </div>
        ) : (
          <div className="overflow-hidden rounded-2xl border border-gray-800/80 bg-gray-900/30 shadow-xl">
            <div className="overflow-x-auto">
              <table className="w-full text-left border-collapse text-sm">
                <thead>
                  <tr className="border-b border-gray-800/80 bg-gray-900/80 text-xs font-semibold uppercase text-gray-400 tracking-wider">
                    <th className="py-3.5 px-4">User</th>
                    <th className="py-3.5 px-4">Company</th>
                    <th className="py-3.5 px-4">Role</th>
                    <th className="py-3.5 px-4">Created</th>
                    <th className="py-3.5 px-4 text-right">Actions</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-800/60">
                  {users.map((u) => (
                    <tr key={u.id || u.email} className="hover:bg-gray-800/40 transition-colors">
                      <td className="py-3.5 px-4">
                        <div className="font-semibold text-white">{u.name}</div>
                        <div className="text-xs text-gray-400 font-mono">{u.email}</div>
                      </td>
                      <td className="py-3.5 px-4 text-gray-300">{u.company || '—'}</td>
                      <td className="py-3.5 px-4">
                        <span
                          className={`inline-flex items-center px-2 py-0.5 rounded text-[11px] font-bold uppercase tracking-wider ${
                            u.role === 'owner'
                              ? 'bg-emerald-500/15 text-emerald-400 border border-emerald-500/30'
                              : u.role === 'admin'
                              ? 'bg-cyan-500/15 text-cyan-400 border border-cyan-500/30'
                              : 'bg-gray-800 text-gray-300'
                          }`}
                        >
                          {u.role}
                        </span>
                      </td>
                      <td className="py-3.5 px-4 text-xs text-gray-400">{formatDate(u.created_at)}</td>
                      <td className="py-3.5 px-4 text-right">
                        {u.role === 'owner' ? (
                          <span className="text-xs text-gray-500 italic">Owner</span>
                        ) : (
                          <button
                            onClick={() => setDeleteTarget(u)}
                            className="inline-flex items-center gap-1 px-2.5 py-1 text-xs font-semibold rounded-md bg-rose-500/15 text-rose-400 hover:bg-rose-500/25 border border-rose-500/30 transition-all cursor-pointer"
                          >
                            <Trash2 size={12} /> Remove
                          </button>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </div>

      {showAddModal && (
        <div className="fixed inset-0 z-50 bg-black/85 backdrop-blur-sm flex items-center justify-center p-4">
          <div className="bg-gray-900 border border-gray-800 rounded-2xl w-full max-w-md p-6 space-y-4 shadow-2xl">
            <div className="flex items-center justify-between pb-3 border-b border-gray-800">
              <div className="flex items-center gap-2.5">
                <div className="p-2 rounded-lg bg-emerald-500/15 text-emerald-400">
                  <UserPlus size={18} />
                </div>
                <div>
                  <h3 className="text-base font-bold text-white">Add User</h3>
                  <p className="text-xs text-gray-400">They can sign in right away with this password.</p>
                </div>
              </div>
              <button onClick={() => setShowAddModal(false)} className="text-gray-400 hover:text-white text-sm">
                ✕
              </button>
            </div>

            <form onSubmit={handleCreate} className="space-y-3 text-xs">
              <div>
                <label className="text-gray-400 uppercase font-semibold block mb-1">Full Name</label>
                <input type="text" required placeholder="e.g. Jane Doe" value={newUser.name}
                  onChange={(e) => setNewUser({ ...newUser, name: e.target.value })} className={inputClass} />
              </div>
              <div>
                <label className="text-gray-400 uppercase font-semibold block mb-1">Email Address</label>
                <input type="email" required placeholder="name@company.com" value={newUser.email}
                  onChange={(e) => setNewUser({ ...newUser, email: e.target.value })} className={inputClass} />
              </div>
              <div>
                <label className="text-gray-400 uppercase font-semibold block mb-1">Password</label>
                <input type="password" required minLength={8} placeholder="Min 8 characters" value={newUser.password}
                  onChange={(e) => setNewUser({ ...newUser, password: e.target.value })} className={inputClass} />
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="text-gray-400 uppercase font-semibold block mb-1">Role</label>
                  <select value={newUser.role} onChange={(e) => setNewUser({ ...newUser, role: e.target.value })} className={inputClass}>
                    <option value="user">User</option>
                    <option value="admin">Admin</option>
                  </select>
                </div>
                <div>
                  <label className="text-gray-400 uppercase font-semibold block mb-1">Company</label>
                  <input type="text" placeholder="Optional" value={newUser.company}
                    onChange={(e) => setNewUser({ ...newUser, company: e.target.value })} className={inputClass} />
                </div>
              </div>
              <div className="flex items-center justify-end gap-3 pt-3 border-t border-gray-800">
                <button type="button" onClick={() => setShowAddModal(false)} disabled={adding}
                  className="px-3.5 py-2 rounded-lg font-medium text-gray-400 hover:text-white">
                  Cancel
                </button>
                <button type="submit" disabled={adding}
                  className="px-4 py-2 rounded-lg font-semibold bg-emerald-600 hover:bg-emerald-500 text-white flex items-center gap-2 cursor-pointer">
                  {adding && <RefreshCw size={12} className="animate-spin" />} Create User
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {deleteTarget && (
        <div className="fixed inset-0 z-50 bg-black/85 backdrop-blur-sm flex items-center justify-center p-4">
          <div className="bg-gray-900 border border-gray-800 rounded-2xl w-full max-w-md p-6 space-y-4 shadow-2xl">
            <div className="flex items-center gap-3">
              <div className="p-2.5 rounded-xl bg-rose-500/15 text-rose-400">
                <Trash2 size={24} />
              </div>
              <div>
                <h3 className="text-base font-bold text-white">Remove user?</h3>
                <p className="text-xs text-gray-400 font-mono mt-0.5">{deleteTarget.email}</p>
              </div>
            </div>
            <p className="text-xs text-gray-300 leading-relaxed">
              <span className="font-semibold text-white">{deleteTarget.name}</span> will be deleted and can no longer sign in.
            </p>
            <div className="flex items-center justify-end gap-3 pt-3 border-t border-gray-800">
              <button type="button" onClick={() => setDeleteTarget(null)} disabled={deleting}
                className="px-3.5 py-2 rounded-lg text-xs font-medium text-gray-400 hover:text-white">
                Cancel
              </button>
              <button type="button" onClick={handleDelete} disabled={deleting}
                className="px-4 py-2 rounded-lg text-xs font-semibold bg-rose-600 hover:bg-rose-500 text-white flex items-center gap-2 cursor-pointer">
                {deleting && <RefreshCw size={12} className="animate-spin" />} Remove
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
