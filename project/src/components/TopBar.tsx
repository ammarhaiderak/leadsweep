import { useState, useRef, useEffect } from 'react';
import { Menu, Bell, Search, ChevronRight, LogOut, User, Sparkles, ChevronDown, Sun, Moon } from 'lucide-react';
import type { PageId } from '@/App';
import { api } from '@/api/client';

const pageTitles: Record<PageId, string> = {
  dashboard: 'Dashboard',
  create: 'New Scraper',
  jobs: 'Jobs',
  data: 'Data Explorer',
  analytics: 'Analytics',
  schedule: 'Schedules',
  proxies: 'Proxy Network',
  integrations: 'Integrations',
  api: 'API Access',
  settings: 'Settings',
  docs: 'Documentation',
  users: 'Users',
  'admin-audit': 'Admin Audit Logs',
  activity: 'Activity History',
};

export function TopBar({
  currentPage,
  onMenuClick,
  user,
  onLogout,
  onNavigate,
}: {
  currentPage: PageId;
  onMenuClick: () => void;
  user?: any;
  onLogout?: () => void;
  onNavigate?: (page: PageId) => void;
}) {
  const displayName = user?.name || (user?.email ? user.email.split('@')[0] : 'Guest');
  const displayPlan = user?.plan || (user?.role === 'owner' ? 'System Owner' : 'Standard Plan');
  const displayRole = user?.role || 'user';
  const initial = displayName.charAt(0).toUpperCase();
  const [notificationsOpen, setNotificationsOpen] = useState(false);
  const [notificationsList, setNotificationsList] = useState<any[]>([]);
  const [userMenuOpen, setUserMenuOpen] = useState(false);
  const userMenuRef = useRef<HTMLDivElement>(null);
  const [theme, setTheme] = useState<'dark' | 'light'>(() => {
    return (localStorage.getItem('leadsweep_theme') as 'dark' | 'light') || 'dark';
  });

  const toggleTheme = () => {
    const nextTheme = theme === 'dark' ? 'light' : 'dark';
    setTheme(nextTheme);
    localStorage.setItem('leadsweep_theme', nextTheme);
    if (nextTheme === 'light') {
      document.documentElement.classList.add('theme-light');
    } else {
      document.documentElement.classList.remove('theme-light');
    }
  };

  useEffect(() => {
    if (theme === 'light') {
      document.documentElement.classList.add('theme-light');
    } else {
      document.documentElement.classList.remove('theme-light');
    }
  }, [theme]);

  useEffect(() => {
    let mounted = true;
    const fetchNotifs = async () => {
      try {
        const notifs = await api.getNotifications();
        if (mounted && notifs && notifs.length > 0) {
          setNotificationsList(notifs);
        }
      } catch {}
    };
    fetchNotifs();
    const interval = setInterval(fetchNotifs, 10000);
    return () => {
      mounted = false;
      clearInterval(interval);
    };
  }, []);

  useEffect(() => {
    function handleClickOutside(event: MouseEvent) {
      if (userMenuRef.current && !userMenuRef.current.contains(event.target as Node)) {
        setUserMenuOpen(false);
      }
    }
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  return (
    <header className="sticky top-0 z-30 bg-gray-950/80 backdrop-blur-xl border-b border-gray-800">
      <div className="flex items-center justify-between px-4 lg:px-6 h-16">
        <div className="flex items-center gap-3">
          <button
            onClick={onMenuClick}
            className="lg:hidden p-2 -ml-2 text-gray-400 hover:text-white transition-colors"
          >
            <Menu size={20} />
          </button>
          <div className="flex items-center gap-2 text-sm">
            <button
              onClick={() => onNavigate && onNavigate('dashboard')}
              className="text-gray-400 hover:text-emerald-400 transition-colors font-medium focus:outline-none"
              title="Go to Dashboard"
            >
              LeadSweep
            </button>
            <ChevronRight size={14} className="text-gray-600" />
            <span className="text-white font-medium">{pageTitles[currentPage] || 'LeadSweep'}</span>
          </div>
        </div>

        <div className="flex items-center gap-3">
          <div className="hidden md:flex items-center gap-2 bg-gray-900 border border-gray-800 rounded-lg px-3 py-2 w-64">
            <Search size={16} className="text-gray-500" />
            <input
              type="text"
              placeholder="Search jobs, data, platforms..."
              className="bg-transparent text-sm text-white placeholder-gray-500 outline-none flex-1"
            />
            <kbd className="text-xs text-gray-600 bg-gray-800 px-1.5 py-0.5 rounded">K</kbd>
          </div>

          {/* Theme Toggle Button (Light/Dark Mode) */}
          <button
            onClick={toggleTheme}
            className="p-2 text-gray-400 hover:text-white transition-colors rounded-lg hover:bg-gray-800 flex items-center gap-1.5 text-xs font-medium"
            title={`Switch to ${theme === 'dark' ? 'Light' : 'Dark'} Mode`}
          >
            {theme === 'dark' ? (
              <Sun size={18} className="text-amber-400 hover:rotate-45 transition-transform" />
            ) : (
              <Moon size={18} className="text-sky-400 hover:-rotate-12 transition-transform" />
            )}
          </button>

          <div className="relative">
            <button
              onClick={() => setNotificationsOpen(!notificationsOpen)}
              className="relative p-2 text-gray-400 hover:text-white transition-colors rounded-lg hover:bg-gray-800"
              title="Notifications"
            >
              <Bell size={18} />
              <span className="absolute top-1.5 right-1.5 w-2 h-2 bg-emerald-400 rounded-full animate-pulse" />
            </button>

            {notificationsOpen && (
              <div className="absolute right-0 mt-2 w-80 sm:w-96 bg-gray-900 border border-gray-800 rounded-2xl shadow-2xl p-4 z-50">
                <div className="flex items-center justify-between pb-3 border-b border-gray-800">
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-bold text-white">Notifications</span>
                    <span className="px-2 py-0.5 text-xs font-semibold bg-emerald-500/20 text-emerald-400 rounded-full border border-emerald-500/30">Live</span>
                  </div>
                  <button
                    onClick={() => setNotificationsOpen(false)}
                    className="text-xs text-gray-400 hover:text-gray-200"
                  >
                    Close
                  </button>
                </div>

                <div className="mt-3 space-y-2.5 max-h-72 overflow-y-auto">
                  {notificationsList.length > 0 ? (
                    notificationsList.map((n) => (
                      <div key={n.id} className="p-3 bg-gray-950/60 border border-gray-800 hover:border-emerald-500/30 transition-colors rounded-xl">
                        <div className="flex items-center justify-between">
                          <span className={`text-xs font-semibold ${n.severity === 'WARN' ? 'text-amber-400' : n.severity === 'ERROR' ? 'text-rose-400' : 'text-emerald-400'}`}>
                            {n.title}
                          </span>
                          <span className="text-[10px] text-gray-500">
                            {(() => {
                              try {
                                const d = new Date(n.createdAt);
                                return isNaN(d.getTime()) ? 'Just now' : d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
                              } catch {
                                return 'Recent';
                              }
                            })()}
                          </span>
                        </div>
                        <p className="text-xs text-gray-300 mt-1 line-clamp-2">
                          {n.message}
                        </p>
                      </div>
                    ))
                  ) : (
                    <>
                      <div className="p-3 bg-gray-950/60 border border-emerald-500/20 rounded-xl">
                        <div className="flex items-center justify-between">
                          <span className="text-xs font-semibold text-emerald-400">Email Notifications</span>
                          <span className="text-[10px] text-gray-500">Just now</span>
                        </div>
                        <p className="text-xs text-gray-300 mt-1">
                          Outgoing email uses the SMTP server configured in .env.
                        </p>
                      </div>

                      <div className="p-3 bg-gray-950/60 border border-gray-800 rounded-xl">
                        <div className="flex items-center justify-between">
                          <span className="text-xs font-semibold text-cyan-400">Database Synced</span>
                          <span className="text-[10px] text-gray-500">2m ago</span>
                        </div>
                        <p className="text-xs text-gray-300 mt-1">
                          Audit logging is active.
                        </p>
                      </div>
                    </>
                  )}
                </div>

                <div className="pt-3 mt-3 border-t border-gray-800 text-center">
                  <button
                    onClick={() => {
                      setNotificationsOpen(false);
                      onNavigate && onNavigate('jobs');
                    }}
                    className="text-xs font-medium text-emerald-400 hover:text-emerald-300 transition-colors"
                  >
                    View All Scraper Jobs →
                  </button>
                </div>
              </div>
            )}
          </div>

          {/* User Account / Profile */}
          {user ? (
            <div className="relative" ref={userMenuRef}>
              <button
                onClick={() => setUserMenuOpen(!userMenuOpen)}
                className="flex items-center gap-2.5 pl-3 border-l border-gray-800 hover:opacity-90 transition-opacity text-left cursor-pointer"
                title="Account Menu"
              >
                <div className="w-8 h-8 rounded-full bg-gradient-to-br from-emerald-400 to-cyan-500 flex items-center justify-center text-white text-sm font-bold shadow-md shadow-emerald-500/20">
                  {initial}
                </div>
                <div className="hidden sm:block">
                  <p className="text-sm text-white font-medium leading-none">{displayName}</p>
                  <p className="text-xs text-emerald-400 leading-none mt-1 font-medium">{displayPlan}</p>
                </div>
                <ChevronDown size={14} className="text-gray-400 hidden sm:block" />
              </button>

              {userMenuOpen && (
                <div className="absolute right-0 mt-2 w-64 bg-gray-900 border border-gray-800 rounded-2xl shadow-2xl p-2 z-50 animate-in fade-in zoom-in-95 duration-150">
                  <div className="px-3 py-2.5 border-b border-gray-800">
                    <div className="flex items-center justify-between">
                      <span className="text-xs text-gray-400">{onLogout ? 'Signed in as' : 'Running locally as'}</span>
                      <span className="text-[10px] px-2 py-0.5 rounded-full font-semibold bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 uppercase">
                        {displayRole}
                      </span>
                    </div>
                    <p className="text-sm font-semibold text-white mt-1 truncate">{user?.email || displayName}</p>
                  </div>

                  <div className="py-1 space-y-1">
                    <button
                      onClick={() => {
                        setUserMenuOpen(false);
                        onNavigate && onNavigate('docs');
                      }}
                      className="w-full flex items-center gap-2.5 px-3 py-2 text-xs font-medium text-gray-300 hover:text-white hover:bg-gray-800/60 rounded-xl transition-colors"
                    >
                      <Sparkles size={15} className="text-cyan-400" />
                      Documentation & Guide
                    </button>
                    <button
                      onClick={() => {
                        setUserMenuOpen(false);
                        onNavigate && onNavigate('settings');
                      }}
                      className="w-full flex items-center gap-2.5 px-3 py-2 text-xs font-medium text-gray-300 hover:text-white hover:bg-gray-800/60 rounded-xl transition-colors"
                    >
                      <User size={15} className="text-emerald-400" />
                      Account Settings
                    </button>
                  </div>

                  {onLogout && (
                    <div className="pt-1 border-t border-gray-800">
                      <button
                        onClick={() => {
                          setUserMenuOpen(false);
                          onLogout();
                        }}
                        className="w-full flex items-center gap-2.5 px-3 py-2 text-xs font-semibold text-red-400 hover:text-red-300 hover:bg-red-500/10 rounded-xl transition-colors"
                      >
                        <LogOut size={15} />
                        Log Out
                      </button>
                    </div>
                  )}
                </div>
              )}
            </div>
          ) : null}
        </div>
      </div>
    </header>
  );
}
