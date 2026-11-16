import { useState, useEffect } from 'react';
import {
  User, Bell, Shield, CreditCard, Globe, Trash2, Check,
  Zap, Database, HardDrive, Download, RefreshCw,
} from 'lucide-react';
import { api, type OverviewStats } from '@/api/client';
import { UpgradeSubscriptionModal } from '@/components/UpgradeSubscriptionModal';

export function SettingsPage({ user }: { user?: any }) {
  const [isUpgradeModalOpen, setIsUpgradeModalOpen] = useState(false);
  const [notifications, setNotifications] = useState({
    jobComplete: true,
    jobFailed: true,
    weeklyReport: true,
    productUpdates: false,
  });
  const [activeTab, setActiveTab] = useState<'profile' | 'notifications' | 'billing' | 'security'>('profile');
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
  const [loadingStats, setLoadingStats] = useState(false);
  const [saving, setSaving] = useState(false);
  const [saveMessage, setSaveMessage] = useState<{ text: string; type: 'success' | 'error' } | null>(null);

  // User profile values dynamically populated from authenticated user
  const email = user?.email || 'user@example.com';
  const name = user?.name || email.split('@')[0];
  const role = user?.role === 'owner' ? 'Owner' : user?.role === 'admin' ? 'Administrator' : 'Standard Access';
  const plan = user?.plan || 'Free Trial (10 items)';
  const company = user?.company || 'Workspace';

  const [formData, setFormData] = useState({
    name,
    email,
    company,
    role,
  });

  useEffect(() => {
    setFormData({
      name: user?.name || (user?.email ? user.email.split('@')[0] : 'User'),
      email: user?.email || '',
      company: user?.company || 'Personal Workspace',
      role: user?.role === 'owner' ? 'Owner' : user?.role === 'admin' ? 'Administrator' : 'Standard User',
    });

    if (user?.email) {
      setLoadingStats(true);
      api.getOverviewStats(user.email)
        .then((res) => setStatsData(res))
        .catch(() => {})
        .finally(() => setLoadingStats(false));
    }
  }, [user]);

  const tabs = [
    { id: 'profile' as const, label: 'Profile', icon: User },
    { id: 'notifications' as const, label: 'Notifications', icon: Bell },
    { id: 'billing' as const, label: 'Billing & Usage', icon: CreditCard },
    { id: 'security' as const, label: 'Security', icon: Shield },
  ];

  // Check if admin
  const isAdmin = Boolean(user && (user.role === 'owner' || user.role === 'admin'));

  // One-time 10 items limit for free scraping (for regular users)
  const freeItemsLimit = 10;
  const itemsScrapedCount = statsData.itemsScraped;
  const itemsPercent = isAdmin ? 100 : Math.min(100, Math.round((itemsScrapedCount / freeItemsLimit) * 100));

  return (
    <div className="p-4 lg:p-6">
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-white">Settings</h1>
        <p className="text-sm text-gray-400 mt-1">Manage your account, billing, and preferences</p>
      </div>

      <div className="flex flex-col lg:flex-row gap-6">
        {/* Sidebar tabs */}
        <div className="lg:w-56 flex-shrink-0">
          <div className="flex lg:flex-col gap-1 overflow-x-auto">
            {tabs.map((tab) => {
              const Icon = tab.icon;
              return (
                <button
                  key={tab.id}
                  onClick={() => setActiveTab(tab.id)}
                  className={`flex items-center gap-3 px-4 py-2.5 rounded-xl text-sm font-medium transition-all whitespace-nowrap ${
                    activeTab === tab.id
                      ? 'bg-gray-800 text-white border border-gray-700'
                      : 'text-gray-400 hover:text-white hover:bg-gray-800/50'
                  }`}
                >
                  <Icon size={16} /> {tab.label}
                </button>
              );
            })}
          </div>
        </div>

        {/* Content */}
        <div className="flex-1 max-w-3xl">
          {activeTab === 'profile' && (
            <div className="space-y-6">
              <div className="bg-gray-900 border border-gray-800 rounded-2xl p-6">
                <h2 className="text-base font-bold text-white mb-5">Profile Information</h2>
                <div className="flex items-center gap-4 mb-6">
                  <div className="w-16 h-16 rounded-full bg-gradient-to-br from-emerald-400 to-cyan-500 flex items-center justify-center text-white text-2xl font-bold uppercase shadow-inner">
                    {formData.name[0] || formData.email[0] || 'U'}
                  </div>
                  <div>
                    <p className="text-sm font-semibold text-white">{formData.name}</p>
                    <span className="text-xs text-emerald-400 bg-emerald-500/10 px-2.5 py-0.5 rounded-full border border-emerald-500/30">
                      {formData.role}
                    </span>
                  </div>
                </div>
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                  <div>
                    <label className="text-xs font-medium text-gray-500 mb-1.5 block">Full Name</label>
                    <input
                      type="text"
                      value={formData.name}
                      onChange={(e) => setFormData({ ...formData, name: e.target.value })}
                      className="w-full bg-gray-950 border border-gray-800 rounded-xl py-2.5 px-3.5 text-sm text-white outline-none focus:border-emerald-500/50 transition-colors"
                    />
                  </div>
                  <div>
                    <label className="text-xs font-medium text-gray-500 mb-1.5 block">Email</label>
                    <input
                      type="email"
                      value={formData.email}
                      disabled
                      className="w-full bg-gray-950/60 border border-gray-800/80 rounded-xl py-2.5 px-3.5 text-sm text-gray-400 cursor-not-allowed"
                    />
                  </div>
                  <div>
                    <label className="text-xs font-medium text-gray-500 mb-1.5 block">Company / Workspace</label>
                    <input
                      type="text"
                      value={formData.company}
                      onChange={(e) => setFormData({ ...formData, company: e.target.value })}
                      className="w-full bg-gray-950 border border-gray-800 rounded-xl py-2.5 px-3.5 text-sm text-white outline-none focus:border-emerald-500/50 transition-colors"
                    />
                  </div>
                  <div>
                    <label className="text-xs font-medium text-gray-500 mb-1.5 block">Account Role</label>
                    <input
                      type="text"
                      value={formData.role}
                      disabled
                      className="w-full bg-gray-950/60 border border-gray-800/80 rounded-xl py-2.5 px-3.5 text-sm text-gray-400 cursor-not-allowed"
                    />
                  </div>
                </div>
                {saveMessage && (
                  <div className={`mt-4 p-3 rounded-xl text-xs font-medium border ${saveMessage.type === 'success' ? 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20' : 'bg-rose-500/10 text-rose-400 border-rose-500/20'}`}>
                    {saveMessage.text}
                  </div>
                )}
                <button
                  onClick={async () => {
                    setSaving(true);
                    setSaveMessage(null);
                    try {
                      const res = await api.updateUserProfile({
                        name: formData.name,
                        company: formData.company,
                        email: formData.email,
                      });
                      // Update local storage
                      const stored = localStorage.getItem('leadsweep_auth_user');
                      if (stored) {
                        try {
                          const u = JSON.parse(stored);
                          u.name = formData.name;
                          u.company = formData.company;
                          localStorage.setItem('leadsweep_auth_user', JSON.stringify(u));
                        } catch {}
                      }
                      setSaveMessage({ text: 'Profile changes saved successfully!', type: 'success' });
                    } catch (err: any) {
                      setSaveMessage({ text: err.message || 'Failed to save changes.', type: 'error' });
                    } finally {
                      setSaving(false);
                    }
                  }}
                  disabled={saving}
                  className="mt-5 bg-gradient-to-r from-emerald-500 to-cyan-500 hover:from-emerald-400 hover:to-cyan-400 text-white px-5 py-2.5 rounded-xl font-semibold text-sm transition-all shadow-lg shadow-emerald-500/20 disabled:opacity-50"
                >
                  {saving ? 'Saving Changes...' : 'Save Changes'}
                </button>
              </div>
            </div>
          )}

          {activeTab === 'notifications' && (
            <div className="bg-gray-900 border border-gray-800 rounded-2xl p-6">
              <h2 className="text-base font-bold text-white mb-5">Notification Preferences</h2>
              <div className="space-y-3">
                {[
                  { key: 'jobComplete' as const, label: 'Job Completed', desc: 'Get notified when a scraping job finishes' },
                  { key: 'jobFailed' as const, label: 'Job Failed', desc: 'Get alerted when a job encounters an error' },
                  { key: 'weeklyReport' as const, label: 'Weekly Report', desc: 'Summary of your scraping activity every Monday' },
                  { key: 'productUpdates' as const, label: 'Product Updates', desc: 'New features and platform announcements' },
                ].map((item) => (
                  <label key={item.key} className="flex items-center justify-between p-4 rounded-xl bg-gray-950/50 border border-gray-800 cursor-pointer hover:border-gray-700 transition-colors">
                    <div>
                      <p className="text-sm font-medium text-white">{item.label}</p>
                      <p className="text-xs text-gray-500 mt-0.5">{item.desc}</p>
                    </div>
                    <button
                      onClick={() => setNotifications({ ...notifications, [item.key]: !notifications[item.key] })}
                      className={`relative w-11 h-6 rounded-full transition-colors flex-shrink-0 ${notifications[item.key] ? 'bg-emerald-500' : 'bg-gray-700'}`}
                    >
                      <div className="absolute top-0.5 w-5 h-5 rounded-full bg-white transition-transform" style={{ transform: notifications[item.key] ? 'translateX(22px)' : 'translateX(2px)' }} />
                    </button>
                  </label>
                ))}
              </div>
            </div>
          )}

          {activeTab === 'billing' && (
            <div className="space-y-6">
              {/* Current plan */}
              <div className="bg-gradient-to-br from-emerald-500/10 to-cyan-500/5 border border-emerald-500/20 rounded-2xl p-6">
                <div className="flex items-start justify-between mb-4">
                  <div>
                    <h2 className="text-base font-bold text-white">
                      {isAdmin ? 'Current Plan: Enterprise Master System Tier' : 'Current Plan: Free Scraping Tier'}
                    </h2>
                    <p className="text-sm text-gray-400 mt-1">
                      {isAdmin
                        ? 'Unlimited global scraping, unlimited compute units & unlimited storage · Admin Superuser privileges'
                        : 'One-time 10 scraped items for free evaluation · No credit card required'}
                    </p>
                  </div>
                  <span className="flex items-center gap-1 text-xs text-emerald-400 font-medium bg-emerald-500/10 px-2.5 py-1 rounded-full border border-emerald-500/30">
                    <Check size={14} /> Active
                  </span>
                </div>
                {isAdmin ? (
                  <div className="flex items-center gap-3">
                    <span className="px-3.5 py-1.5 rounded-xl bg-emerald-500/20 border border-emerald-500/30 text-emerald-300 font-mono text-xs font-semibold">
                      ∞ Unlimited Credits
                    </span>
                    <span className="px-3.5 py-1.5 rounded-xl bg-cyan-500/20 border border-cyan-500/30 text-cyan-300 font-mono text-xs font-semibold">
                      Zero Throttling
                    </span>
                  </div>
                ) : (
                  <button
                    onClick={() => setIsUpgradeModalOpen(true)}
                    className="bg-gradient-to-r from-emerald-500 to-cyan-500 hover:from-emerald-400 hover:to-cyan-400 text-white px-5 py-2.5 rounded-xl font-semibold text-sm transition-all shadow-lg shadow-emerald-500/20 cursor-pointer"
                  >
                    Upgrade to Pro
                  </button>
                )}
              </div>

              {/* Usage */}
              <div className="bg-gray-900 border border-gray-800 rounded-2xl p-6">
                <div className="flex items-center justify-between mb-5">
                  <h2 className="text-base font-bold text-white">Usage & Limits</h2>
                  <span className="text-xs text-gray-500">
                    {isAdmin ? 'Global Platform Telemetry' : 'Live Workspace Telemetry'}
                  </span>
                </div>
                <div className="space-y-5">
                  <div>
                    <div className="flex items-center justify-between mb-2">
                      <div className="flex items-center gap-2">
                        <Database size={16} className="text-emerald-400" />
                        <span className="text-sm text-white">
                          {isAdmin ? 'Items Scraped (Master Dataset)' : 'Items Scraped (Free One-Time Trial)'}
                        </span>
                      </div>
                      <span className="text-xs text-gray-400">
                        {isAdmin ? (
                          <>
                            <span className="text-white font-medium">{itemsScrapedCount}</span> / <span className="text-emerald-400 font-semibold">Unlimited (∞)</span>
                          </>
                        ) : (
                          <>
                            <span className="text-white font-medium">{itemsScrapedCount}</span> / {freeItemsLimit} items
                          </>
                        )}
                      </span>
                    </div>
                    <div className="h-2.5 bg-gray-800 rounded-full overflow-hidden p-0.5 border border-gray-700/50">
                      <div
                        className="h-full rounded-full bg-gradient-to-r from-emerald-500 to-cyan-400 transition-all duration-300"
                        style={{ width: `${isAdmin ? 100 : itemsPercent}%` }}
                      />
                    </div>
                  </div>

                  <div>
                    <div className="flex items-center justify-between mb-2">
                      <div className="flex items-center gap-2">
                        <Zap size={16} className="text-cyan-400" />
                        <span className="text-sm text-white">Compute Units (CU)</span>
                      </div>
                      <span className="text-xs text-gray-400">
                        {isAdmin ? (
                          <>
                            <span className="text-white font-medium">{statsData.computeUsed} CU used</span> / <span className="text-cyan-400 font-semibold">Unlimited (∞)</span>
                          </>
                        ) : (
                          <>
                            <span className="text-white font-medium">{statsData.computeUsed}</span> / {freeItemsLimit} CU
                          </>
                        )}
                      </span>
                    </div>
                    <div className="h-2 bg-gray-800 rounded-full overflow-hidden">
                      <div
                        className="h-full rounded-full bg-gradient-to-r from-cyan-500 to-sky-400"
                        style={{ width: `${isAdmin ? 100 : Math.min(100, (statsData.computeUsed / freeItemsLimit) * 100)}%` }}
                      />
                    </div>
                  </div>

                  <div>
                    <div className="flex items-center justify-between mb-2">
                      <div className="flex items-center gap-2">
                        <HardDrive size={16} className="text-sky-400" />
                        <span className="text-sm text-white">Storage Capacity</span>
                      </div>
                      <span className="text-xs text-gray-400">
                        {isAdmin ? (
                          <>
                            <span className="text-white font-medium">{statsData.storageUsed} MB used</span> / <span className="text-sky-400 font-semibold">Unlimited (∞)</span>
                          </>
                        ) : (
                          <>
                            <span className="text-white font-medium">{statsData.storageUsed}</span> / {freeItemsLimit} MB
                          </>
                        )}
                      </span>
                    </div>
                    <div className="h-2 bg-gray-800 rounded-full overflow-hidden">
                      <div
                        className="h-full rounded-full bg-gradient-to-r from-sky-500 to-emerald-400"
                        style={{ width: `${isAdmin ? 100 : Math.min(100, (statsData.storageUsed / freeItemsLimit) * 100)}%` }}
                      />
                    </div>
                  </div>
                </div>
              </div>

              {/* Export data */}
              <div className="bg-gray-900 border border-gray-800 rounded-2xl p-6">
                <h2 className="text-base font-bold text-white mb-2">Data Export</h2>
                <p className="text-sm text-gray-400 mb-4">Download all your scraped data and account information.</p>
                <button
                  onClick={() => window.open(api.getExportUrl('csv'), '_blank')}
                  className="flex items-center gap-2 bg-gray-800 hover:bg-gray-700 text-white px-4 py-2.5 rounded-xl font-medium text-sm transition-colors"
                >
                  <Download size={16} /> Export All Data
                </button>
              </div>
            </div>
          )}

          {activeTab === 'security' && (
            <div className="space-y-6">
              <div className="bg-gray-900 border border-gray-800 rounded-2xl p-6">
                <h2 className="text-base font-bold text-white mb-5">Change Password</h2>
                <div className="space-y-4">
                  {['Current Password', 'New Password', 'Confirm New Password'].map((label) => (
                    <div key={label}>
                      <label className="text-xs font-medium text-gray-500 mb-1.5 block">{label}</label>
                      <input
                        type="password"
                        placeholder="••••••••"
                        className="w-full bg-gray-950 border border-gray-800 rounded-xl py-2.5 px-3.5 text-sm text-white placeholder-gray-600 outline-none focus:border-emerald-500/50 transition-colors"
                      />
                    </div>
                  ))}
                  <button className="bg-gradient-to-r from-emerald-500 to-cyan-500 hover:from-emerald-400 hover:to-cyan-400 text-white px-5 py-2.5 rounded-xl font-semibold text-sm transition-all shadow-lg shadow-emerald-500/20">
                    Update Password
                  </button>
                </div>
              </div>

              {/* Zero-Account Integration Security Guarantee */}
              <div className="bg-gray-900 border border-gray-800 rounded-2xl p-6">
                <div className="flex items-start justify-between mb-4">
                  <div>
                    <h2 className="text-base font-bold text-white flex items-center gap-2">
                      <Shield className="text-emerald-400" size={18} /> Zero-Account Integration Guarantee
                    </h2>
                    <p className="text-xs text-gray-400 mt-1">
                      Full platform privacy and autonomous scraping protection.
                    </p>
                  </div>
                  <span className="px-2.5 py-1 text-xs font-semibold rounded-full border bg-emerald-500/10 text-emerald-400 border-emerald-500/20">
                    Enforced & Protected
                  </span>
                </div>

                <div className="bg-gray-950/60 border border-gray-800/80 rounded-xl p-4 space-y-2 text-xs text-gray-300">
                  <div className="flex items-center gap-2 text-emerald-400 font-medium">
                    <Check size={15} /> 100% Zero Personal Account Linking
                  </div>
                  <p className="text-gray-400 leading-relaxed">
                    To maximize security and protect your identity, this scraper operates completely autonomously without requiring login or session integration with your personal X, Telegram, or LinkedIn accounts. No accounts can be banned or compromised.
                  </p>
                </div>
              </div>

              <div className="bg-gray-900 border border-gray-800 rounded-2xl p-6">
                <div className="flex items-center gap-2 mb-4">
                  <Globe size={16} className="text-gray-400" />
                  <h3 className="text-sm font-semibold text-white">Active Sessions</h3>
                </div>
                <div className="flex items-center justify-between p-3.5 rounded-xl bg-gray-950/50 border border-gray-800">
                  <div>
                    <p className="text-xs font-medium text-white">Current Web Browser</p>
                    <p className="text-[11px] text-gray-500">Active session · Verified IP</p>
                  </div>
                  <span className="text-[11px] text-emerald-400 font-mono">Authenticated</span>
                </div>
              </div>
            </div>
          )}
        </div>
      </div>

      <UpgradeSubscriptionModal
        isOpen={isUpgradeModalOpen}
        onClose={() => setIsUpgradeModalOpen(false)}
        userEmail={user?.email}
      />
    </div>
  );
}
