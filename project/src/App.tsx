import { useState, useEffect } from 'react';
import { Sidebar } from '@/components/Sidebar';
import { TopBar } from '@/components/TopBar';
import { LoginModal } from '@/components/LoginModal';
import { DashboardPage } from '@/pages/DashboardPage';
import { CreateScraperPage } from '@/pages/CreateScraperPage';
import { JobsPage } from '@/pages/JobsPage';
import { DataExplorerPage } from '@/pages/DataExplorerPage';
import { AnalyticsPage } from '@/pages/AnalyticsPage';
import { SchedulePage } from '@/pages/SchedulePage';
import { ProxiesPage } from '@/pages/ProxiesPage';
import { IntegrationsPage } from '@/pages/IntegrationsPage';
import { ApiPage } from '@/pages/ApiPage';
import { SettingsPage } from '@/pages/SettingsPage';
import { DocsPage } from '@/pages/DocsPage';
import { UsersPage } from '@/pages/UsersPage';
import { ActivityHistoryPage } from '@/pages/ActivityHistoryPage';
import { AdminAuditLogsPage } from '@/pages/AdminAuditLogsPage';
import { api } from '@/api/client';

export type PageId =
  | 'dashboard'
  | 'create'
  | 'jobs'
  | 'data'
  | 'analytics'
  | 'schedule'
  | 'proxies'
  | 'integrations'
  | 'api'
  | 'settings'
  | 'docs'
  | 'users'
  | 'admin-audit'
  | 'activity';

export type Platform =
  | 'twitter'
  | 'linkedin'
  | 'upwork'
  | 'fiverr'
  | 'instagram'
  | 'facebook'
  | 'reddit'
  | 'bluesky';

export type ScraperType =
  | 'profile'
  | 'search'
  | 'hashtag'
  | 'timeline'
  | 'replies'
  | 'followers'
  | 'media'
  | 'lists';

type AuthMode = 'loading' | 'local' | 'login';

const PAGE_IDS: PageId[] = [
  'dashboard', 'create', 'jobs', 'data', 'analytics', 'schedule', 'proxies',
  'integrations', 'api', 'settings', 'docs', 'users', 'admin-audit', 'activity',
];

function initialPage(): PageId {
  try {
    const saved = localStorage.getItem('leadsweep_active_page') as PageId | null;
    return saved && PAGE_IDS.includes(saved) ? saved : 'dashboard';
  } catch {
    return 'dashboard';
  }
}

