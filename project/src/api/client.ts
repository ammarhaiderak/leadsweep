/**
 * API client for connecting Bolt Frontend to FastAPI backend.
 */
import type { ScraperJob, ScrapedItem, ProxyNode, ScheduledTask } from '@/types';

const BASE_URL = import.meta.env.VITE_API_BASE_URL !== undefined ? import.meta.env.VITE_API_BASE_URL : '';

export interface OverviewStats {
  totalJobs: number;
  activeJobs: number;
  itemsScraped: number;
  platformsConnected: number;
  successRate: number;
  monthlyCost: number;
  computeUsed: number;
  computeLimit: number;
  storageUsed: number;
  storageLimit: number;
}

export interface ScrapePayload {
  platform: string;
  type: string;
  query: string;
  maxItems: number;
  proxyRegion?: string;
  options?: {
    includeReplies?: boolean;
    includeMedia?: boolean;
    sentimentAnalysis?: boolean;
    // NEW FEATURE: Reddit discovery options (zero-credential integration)
    subreddits?: string;
    includeComments?: boolean;
    sort?: string;
    dateFrom?: string;
    dateTo?: string;
  };
}

export interface ActivityEvent {
  id: string;
  userId: string | null;
  userEmail: string;
  category: string;
  eventType: string;
  description: string;
  resourceType: string | null;
  resourceId: string | null;
  status: string;
  metadata: Record<string, any>;
  createdAt: string;
}

