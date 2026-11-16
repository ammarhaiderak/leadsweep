import { useState, useEffect } from 'react';
import {
  Twitter, Instagram, Facebook, Linkedin, MessageCircle, Cloud, Briefcase, Layers,
  Send, AlertCircle, Calendar, // NEW FEATURE: Telegram Send & AlertCircle & Calendar icons
  Search, Hash, User, Clock, MessageSquare, Users, Image, ListFilter,
  Rocket, ArrowRight, ArrowLeft, Check, Settings2, Globe, Database, Zap, Sparkles,
} from 'lucide-react';
import { platforms } from '@/data/mockData';
import { PlatformIcon } from '@/components/ui';
import type { Platform, ScraperType } from '@/types';
import type { PageId } from '@/App';
import { api } from '@/api/client';
import { UpgradeSubscriptionModal } from '@/components/UpgradeSubscriptionModal';

const platformIconMap: Record<string, typeof Twitter> = {
  Twitter, Instagram, Facebook, Linkedin, MessageCircle, Cloud, Briefcase, Layers,
  Send, // NEW FEATURE: Telegram mapping
};


// UPDATED LOGIC: Standard scraper types plus Telegram MTProto specific scraper types
const standardScraperTypes: Array<{ id: ScraperType; label: string; icon: typeof Search; desc: string; disabled?: boolean; badge?: string }> = [
  { id: 'search', label: 'Search Results', icon: Search, desc: 'Scrape posts matching keywords, hashtags, or search queries' },
  { id: 'profile', label: 'Profile Data', icon: User, desc: 'Extract user profile info, bio, follower counts, and stats' },
  { id: 'hashtag', label: 'Hashtag Posts', icon: Hash, desc: 'Get all posts under a specific hashtag or topic' },
  { id: 'timeline', label: 'User Timeline', icon: Clock, desc: 'Scrape complete posting history of a user' },
  { id: 'replies', label: 'Replies & Comments', icon: MessageSquare, desc: 'Extract all replies and comments on a post' },
  { id: 'followers', label: 'Followers List', icon: Users, desc: 'Get follower or following lists for a profile' },
  { id: 'media', label: 'Media Download', icon: Image, desc: 'Download images, videos, and media attachments', disabled: true, badge: 'Coming soon' },
  { id: 'lists', label: 'Lists & Collections', icon: ListFilter, desc: 'Scrape curated lists, collections, or threads', disabled: true, badge: 'Coming soon' },
];

// NEW FEATURE: Telegram Specific Scraper Types
const telegramScraperTypes: Array<{ id: ScraperType; label: string; icon: typeof Search; desc: string }> = [
  { id: 'channel_messages', label: 'Channel & Group Messages', icon: MessageSquare, desc: 'Scrape messages from public channel or group by @username or t.me link' },
  { id: 'keyword_search', label: 'Keyword Search', icon: Search, desc: 'Search messages by keyword across a specific channel or globally' },
  { id: 'group_members', label: 'Group Members', icon: Users, desc: 'Extract member list & participant profiles where permissions allow' },
  { id: 'channel_info', label: 'Channel Info', icon: User, desc: 'Extract channel metadata, subscriber count, bio, and official links' },
];

// NEW FEATURE: Reddit Specific Scraper Types (no account or API key required)
const redditScraperTypes: Array<{ id: ScraperType; label: string; icon: typeof Search; desc: string }> = [
  { id: 'search', label: 'Keyword & Intent Search', icon: Search, desc: 'Find posts asking for products, tools, agencies, freelancers, or recommendations' },
  { id: 'subreddit_posts', label: 'Subreddit Discovery', icon: ListFilter, desc: 'Scan recent public posts from the subreddits you name' },
  { id: 'intent_search', label: 'Commercial Intent Discovery', icon: Zap, desc: 'Search with buying-intent phrasings across Reddit or your selected subreddits' },
];

const proxyRegions = ['Auto-Rotate', 'US-East', 'US-West', 'EU-West', 'EU-North', 'Asia-Pacific', 'UK', 'Canada'];