function App() {
  // The server decides: 'local' (default, no sign-in) or 'login' (LEADSWEEP_REQUIRE_LOGIN=true).
  const [authMode, setAuthMode] = useState<AuthMode>('loading');
  const [currentUser, setCurrentUser] = useState<any>(null);
  const [page, setPage] = useState<PageId>(initialPage);

  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [loginModalMode, setLoginModalMode] = useState<'signin' | 'reset'>('signin');
  const [resetTokenParam, setResetTokenParam] = useState('');
  const [resetEmailParam, setResetEmailParam] = useState('');

  useEffect(() => {
    // Password reset links (?reset_token=...&email=...) only matter in login mode.
    const params = new URLSearchParams(window.location.search);
    const token = params.get('reset_token');
    const email = params.get('email');
    if (token) {
      setResetTokenParam(token);
      if (email) setResetEmailParam(email);
      setLoginModalMode('reset');
    }
  }, []);

  useEffect(() => {
    let token: string | null = null;
    try {
      token = localStorage.getItem('leadsweep_auth_token');
    } catch {
      token = null;
    }
    api.getMe(token || undefined)
      .then((user) => {
        setCurrentUser(user);
        setAuthMode(user?.authMode === 'login' ? 'login' : 'local');
        try {
          localStorage.setItem('leadsweep_auth_user', JSON.stringify(user));
        } catch {
          /* storage unavailable: fine, state lives in memory */
        }
      })
      .catch(() => {
        // 401: login is required and there is no valid session yet.
        setCurrentUser(null);
        setAuthMode('login');
      });
  }, []);

  const navigate = (next: PageId) => {
    setPage(next);
    try {
      localStorage.setItem('leadsweep_active_page', next);
    } catch {
      /* ignore */
    }
    window.scrollTo(0, 0);
  };

  const handleLoginSuccess = (user: any) => {
    setCurrentUser(user);
    setAuthMode('login');
    navigate('dashboard');
  };

  const handleLogout = () => {
    try {
      localStorage.removeItem('leadsweep_auth_token');
      localStorage.removeItem('leadsweep_auth_user');
      localStorage.removeItem('leadsweep_active_page');
    } catch {
      /* ignore */
    }
    setCurrentUser(null);
    setPage('dashboard');
  };

  if (authMode === 'loading') {
    return (
      <div className="min-h-screen bg-gray-950 flex items-center justify-center">
        <div className="w-8 h-8 rounded-full border-2 border-emerald-500/30 border-t-emerald-400 animate-spin" />
      </div>
    );
  }

  if (!currentUser) {
    // Login mode without a session: the sign-in dialog is the only thing to show.
    return (
      <div className="min-h-screen bg-gray-950">
        <LoginModal
          isOpen
          initialMode={loginModalMode}
          resetToken={resetTokenParam}
          resetEmail={resetEmailParam}
          onClose={() => setLoginModalMode('signin')}
          onSuccess={handleLoginSuccess}
        />
      </div>
    );
  }

  const isOwner = currentUser.role === 'admin' || currentUser.role === 'owner';

  return (
    <div className="min-h-screen bg-gray-950 flex">
      <Sidebar
        currentPage={page}
        onNavigate={navigate}
        open={sidebarOpen}
        onClose={() => setSidebarOpen(false)}
        user={currentUser}
      />
      <div className="flex-1 min-w-0 flex flex-col">
        <TopBar
          currentPage={page}
          onMenuClick={() => setSidebarOpen(true)}
          user={currentUser}
          onLogout={authMode === 'login' ? handleLogout : undefined}
          onNavigate={navigate}
        />
        <main className="flex-1">
          {page === 'dashboard' && <DashboardPage onNavigate={navigate} user={currentUser} />}
          {page === 'create' && <CreateScraperPage onNavigate={navigate} user={currentUser} />}
          {page === 'jobs' && <JobsPage onNavigate={navigate} user={currentUser} />}
          {page === 'data' && <DataExplorerPage user={currentUser} />}
          {page === 'analytics' && <AnalyticsPage user={currentUser} />}
          {page === 'activity' && <ActivityHistoryPage user={currentUser} />}
          {page === 'schedule' && <SchedulePage onNavigate={navigate} user={currentUser} />}
          {page === 'proxies' && <ProxiesPage />}
          {page === 'integrations' && <IntegrationsPage />}
          {page === 'api' && <ApiPage />}
          {page === 'settings' && <SettingsPage user={currentUser} />}
          {page === 'docs' && <DocsPage onNavigate={navigate} user={currentUser} />}
          {page === 'users' && (
            isOwner ? (
              <UsersPage />
            ) : (
              <div className="p-8 text-center text-gray-400">
                <p className="text-lg font-semibold text-rose-400 mb-2">Restricted Access</p>
                <p className="text-sm">Owner privileges are required to manage users.</p>
              </div>
            )
          )}
          {page === 'admin-audit' && (
            isOwner ? (
              <AdminAuditLogsPage />
            ) : (
              <div className="p-8 text-center text-gray-400">
                <p className="text-lg font-semibold text-rose-400 mb-2">Restricted Access</p>
                <p className="text-sm">Administrator privileges are required to inspect system audit logs.</p>
              </div>
            )
          )}
        </main>
      </div>
    </div>
  );
}

export default App;