export const api = {
  async getOverviewStats(userEmail?: string): Promise<OverviewStats> {
    try {
      const url = userEmail ? `${BASE_URL}/v1/stats/overview?user_email=${encodeURIComponent(userEmail)}` : `${BASE_URL}/v1/stats/overview`;
      const res = await fetch(url);
      if (!res.ok) throw new Error('Failed to fetch stats');
      return await res.json();
    } catch {
      return {
        totalJobs: 0,
        activeJobs: 0,
        itemsScraped: 0,
        platformsConnected: 8,
        successRate: 100,
        monthlyCost: 0,
        computeUsed: 0,
        computeLimit: 999,
        storageUsed: 0,
        storageLimit: 999,
      };
    }
  },

  async getJobs(status?: string, userEmail?: string): Promise<ScraperJob[]> {
    try {
      const sp = new URLSearchParams();
      if (status && status !== 'all') sp.set('status', status);
      if (userEmail) sp.set('user_email', userEmail);
      const q = sp.toString();
      const url = q ? `${BASE_URL}/v1/jobs?${q}` : `${BASE_URL}/v1/jobs`;
      const res = await fetch(url);
      if (!res.ok) throw new Error('Failed to fetch jobs');
      return await res.json();
    } catch {
      return [];
    }
  },

  async getJobData(jobId: string, limit: number = 100): Promise<any[]> {
    const token = localStorage.getItem('leadsweep_auth_token');
    const headers: Record<string, string> = {};
    if (token) headers['Authorization'] = `Bearer ${token}`;
    const res = await fetch(`${BASE_URL}/v1/data/${encodeURIComponent(jobId)}?limit=${limit}`, { headers });
    if (!res.ok) {
      throw new Error(`Failed to load data for job: HTTP ${res.status}`);
    }
    return await res.json();
  },

  async createScraperJob(payload: ScrapePayload & { user_email?: string }): Promise<ScraperJob> {
    const res = await fetch(`${BASE_URL}/v1/scrape`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    if (!res.ok) {
      let errDetail = 'Failed to launch scraper job';
      try {
        const errJson = await res.json();
        if (errJson.detail) errDetail = errJson.detail;
      } catch {}
      const error: any = new Error(errDetail);
      error.status = res.status;
      throw error;
    }
    return await res.json();
  },

  async getActivity(params: { user_email?: string; category?: string; limit?: number; offset?: number } = {}): Promise<{ events: ActivityEvent[]; total: number }> {
    try {
      const sp = new URLSearchParams();
      if (params.user_email) sp.set('user_email', params.user_email);
      if (params.category && params.category !== 'all') sp.set('category', params.category);
      if (params.limit) sp.set('limit', String(params.limit));
      if (params.offset) sp.set('offset', String(params.offset));
      const res = await fetch(`${BASE_URL}/v1/activity?${sp.toString()}`);
      if (!res.ok) throw new Error('Failed to fetch activity');
      return await res.json();
    } catch {
      return { events: [], total: 0 };
    }
  },

  async getUsers(): Promise<Array<{
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
  }>> {
    try {
      const token = localStorage.getItem('leadsweep_auth_token') || '';
      const res = await fetch(`${BASE_URL}/v1/users`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!res.ok) throw new Error('Failed to fetch users');
      return await res.json();
    } catch {
      return [];
    }
  },

  async getScrapedData(params: {
    page?: number;
    limit?: number;
    search?: string;
    platform?: string;
    sentiment?: string;
    user_email?: string;
  } = {}): Promise<{ items: ScrapedItem[]; total: number; page: number; totalPages: number }> {
    try {
      const sp = new URLSearchParams();
      if (params.page) sp.set('page', String(params.page));
      if (params.limit) sp.set('limit', String(params.limit));
      if (params.search) sp.set('q', params.search);
      if (params.platform && params.platform !== 'all') sp.set('platform', params.platform);
      if (params.sentiment && params.sentiment !== 'all') sp.set('sentiment', params.sentiment);
      if (params.user_email) sp.set('user_email', params.user_email);

      const token = localStorage.getItem('leadsweep_auth_token') || '';
      const headers: Record<string, string> = {};
      if (token) headers['Authorization'] = `Bearer ${token}`;

      const res = await fetch(`${BASE_URL}/v1/data?${sp.toString()}`, { headers });
      if (!res.ok) throw new Error('Failed to fetch data');
      return await res.json();
    } catch {
      return { items: [], total: 0, page: 1, totalPages: 1 };
    }
  },

  getExportUrl(format: 'json' | 'csv' | 'jsonl' | 'xlsx' | 'tsv' = 'csv', search?: string, runId?: string): string {
    const sp = new URLSearchParams({ format });
    if (search) sp.set('q', search);
    if (runId) sp.set('run_id', runId);
    return `${BASE_URL}/api/export?${sp.toString()}`;
  },

  // NEW FEATURE: Surgical downloadExport helper with blob download & filename extraction
  async downloadExport(params: {
    scope?: 'job' | 'all';
    job_id?: string;
    run_id?: string;
    format?: 'csv' | 'json' | 'jsonl' | 'xlsx' | 'tsv';
    kind?: 'leads' | 'raw';
    min_score?: number;
    platform?: string;
    q?: string;
  } = {}): Promise<string> {
    const sp = new URLSearchParams();
    sp.set('scope', params.scope || (params.job_id || params.run_id ? 'job' : 'all'));
    if (params.job_id) sp.set('job_id', params.job_id);
    if (params.run_id) sp.set('run_id', params.run_id);
    sp.set('format', params.format || 'csv');
    sp.set('kind', params.kind || 'leads');
    if (params.min_score !== undefined) sp.set('min_score', String(params.min_score));
    if (params.platform) sp.set('platform', params.platform);
    if (params.q) sp.set('q', params.q);

    const token = localStorage.getItem('leadsweep_auth_token');
    const headers: Record<string, string> = {};
    if (token) headers['Authorization'] = `Bearer ${token}`;

    const url = `${BASE_URL}/api/export?${sp.toString()}`;
    const res = await fetch(url, { headers });
    if (!res.ok) {
      let errMsg = 'Failed to download export';
      try {
        const errJson = await res.json();
        errMsg = errJson.detail || errJson.error || errMsg;
      } catch {}
      throw new Error(errMsg);
    }

    // Extract filename from Content-Disposition header if available
    let filename = `leadsweep_export_${Date.now()}.${params.format || 'csv'}`;
    const disposition = res.headers.get('Content-Disposition');
    if (disposition) {
      const match = disposition.match(/filename=["']?([^"';]+)["']?/i);
      if (match && match[1]) filename = match[1].trim();
    }

    const blob = await res.blob();
    const blobUrl = window.URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = blobUrl;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    setTimeout(() => window.URL.revokeObjectURL(blobUrl), 2000);
    return filename;
  },

  async getProxies(): Promise<ProxyNode[]> {
    try {
      const res = await fetch(`${BASE_URL}/v1/proxies`);
      if (!res.ok) throw new Error('Failed to fetch proxies');
      return await res.json();
    } catch {
      return [];
    }
  },

  async getSchedules(userEmail?: string): Promise<ScheduledTask[]> {
    try {
      const sp = new URLSearchParams();
      if (userEmail) sp.set('user_email', userEmail);
      const res = await fetch(`${BASE_URL}/v1/schedules?${sp.toString()}`);
      if (!res.ok) throw new Error('Failed to fetch schedules');
      return await res.json();
    } catch {
      return [];
    }
  },

  async pauseJob(id: string): Promise<void> {
    await fetch(`${BASE_URL}/v1/jobs/${id}/pause`, { method: 'POST' });
  },

  async resumeJob(id: string): Promise<void> {
    await fetch(`${BASE_URL}/v1/jobs/${id}/resume`, { method: 'POST' });
  },

  async retryJob(id: string): Promise<ScraperJob | void> {
    const res = await fetch(`${BASE_URL}/v1/jobs/${id}/retry`, { method: 'POST' });
    if (res.ok) return await res.json();
  },

  async cancelJob(id: string): Promise<void> {
    await fetch(`${BASE_URL}/v1/jobs/${id}/cancel`, { method: 'POST' });
  },

  async deleteJob(id: string): Promise<void> {
    await fetch(`${BASE_URL}/v1/jobs/${id}`, { method: 'DELETE' });
  },

  async login(email: string, password: string): Promise<{ token: string; user: any }> {
    const url = `${BASE_URL}/v1/auth/login`;
    let res: Response;
    try {
      res = await fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email, password }),
      });
    } catch {
      const resolvedUrl = url.startsWith('http')
        ? url
        : (typeof window !== 'undefined' ? `${window.location.origin}${url}` : `http://localhost:8000${url}`);
      throw new Error(`Cannot reach the server at ${resolvedUrl}`);
    }
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || 'Invalid email or password');
    }
    return await res.json();
  },

  async getMe(token?: string): Promise<any> {
    const url = token ? `${BASE_URL}/v1/auth/me?token=${encodeURIComponent(token)}` : `${BASE_URL}/v1/auth/me`;
    const res = await fetch(url);
    if (!res.ok) throw new Error('Failed to fetch user');
    return await res.json();
  },

  async getAnalytics(scope: 'user' | 'global' = 'user', userEmail?: string): Promise<{
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
  }> {
    const token = localStorage.getItem('leadsweep_auth_token') || '';
    const sp = new URLSearchParams({ scope });
    if (userEmail) sp.set('user_email', userEmail);
    const headers: Record<string, string> = {};
    if (token) headers['Authorization'] = `Bearer ${token}`;

    const res = await fetch(`${BASE_URL}/v1/analytics?${sp.toString()}`, { headers });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || `HTTP ${res.status}: Failed to load analytics`);
    }
    return await res.json();
  },

  async getAdminAuditLogs(params: {
    severity?: string;
    search?: string;
    user_email?: string;
    limit?: number;
    offset?: number;
  } = {}): Promise<{
    logs: Array<{
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
    }>;
    total: number;
    limit: number;
    offset: number;
  }> {
    const token = localStorage.getItem('leadsweep_auth_token') || '';
    const sp = new URLSearchParams();
    if (params.severity && params.severity !== 'all') sp.set('severity', params.severity);
    if (params.search) sp.set('search', params.search);
    if (params.user_email) sp.set('user_email', params.user_email);
    if (params.limit) sp.set('limit', String(params.limit));
    if (params.offset) sp.set('offset', String(params.offset));

    const res = await fetch(`${BASE_URL}/v1/admin/audit-logs?${sp.toString()}`, {
      headers: {
        Authorization: `Bearer ${token}`,
      },
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || `HTTP ${res.status}: Failed to load admin audit logs`);
    }
    return await res.json();
  },

  async getXAccountStatus(userEmail?: string): Promise<{
    connected: boolean;
    user_email: string;
    session_path?: string | null;
    message: string;
  }> {
    try {
      const email = userEmail || 'admin';
      const res = await fetch(`${BASE_URL}/v1/x-account/status?user_email=${encodeURIComponent(email)}`);
      if (!res.ok) throw new Error('Failed to query account status');
      return await res.json();
    } catch {
      return {
        connected: false,
        user_email: userEmail || 'admin',
        message: 'Account not connected',
      };
    }
  },

  // NEW FEATURE: Query Telegram MTProto Session Connection Status
  // NEW FEATURE: Reddit access/config status (no credentials involved)
  async getRedditStatus(): Promise<{
    enabled: boolean;
    mode: string;
    source_provider?: string;
    source_label?: string;
    ui_state?: string;
    last_retrieved_at?: string | null;
    live_access_note?: string;
    ready: boolean;
    requires_credentials: boolean;
    personal_account_required: boolean;
    fixtures_present: number;
    status: string;
    documented_access_note: string;
    notes: string[];
    status_detail?: string;
  }> {
    try {
      const res = await fetch(`${BASE_URL}/v1/reddit/status`);
      if (!res.ok) throw new Error(`Reddit status HTTP ${res.status}`);
      return await res.json();
    } catch {
      return {
        enabled: false,
        mode: 'unavailable',
        source_provider: 'unavailable',
        source_label: 'Unavailable',
        ui_state: 'LIVE SOURCE UNAVAILABLE',
        last_retrieved_at: null,
        ready: false,
        requires_credentials: false,
        personal_account_required: false,
        fixtures_present: 0,
        status: 'UNAVAILABLE',
        documented_access_note: 'Could not reach the Reddit status endpoint.',
        notes: [],
      };
    }
  },

  async getTelegramAccountStatus(): Promise<{
    connected: boolean;
    has_credentials: boolean;
    has_session_file: boolean;
    session_path?: string;
    message: string;
  }> {
    try {
      const res = await fetch(`${BASE_URL}/v1/telegram-account/status`);
      if (!res.ok) throw new Error('Failed to query Telegram status');
      return await res.json();
    } catch {
      return {
        connected: false,
        has_credentials: false,
        has_session_file: false,
        message: 'Telegram session not connected. Set TELEGRAM_API_ID in .env and run python telegram_login.py',
      };
    }
  },


  async connectXAccount(userEmail?: string, timeoutSeconds: number = 300): Promise<{
    status: string;
    connected: boolean;
    message: string;
  }> {
    const email = userEmail || 'admin';
    const res = await fetch(`${BASE_URL}/v1/x-account/connect`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ user_email: email, timeout_seconds: timeoutSeconds }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || 'Failed to authenticate X account. Verification timed out or window was closed.');
    }
    return await res.json();
  },

  async disconnectXAccount(userEmail?: string): Promise<{
    status: string;
    connected: boolean;
    message: string;
  }> {
    const email = userEmail || 'admin';
    const res = await fetch(`${BASE_URL}/v1/x-account/disconnect`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ user_email: email }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || 'Failed to disconnect account');
    }
    return await res.json();
  },

  async updateUserProfile(data: { name?: string; company?: string; email?: string }): Promise<any> {
    const token = localStorage.getItem('leadsweep_auth_token') || '';
    const res = await fetch(`${BASE_URL}/v1/users/profile`, {
      method: 'PUT',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${token}`,
      },
      body: JSON.stringify(data),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || 'Failed to update profile');
    }
    return await res.json();
  },

  async getNotifications(): Promise<any[]> {
    const token = localStorage.getItem('leadsweep_auth_token') || '';
    const res = await fetch(`${BASE_URL}/v1/notifications`, {
      headers: {
        Authorization: `Bearer ${token}`,
      },
    });
    if (!res.ok) return [];
    return await res.json();
  },

  async forgotPassword(email: string): Promise<any> {
    const res = await fetch(`${BASE_URL}/v1/auth/forgot-password`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || 'Failed to send password reset request');
    }
    return await res.json();
  },

  async resetPassword(token: string, email: string, newPassword: string): Promise<any> {
    const res = await fetch(`${BASE_URL}/v1/auth/reset-password`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ token, email, new_password: newPassword }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || 'Failed to reset password');
    }
    return await res.json();
  },

  async adminGetUsers(): Promise<any[]> {
    const token = localStorage.getItem('leadsweep_auth_token') || '';
    const res = await fetch(`${BASE_URL}/v1/admin/users`, {
      headers: {
        Authorization: `Bearer ${token}`,
      },
    });
    if (!res.ok) return [];
    return await res.json();
  },

  async adminCreateUser(data: { name: string; email: string; password: string; role?: string; company?: string; plan?: string }): Promise<any> {
    const token = localStorage.getItem('leadsweep_auth_token') || '';
    const res = await fetch(`${BASE_URL}/v1/admin/users`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${token}`,
      },
      body: JSON.stringify(data),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || 'Failed to create user');
    }
    return await res.json();
  },

  async adminDeleteUser(targetEmail: string): Promise<any> {
    const token = localStorage.getItem('leadsweep_auth_token') || '';
    const res = await fetch(`${BASE_URL}/v1/admin/users/${encodeURIComponent(targetEmail)}`, {
      method: 'DELETE',
      headers: {
        Authorization: `Bearer ${token}`,
      },
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || 'Failed to remove user');
    }
    return await res.json();
  },
};