export function CreateScraperPage({ onNavigate, user }: { onNavigate: (page: PageId) => void; user?: any }) {
  const [step, setStep] = useState(1);
  const [selectedPlatform, setSelectedPlatform] = useState<Platform | null>(null);
  const [selectedType, setSelectedType] = useState<ScraperType | null>(null);
  const [query, setQuery] = useState('');

  // NEW FEATURE: Telegram Specific Configuration Fields
  const [telegramKeyword, setTelegramKeyword] = useState('');
  const [dateFrom, setDateFrom] = useState('');
  const [dateTo, setDateTo] = useState('');
  const [telegramSessionStatus, setTelegramSessionStatus] = useState<{
    connected: boolean;
    has_credentials: boolean;
    has_session_file: boolean;
    message: string;
  } | null>(null);
  const [dismissTelegramBanner, setDismissTelegramBanner] = useState(false);

  // NEW FEATURE: Reddit specific configuration fields
  const [redditSubreddits, setRedditSubreddits] = useState('');
  const [redditIncludeComments, setRedditIncludeComments] = useState(false);
  const [redditStatus, setRedditStatus] = useState<{
    ready: boolean;
    mode: string;
    source_provider?: string;
    source_label?: string;
    ui_state?: string;
    last_retrieved_at?: string | null;
    live_access_note?: string;
    status: string;
    fixtures_present: number;
    notes: string[];
    documented_access_note: string;
  } | null>(null);
  const [dismissRedditBanner, setDismissRedditBanner] = useState(false);

  // Check if admin or upgraded — Admin & local self-hosted accounts always have unlimited access
  const isAdmin = true;
  const userPlan = (user?.plan || '').toLowerCase();
  const isUpgraded = true;

  // Usage and credits check
  const [usedCredits, setUsedCredits] = useState<number>(0);
  const [remainingCredits, setRemainingCredits] = useState<number>(999999);
  const [isUpgradeModalOpen, setIsUpgradeModalOpen] = useState(false);

  useEffect(() => {
    if (user?.email) {
      api.getOverviewStats(user.email).then((stats) => {
        const scraped = stats.itemsScraped || 0;
        setUsedCredits(scraped);
        setRemainingCredits(999999);
      }).catch(() => {});
    }
  }, [user]);

  // Admin & self-hosted users have unlimited extraction capacity
  const maxAllowedItems = 10000;
  const [maxItems, setMaxItems] = useState(25);
  const [proxyRegion, setProxyRegion] = useState('Auto-Rotate');
  const [includeReplies, setIncludeReplies] = useState(false);
  const [includeMedia, setIncludeMedia] = useState(true);
  const [sentimentAnalysis, setSentimentAnalysis] = useState(true);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [limitError, setLimitError] = useState<string | null>(null);

  const isCreditsExhausted = !isAdmin && !isUpgraded && remainingCredits <= 0;

  const canProceed = isCreditsExhausted
    ? false
    : step === 1
    ? selectedPlatform !== null
    : step === 2
    ? selectedType !== null
    : step === 3
    ? (selectedPlatform === 'telegram'
        ? maxItems > 0 && maxItems <= maxAllowedItems
        : selectedPlatform === 'reddit'
        ? (query.trim().length > 0 || redditSubreddits.trim().length > 0) && maxItems > 0 && maxItems <= maxAllowedItems
        : query.trim().length > 0 && maxItems > 0 && maxItems <= maxAllowedItems)
    : !isSubmitting;

  useEffect(() => {
    // NEW FEATURE: Check Telegram MTProto session status
    api.getTelegramAccountStatus().then((res) => {
      setTelegramSessionStatus(res);
    }).catch(() => {
      setTelegramSessionStatus({
        connected: false,
        has_credentials: false,
        has_session_file: false,
        message: 'Could not connect to Telegram backend session.',
      });
    });
  }, [user]);


  // NEW FEATURE: Reddit requires no account or credentials; surface the access reality plainly
  useEffect(() => {
    api.getRedditStatus()
      .then((res) => setRedditStatus(res))
      .catch(() => setRedditStatus(null));
  }, [user]);

  const scraperTypesForPlatform =
    selectedPlatform === 'telegram'
      ? telegramScraperTypes
      : selectedPlatform === 'reddit'
      ? redditScraperTypes
      : standardScraperTypes;

  const handleNext = async () => {
    if (isCreditsExhausted) {
      setIsUpgradeModalOpen(true);
      return;
    }

    if (step < 4) {
      if (step === 3 && maxItems > maxAllowedItems) {
        setLimitError(`Free Trial limit: only ${maxAllowedItems} credits remaining. Please upgrade for higher extraction capacity.`);
        return;
      }
      setLimitError(null);
      setStep(step + 1);
    } else {
      // Step 4: Launching Job directly without requiring any third-party account integration
      await executeLaunch();
    }
  };

  const executeLaunch = async () => {
    setIsSubmitting(true);
    try {
      const storedUser = localStorage.getItem('leadsweep_auth_user');
      const userObj = storedUser ? JSON.parse(storedUser) : user;
      // UPDATED LOGIC: Include Telegram keyword & date range in job launch options
      await api.createScraperJob({
        platform: selectedPlatform || 'twitter',
        type: selectedType || 'search',
        query,
        maxItems: Math.min(maxItems, maxAllowedItems),
        proxyRegion,
        user_email: userObj?.email || undefined,
        options: {
          includeReplies,
          includeMedia,
          sentimentAnalysis,
          ...(selectedPlatform === 'telegram'
            ? {
                telegramKeyword: telegramKeyword.trim() || undefined,
                dateFrom: dateFrom || undefined,
                dateTo: dateTo || undefined,
              }
            : {}),
          ...(selectedPlatform === 'reddit'
            ? {
                subreddits: redditSubreddits.trim() || undefined,
                includeComments: redditIncludeComments,
                sort: 'new',
                dateFrom: dateFrom || undefined,
                dateTo: dateTo || undefined,
              }
            : {}),
        },
      });
      onNavigate('jobs');

    } catch (err: any) {
      console.error('Failed to dispatch job to backend:', err);
      if (err?.status === 402 || (err?.message && err.message.toLowerCase().includes('upgrade'))) {
        setIsUpgradeModalOpen(true);
      } else {
        setLimitError(err?.message || 'Failed to start scraping job.');
      }
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="p-4 lg:p-6 max-w-4xl mx-auto">
      {/* Steps indicator */}
      <div className="flex items-center justify-between mb-8">
        {['Platform', 'Scraper Type', 'Configuration', 'Review & Launch'].map((label, i) => (
          <div key={label} className="flex items-center flex-1">
            <div className="flex items-center gap-2.5">
              <div
                className={`w-8 h-8 rounded-full flex items-center justify-center text-sm font-bold transition-all ${
                  step > i + 1
                    ? 'bg-emerald-500 text-white'
                    : step === i + 1
                    ? 'bg-gradient-to-br from-emerald-500 to-cyan-500 text-white ring-4 ring-emerald-500/20'
                    : 'bg-gray-800 text-gray-500'
                }`}
              >
                {step > i + 1 ? <Check size={16} /> : i + 1}
              </div>
              <span className={`text-sm font-medium hidden sm:block ${step >= i + 1 ? 'text-white' : 'text-gray-500'}`}>
                {label}
              </span>
            </div>
            {i < 3 && <div className={`flex-1 h-0.5 mx-3 ${step > i + 1 ? 'bg-emerald-500' : 'bg-gray-800'}`} />}
          </div>
        ))}
      </div>

      {/* Step content */}
      <div className="bg-gray-900 border border-gray-800 rounded-2xl p-6 lg:p-8 min-h-[400px]">
        {step === 1 && (
          <div>
            <h2 className="text-xl font-bold text-white mb-2">Choose a Platform</h2>
            <p className="text-sm text-gray-400 mb-6">Select the social media platform you want to scrape data from.</p>
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
              {platforms.map((p) => {
                const Icon = platformIconMap[p.icon] || Twitter;
                const selected = selectedPlatform === p.id;
                return (
                  <button
                    key={p.id}
                    onClick={() => {
                      setSelectedPlatform(p.id);
                      setSelectedType(p.id === 'telegram' ? 'channel_messages' : 'search');
                    }}
                    className={`flex flex-col items-center gap-3 p-5 rounded-xl border-2 transition-all ${
                      selected
                        ? `${p.bgColor} scale-105`
                        : 'bg-gray-950/50 border-gray-800 hover:border-gray-700'
                    }`}
                  >
                    <Icon className={`w-8 h-8 ${selected ? p.color : 'text-gray-500'}`} />
                    <span className={`text-sm font-medium ${selected ? 'text-white' : 'text-gray-400'}`}>{p.name}</span>
                    {selected && (
                      <div className="w-5 h-5 rounded-full bg-emerald-500 flex items-center justify-center">
                        <Check size={12} className="text-white" />
                      </div>
                    )}
                  </button>
                );
              })}
            </div>
          </div>
        )}

        {step === 2 && (
          <div>
            <h2 className="text-xl font-bold text-white mb-2">Select Scraper Type</h2>
            <p className="text-sm text-gray-400 mb-6">What kind of data do you want to extract from {platforms.find(p => p.id === selectedPlatform)?.name}?</p>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              {scraperTypesForPlatform.map((type) => {
                const Icon = type.icon;
                const selected = selectedType === type.id;
                return (
                  <button
                    key={type.id}
                    disabled={(type as any).disabled}
                    onClick={() => !(type as any).disabled && setSelectedType(type.id)}
                    className={`flex items-start gap-3 p-4 rounded-xl border-2 text-left transition-all ${
                      (type as any).disabled
                        ? 'bg-gray-950/30 border-gray-900 opacity-50 cursor-not-allowed'
                        : selected
                        ? 'bg-emerald-500/10 border-emerald-500/40'
                        : 'bg-gray-950/50 border-gray-800 hover:border-gray-700'
                    }`}
                  >
                    <div className={`w-10 h-10 rounded-lg flex items-center justify-center flex-shrink-0 ${(type as any).disabled ? 'bg-gray-900' : selected ? 'bg-emerald-500/20' : 'bg-gray-800'}`}>
                      <Icon className={`w-5 h-5 ${(type as any).disabled ? 'text-gray-600' : selected ? 'text-emerald-400' : 'text-gray-400'}`} />
                    </div>
                    <div className="flex-1">
                      <div className="flex items-center gap-2">
                        <p className={`text-sm font-medium ${selected ? 'text-white' : 'text-gray-300'}`}>{type.label}</p>
                        {(type as any).badge && (
                          <span className="text-[10px] font-semibold bg-gray-800 text-amber-400 border border-amber-500/30 px-1.5 py-0.5 rounded">
                            {(type as any).badge}
                          </span>
                        )}
                      </div>
                      <p className="text-xs text-gray-500 mt-0.5">{type.desc}</p>
                    </div>
                    {selected && <Check size={16} className="text-emerald-400 flex-shrink-0 mt-1" />}
                  </button>
                );
              })}
            </div>
          </div>
        )}

        {step === 3 && (
          <div>
            <h2 className="text-xl font-bold text-white mb-2">Configure Your Scraper</h2>
            <p className="text-sm text-gray-400 mb-6">Set your search parameters and scraping options.</p>

            <div className="space-y-5">
              <div>
                <label className="text-sm font-medium text-white mb-2 block">
                  {selectedPlatform === 'telegram'
                    ? (selectedType === 'keyword_search' ? 'Channel or Group (@username or t.me link, or leave empty for global)' : 'Channel or Group (@username or t.me link)')
                    : selectedPlatform === 'reddit'
                    ? (selectedType === 'subreddit_posts' ? 'Optional Keyword Filter (leave empty to read recent posts)' : 'Keywords, Need, or Problem Phrase')
                    : selectedType === 'profile' || selectedType === 'timeline' || selectedType === 'followers'
                    ? 'Username or Profile URL'
                    : selectedType === 'hashtag'
                    ? 'Hashtag (without #)'
                    : 'Search Query'}
                </label>
                <div className="relative">
                  {selectedType === 'hashtag' && <Hash size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-500" />}
                  {selectedType !== 'hashtag' && <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-500" />}
                  <input
                    type="text"
                    value={query}
                    onChange={(e) => setQuery(e.target.value)}
                    placeholder={
                      selectedPlatform === 'telegram'
                        ? '@telegram, https://t.me/durov, or durov'
                        : selectedPlatform === 'reddit'
                        ? 'looking for an AI automation agency, need a scraping tool'
                        : selectedType === 'hashtag'
                        ? 'AI, technology, sports...'
                        : selectedType === 'profile'
                        ? '@NASA, nasa, https://x.com/NASA'
                        : 'hire developer or build projects, ai engineer | founder'
                    }
                    className={`w-full bg-gray-950 border border-gray-800 rounded-xl py-3 ${selectedType === 'hashtag' ? 'pl-9' : 'pl-10'} pr-4 text-sm text-white placeholder-gray-600 outline-none focus:border-emerald-500/50 transition-colors`}
                  />
                </div>
                {selectedPlatform === 'telegram' ? (
                  <p className="text-xs text-gray-500 mt-1.5">
                    Empty = global search using your ICP / channel registry.
                  </p>
                ) : (
                  <p className="text-xs text-gray-500 mt-1.5">
                    To scrape this account's posts choose User Timeline; Profile Data returns only the account details.
                  </p>
                )}

                {/* NEW FEATURE: Keyword Search for Telegram */}
                {selectedPlatform === 'telegram' && selectedType === 'keyword_search' && (
                  <div className="mt-4">
                    <label className="text-sm font-medium text-white mb-2 block flex items-center gap-1.5">
                      <Search size={14} className="text-sky-400" /> Search Keyword or Phrase
                    </label>
                    <input
                      type="text"
                      value={telegramKeyword}
                      onChange={(e) => setTelegramKeyword(e.target.value)}
                      placeholder="e.g. bitcoin, hiring, release, update..."
                      className="w-full bg-gray-950 border border-gray-800 rounded-xl py-3 px-4 text-sm text-white placeholder-gray-600 outline-none focus:border-emerald-500/50 transition-colors"
                    />
                  </div>
                )}

                {/* NEW FEATURE: Date Range Filter for Telegram */}
                {selectedPlatform === 'telegram' && (
                  <div className="mt-4 grid grid-cols-1 sm:grid-cols-2 gap-4">
                    <div>
                      <label className="text-xs font-medium text-gray-300 mb-1.5 flex items-center gap-1.5">
                        <Calendar size={13} className="text-emerald-400" /> Date From (Optional)
                      </label>
                      <div className="relative flex items-center">
                        <input
                          id="tg-date-from"
                          type="date"
                          value={dateFrom}
                          onChange={(e) => setDateFrom(e.target.value)}
                          className="w-full bg-gray-950 border border-gray-700/80 hover:border-emerald-500/50 rounded-xl py-2.5 pl-3.5 pr-10 text-xs text-white outline-none focus:border-emerald-500 transition-all font-mono"
                        />
                        <button
                          type="button"
                          onClick={() => {
                            const el = document.getElementById('tg-date-from') as any;
                            if (el && typeof el.showPicker === 'function') el.showPicker();
                            else el?.focus();
                          }}
                          className="absolute right-2.5 p-1 text-emerald-400 hover:text-emerald-300 bg-emerald-500/10 hover:bg-emerald-500/20 rounded-lg transition-colors"
                          title="Open Calendar"
                        >
                          <Calendar size={15} />
                        </button>
                      </div>
                    </div>
                    <div>
                      <label className="text-xs font-medium text-gray-300 mb-1.5 flex items-center gap-1.5">
                        <Calendar size={13} className="text-emerald-400" /> Date To (Optional)
                      </label>
                      <div className="relative flex items-center">
                        <input
                          id="tg-date-to"
                          type="date"
                          value={dateTo}
                          onChange={(e) => setDateTo(e.target.value)}
                          className="w-full bg-gray-950 border border-gray-700/80 hover:border-emerald-500/50 rounded-xl py-2.5 pl-3.5 pr-10 text-xs text-white outline-none focus:border-emerald-500 transition-all font-mono"
                        />
                        <button
                          type="button"
                          onClick={() => {
                            const el = document.getElementById('tg-date-to') as any;
                            if (el && typeof el.showPicker === 'function') el.showPicker();
                            else el?.focus();
                          }}
                          className="absolute right-2.5 p-1 text-emerald-400 hover:text-emerald-300 bg-emerald-500/10 hover:bg-emerald-500/20 rounded-lg transition-colors"
                          title="Open Calendar"
                        >
                          <Calendar size={15} />
                        </button>
                      </div>
                    </div>
                  </div>
                )}

                {/* NEW FEATURE: Reddit configuration (no account, API key, or token required) */}
                {selectedPlatform === 'reddit' && (
                  <div className="mt-4 space-y-4">
                    <div>
                      <label className="text-sm font-medium text-white mb-2 flex items-center gap-1.5">
                        <MessageCircle size={14} className="text-orange-400" /> Target Subreddits (Optional)
                      </label>
                      <input
                        type="text"
                        value={redditSubreddits}
                        onChange={(e) => setRedditSubreddits(e.target.value)}
                        placeholder="r/SaaS, r/webdev, r/Entrepreneur"
                        className="w-full bg-gray-950 border border-gray-800 rounded-xl py-3 px-4 text-sm text-white placeholder-gray-600 outline-none focus:border-orange-500/50 transition-colors"
                      />
                      <p className="text-xs text-gray-500 mt-1.5">
                        Comma-separated public subreddits. Leave empty to search across Reddit. Private or restricted communities are never accessed.
                      </p>
                    </div>

                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                      <div>
                        <label className="text-xs font-medium text-gray-300 mb-1.5 flex items-center gap-1.5">
                          <Calendar size={13} className="text-orange-400" /> Posted After (Optional)
                        </label>
                        <input
                          type="date"
                          value={dateFrom}
                          onChange={(e) => setDateFrom(e.target.value)}
                          className="w-full bg-gray-950 border border-gray-700/80 hover:border-orange-500/50 rounded-xl py-2.5 pl-3.5 pr-3 text-xs text-white outline-none focus:border-orange-500 transition-all font-mono"
                        />
                      </div>
                      <div>
                        <label className="text-xs font-medium text-gray-300 mb-1.5 flex items-center gap-1.5">
                          <Calendar size={13} className="text-orange-400" /> Posted Before (Optional)
                        </label>
                        <input
                          type="date"
                          value={dateTo}
                          onChange={(e) => setDateTo(e.target.value)}
                          className="w-full bg-gray-950 border border-gray-700/80 hover:border-orange-500/50 rounded-xl py-2.5 pl-3.5 pr-3 text-xs text-white outline-none focus:border-orange-500 transition-all font-mono"
                        />
                      </div>
                    </div>

                    <label className="flex items-center justify-between p-3 rounded-xl bg-gray-950/50 border border-gray-800 cursor-pointer hover:border-gray-700 transition-colors">
                      <span className="text-sm text-gray-300">
                        Attach comments as supporting evidence
                        <span className="block text-xs text-gray-500 mt-0.5">Comments support their parent post only; they never become separate leads.</span>
                      </span>
                      <button
                        type="button"
                        onClick={() => setRedditIncludeComments(!redditIncludeComments)}
                        className={`relative w-11 h-6 rounded-full transition-colors ${redditIncludeComments ? 'bg-orange-500' : 'bg-gray-700'}`}
                      >
                        <div className="absolute top-0.5 w-5 h-5 rounded-full bg-white transition-transform" style={{ transform: redditIncludeComments ? 'translateX(22px)' : 'translateX(2px)' }} />
                      </button>
                    </label>
                  </div>
                )}

                {(selectedType === 'search' || selectedType === 'hashtag') && selectedPlatform !== 'telegram' && (
                  <p className="text-xs text-emerald-400/90 mt-2 flex items-center gap-1.5">
                    <span className="font-semibold px-1.5 py-0.5 rounded bg-emerald-500/10 border border-emerald-500/20 text-[10px] tracking-wide uppercase">Multi-Query Enabled</span>
                    Separate multiple phrases with <code className="bg-gray-800/80 px-1 py-0.5 rounded text-gray-300">or</code>, <code className="bg-gray-800/80 px-1 py-0.5 rounded text-gray-300">,</code>, or <code className="bg-gray-800/80 px-1 py-0.5 rounded text-gray-300">|</code> for parallel scraping & auto-deduplication.
                  </p>
                )}

              </div>

              <div className="grid grid-cols-1 sm:grid-cols-2 gap-5">
                <div>
                  <div className="flex items-center justify-between mb-2">
                    <label className="text-sm font-medium text-white flex items-center gap-2">
                      <Database size={14} className="text-emerald-400" /> Max Items to Scrape
                    </label>
                    <span className={`text-xs font-medium ${maxItems > maxAllowedItems ? 'text-rose-400 font-bold' : 'text-gray-400'}`}>
                      Max Allowed: {maxAllowedItems}
                    </span>
                  </div>
                  <input
                    type="number"
                    min={1}
                    max={maxAllowedItems}
                    value={maxItems}
                    onChange={(e) => {
                      const val = parseInt(e.target.value) || 0;
                      setMaxItems(val);
                      if (val > maxAllowedItems) {
                        setLimitError(`Your Free Trial plan only allows up to ${maxAllowedItems} items. Please upgrade your plan to scrape more.`);
                      } else {
                        setLimitError(null);
                      }
                    }}
                    className={`w-full bg-gray-950 border ${maxItems > maxAllowedItems ? 'border-rose-500/80' : 'border-gray-800'} rounded-xl py-3 px-4 text-sm text-white placeholder-gray-600 outline-none focus:border-emerald-500/50 transition-colors`}
                  />
                  {limitError && (
                    <p className="text-xs text-rose-400 mt-1.5 flex items-center gap-1 font-medium">
                      ⚠️ {limitError}
                    </p>
                  )}
                  <p className="text-xs text-gray-500 mt-1.5">
                    {isAdmin
                      ? 'Enterprise Admin Tier: Unlimited scraping capability.'
                      : isUpgraded
                      ? `Upgraded Tier: Up to ${maxAllowedItems.toLocaleString()} items per run.`
                      : 'Free Trial Plan: Limited to 10 items maximum. Upgrade your plan to increase limits.'}
                  </p>
                </div>

                <div>
                  <label className="text-sm font-medium text-white mb-2 block flex items-center gap-2">
                    <Globe size={14} className="text-cyan-400" /> Proxy Region
                  </label>
                  <select
                    value={proxyRegion}
                    onChange={(e) => setProxyRegion(e.target.value)}
                    className="w-full bg-gray-950 border border-gray-800 rounded-xl py-3 px-4 text-sm text-white outline-none focus:border-emerald-500/50 transition-colors"
                  >
                    {proxyRegions.map((r) => (
                      <option key={r} value={r} className="bg-gray-900">{r}</option>
                    ))}
                  </select>
                </div>
              </div>

              <div>
                <p className="text-sm font-medium text-white mb-3 flex items-center gap-2">
                  <Settings2 size={14} className="text-sky-400" /> Advanced Options
                </p>
                <div className="space-y-2.5">
                  {[
                    { label: 'Include replies & comments', value: includeReplies, set: setIncludeReplies },
                    { label: 'Download media attachments', value: includeMedia, set: setIncludeMedia },
                    { label: 'Run sentiment analysis on text', value: sentimentAnalysis, set: setSentimentAnalysis },
                  ].map((opt) => (
                    <label key={opt.label} className="flex items-center justify-between p-3 rounded-xl bg-gray-950/50 border border-gray-800 cursor-pointer hover:border-gray-700 transition-colors">
                      <span className="text-sm text-gray-300">{opt.label}</span>
                      <button
                        onClick={() => opt.set(!opt.value)}
                        className={`relative w-11 h-6 rounded-full transition-colors ${opt.value ? 'bg-emerald-500' : 'bg-gray-700'}`}
                      >
                        <div className={`absolute top-0.5 w-5 h-5 rounded-full bg-white transition-transform ${opt.value ? 'translate-x-5.5' : 'translate-x-0.5'}`} style={{ transform: opt.value ? 'translateX(22px)' : 'translateX(2px)' }} />
                      </button>
                    </label>
                  ))}
                </div>
              </div>
            </div>
          </div>
        )}

        {step === 4 && (
          <div>
            <h2 className="text-xl font-bold text-white mb-2">Review & Launch</h2>
            <p className="text-sm text-gray-400 mb-6">Confirm your scraper configuration before launching.</p>

            <div className="space-y-4">
              <div className="bg-gray-950/50 border border-gray-800 rounded-xl p-5">
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                  {[
                    { label: 'Platform', value: platforms.find(p => p.id === selectedPlatform)?.name || '', icon: selectedPlatform ? platformIconMap[platforms.find(p => p.id === selectedPlatform)!.icon] : Twitter },
                    {
                      label: 'Scraper Type',
                      value: scraperTypesForPlatform.find(t => t.id === selectedType)?.label || '',
                      icon: Search,
                    },
                    { label: 'Target Channel / Query', value: query || '—', icon: Hash },
                    ...(selectedPlatform === 'telegram' && telegramKeyword ? [{ label: 'Search Keyword', value: telegramKeyword, icon: Search }] : []),
                    ...(selectedPlatform === 'telegram' && (dateFrom || dateTo) ? [{ label: 'Date Range', value: `${dateFrom || 'Any'} → ${dateTo || 'Present'}`, icon: Clock }] : []),
                    ...(selectedPlatform === 'reddit' && redditSubreddits ? [{ label: 'Target Subreddits', value: redditSubreddits, icon: MessageCircle }] : []),
                    ...(selectedPlatform === 'reddit' ? [{ label: 'Comment Evidence', value: redditIncludeComments ? 'Enabled' : 'Disabled', icon: MessageSquare }] : []),
                    ...(selectedPlatform === 'reddit' && (dateFrom || dateTo) ? [{ label: 'Posted Between', value: `${dateFrom || 'Any'} → ${dateTo || 'Present'}`, icon: Clock }] : []),
                    { label: 'Max Items', value: maxItems.toLocaleString(), icon: Database },
                    { label: 'Proxy Region', value: proxyRegion, icon: Globe },
                    { label: 'Sentiment Analysis', value: sentimentAnalysis ? 'Enabled' : 'Disabled', icon: Zap },
                  ].map((item) => {
                    const Icon = item.icon;
                    return (
                      <div key={item.label} className="flex items-center gap-3">
                        <div className="w-8 h-8 rounded-lg bg-gray-800 flex items-center justify-center flex-shrink-0">
                          <Icon size={14} className="text-gray-400" />
                        </div>
                        <div className="min-w-0">
                          <p className="text-xs text-gray-500">{item.label}</p>
                          <p className="text-sm font-medium text-white truncate">{item.value}</p>
                        </div>
                      </div>
                    );
                  })}
                </div>
              </div>

              <div className="bg-gradient-to-br from-emerald-500/10 to-cyan-500/5 border border-emerald-500/20 rounded-xl p-5">
                <div className="flex items-center gap-3 mb-3">
                  <Check size={18} className="text-emerald-400" />
                  <span className="text-sm font-medium text-white">Ready to launch</span>
                </div>
                <div className="grid grid-cols-3 gap-4 text-center">
                  <div>
                    <p className="text-xs text-gray-400">Estimated Time</p>
                    <p className="text-sm font-bold text-white mt-1">~1 min</p>
                  </div>
                  <div>
                    <p className="text-xs text-gray-400">Estimated Cost</p>
                    <p className="text-sm font-bold text-emerald-400 mt-1">$0.00</p>
                  </div>
                  <div>
                    <p className="text-xs text-gray-400">Items</p>
                    <p className="text-sm font-bold text-white mt-1">{maxItems.toLocaleString()}</p>
                  </div>
                </div>
              </div>

              {/* Step 4 Error display */}
              {limitError && (
                <div className="p-4 rounded-xl bg-rose-500/10 border border-rose-500/30 flex items-center gap-3 text-rose-300 text-sm animate-in fade-in">
                  <AlertCircle size={18} className="shrink-0 text-rose-400" />
                  <span>{limitError}</span>
                </div>
              )}
            </div>
          </div>
        )}

      </div>

      {/* Navigation buttons */}
      <div className="flex items-center justify-between mt-6">
        <button
          onClick={() => step > 1 ? setStep(step - 1) : onNavigate('dashboard')}
          className="flex items-center gap-2 text-sm text-gray-400 hover:text-white transition-colors px-4 py-2.5"
        >
          <ArrowLeft size={16} /> {step > 1 ? 'Back' : 'Cancel'}
        </button>
        <button
          onClick={handleNext}
          disabled={!canProceed && !isCreditsExhausted}
          className={`flex items-center gap-2 px-6 py-3 rounded-xl font-semibold text-sm transition-all ${
            isCreditsExhausted
              ? 'bg-gradient-to-r from-amber-500 to-rose-500 hover:from-amber-400 hover:to-rose-400 text-white shadow-lg shadow-amber-500/20 cursor-pointer animate-pulse'
              : canProceed
              ? 'bg-gradient-to-r from-emerald-500 to-cyan-500 hover:from-emerald-400 hover:to-cyan-400 text-white shadow-lg shadow-emerald-500/20'
              : 'bg-gray-800 text-gray-500 cursor-not-allowed'
          }`}
        >
          {isCreditsExhausted ? (
            <><Sparkles size={16} /> Upgrade Subscription to Scrape</>
          ) : step === 4 ? (
            <><Rocket size={16} /> Launch Scraper</>
          ) : (
            <>Continue <ArrowRight size={16} /></>
          )}
        </button>
      </div>

      {/* Subscription Upgrade Modal */}
      <UpgradeSubscriptionModal
        isOpen={isUpgradeModalOpen}
        onClose={() => setIsUpgradeModalOpen(false)}
        userEmail={user?.email}
      />
    </div>
  );
}
