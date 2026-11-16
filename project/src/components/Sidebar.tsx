import {
  LayoutDashboard,
  Search,
  ListChecks,
  Table2,
  Calendar,
  Globe,
  BarChart3,
  Code2,
  Settings,
  Webhook,
  HelpCircle,
  UserCheck,
  History,
  ShieldAlert,
} from 'lucide-react';
import { Logo } from './Logo';
import type { PageId } from '@/App';

const navItems: Array<{ id: PageId; label: string; icon: typeof LayoutDashboard; section: string }> = [
  { id: 'dashboard', label: 'Dashboard', icon: LayoutDashboard, section: 'main' },
  { id: 'create', label: 'New Scraper', icon: Search, section: 'main' },
  { id: 'jobs', label: 'Jobs', icon: ListChecks, section: 'main' },
  { id: 'data', label: 'Data Explorer', icon: Table2, section: 'main' },
  { id: 'activity', label: 'Activity History', icon: History, section: 'main' },
  { id: 'users', label: 'Users', icon: UserCheck, section: 'main' },
  { id: 'admin-audit', label: 'System Audit Logs', icon: ShieldAlert, section: 'main' },
  { id: 'analytics', label: 'Analytics', icon: BarChart3, section: 'tools' },
  { id: 'schedule', label: 'Schedules', icon: Calendar, section: 'tools' },
  { id: 'proxies', label: 'Proxies', icon: Globe, section: 'tools' },
  { id: 'integrations', label: 'Integrations', icon: Webhook, section: 'tools' },
  { id: 'api', label: 'API Access', icon: Code2, section: 'tools' },
  { id: 'settings', label: 'Settings', icon: Settings, section: 'tools' },
];

export function Sidebar({
  currentPage,
  onNavigate,
  open,
  onClose,
  user,
}: {
  currentPage: PageId;
  onNavigate: (page: PageId) => void;
  open: boolean;
  onClose: () => void;
  user?: any;
}) {
  const isAdmin = true;
  // Single-user local mode has nobody to manage, so the Users page is hidden.
  const isLocalMode = user?.authMode === 'local';

  // Both user and admin access their personalized dashboard, scraping, explorer, jobs, and lifetime activity
  const mainItems = navItems.filter((i) => {
    if (i.section !== 'main') return false;
    if (!isAdmin && (i.id === 'users' || i.id === 'admin-audit')) return false; // OWNER ONLY: never visible to normal users
    if (isLocalMode && i.id === 'users') return false;
    return true;
  });

  const toolItems = navItems.filter((i) => {
    if (i.section !== 'tools') return false;
    if (!isAdmin && (i.id === 'proxies' || i.id === 'integrations')) {
      return false; // Sensitive system/proxy configs reserved for admin
    }
    return true;
  });

  return (
    <>
      {open && <div className="fixed inset-0 bg-black/60 z-40 lg:hidden" onClick={onClose} />}
      <aside
        className={`fixed lg:sticky top-0 left-0 z-50 h-screen w-64 bg-gray-950 border-r border-gray-800 flex flex-col transition-transform duration-300 ${
          open ? 'translate-x-0' : '-translate-x-full lg:translate-x-0'
        }`}
      >
        <div className="p-5 border-b border-gray-800">
          <button
            onClick={() => onNavigate('dashboard')}
            className="text-left w-full hover:opacity-90 transition-opacity focus:outline-none cursor-pointer"
            title="Go to Dashboard"
          >
            <Logo />
          </button>
        </div>

        <nav className="flex-1 overflow-y-auto px-3 py-4 space-y-6">
          <div>
            <p className="text-xs font-semibold text-gray-500 uppercase tracking-wider px-3 mb-2">Main</p>
            <div className="space-y-1">
              {mainItems.map((item) => {
                const Icon = item.icon;
                const active = currentPage === item.id;
                return (
                  <button
                    key={item.id}
                    onClick={() => {
                      onNavigate(item.id);
                      onClose();
                    }}
                    className={`w-full flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium transition-all ${
                      active
                        ? 'bg-gradient-to-r from-emerald-500/20 to-cyan-500/10 text-emerald-400 border border-emerald-500/30'
                        : 'text-gray-400 hover:text-white hover:bg-gray-800/50'
                    }`}
                  >
                    <Icon className="w-4.5 h-4.5 flex-shrink-0" size={18} />
                    {item.label}
                  </button>
                );
              })}
            </div>
          </div>

          <div>
            <p className="text-xs font-semibold text-gray-500 uppercase tracking-wider px-3 mb-2">Tools</p>
            <div className="space-y-1">
              {toolItems.map((item) => {
                const Icon = item.icon;
                const active = currentPage === item.id;
                return (
                  <button
                    key={item.id}
                    onClick={() => {
                      onNavigate(item.id);
                      onClose();
                    }}
                    className={`w-full flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium transition-all ${
                      active
                        ? 'bg-gradient-to-r from-emerald-500/20 to-cyan-500/10 text-emerald-400 border border-emerald-500/30'
                        : 'text-gray-400 hover:text-white hover:bg-gray-800/50'
                    }`}
                  >
                    <Icon className="w-4.5 h-4.5 flex-shrink-0" size={18} />
                    {item.label}
                  </button>
                );
              })}
            </div>
          </div>
        </nav>

        <div className="p-4 border-t border-gray-800">
          <div className="bg-gradient-to-br from-emerald-500/10 to-cyan-500/5 border border-emerald-500/20 rounded-xl p-4">
            <div className="flex items-center gap-2 mb-2">
              <div className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse" />
              <span className="text-xs font-semibold text-emerald-400">
                {isAdmin ? 'Master System Plan' : 'Free Trial Active'}
              </span>
            </div>
            <p className="text-xs text-gray-400 mb-3">
              {isAdmin ? 'Enterprise Admin · Unlimited Access' : '10 items one-time free scraping'}
            </p>
            <button
              onClick={() => onNavigate('settings')}
              className="w-full text-xs font-medium text-gray-300 hover:text-white py-2 px-3 rounded-lg bg-gray-800/50 hover:bg-gray-800 transition-colors"
            >
              {isAdmin ? 'System Settings' : 'Manage Plan'}
            </button>
          </div>
          <button
            onClick={() => {
              onNavigate('docs');
              onClose();
            }}
            className="w-full flex items-center gap-2 px-3 py-2.5 mt-3 text-xs text-gray-400 hover:text-emerald-400 hover:bg-gray-800/40 rounded-lg transition-colors"
          >
            <HelpCircle size={16} />
            Help & Documentation
          </button>
        </div>
      </aside>
    </>
  );
}
