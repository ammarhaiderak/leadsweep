import type {
  Platform,
  ScraperJob,
  ScrapedItem,
  ScheduledTask,
  ProxyNode,
  Integration,
  PlatformInfo,
  FAQItem,
  FeatureItem,
} from '@/types';

export const platforms: PlatformInfo[] = [
  {
    id: 'twitter',
    name: 'Twitter (X)',
    color: 'text-sky-400',
    bgColor: 'bg-sky-500/10 border-sky-500/30',
    icon: 'Twitter',
    dataPoints: ['Tweets', 'Profiles', 'Threads', 'Replies', 'Followers', 'Hashtags', 'Media', 'Engagement'],
  },
  {
    id: 'linkedin',
    name: 'LinkedIn',
    color: 'text-blue-400',
    bgColor: 'bg-blue-500/10 border-blue-500/30',
    icon: 'Linkedin',
    dataPoints: ['Profiles', 'Posts', 'Companies', 'Founders', 'Connections', 'Articles', 'Leads', 'Skills'],
  },
  {
    id: 'upwork',
    name: 'Upwork',
    color: 'text-emerald-400',
    bgColor: 'bg-emerald-500/10 border-emerald-500/30',
    icon: 'Briefcase',
    dataPoints: ['Freelancers', 'Agencies', 'Job Posts', 'Budgets', 'Skills', 'Proposals', 'Contracts', 'Hourly Rates'],
  },
  {
    id: 'fiverr',
    name: 'Fiverr',
    color: 'text-teal-400',
    bgColor: 'bg-teal-500/10 border-teal-500/30',
    icon: 'Layers',
    dataPoints: ['Gigs', 'Sellers', 'Agencies', 'Reviews', 'Pricing', 'Ratings', 'Services', 'Delivery Times'],
  },
  {
    id: 'reddit',
    name: 'Reddit',
    color: 'text-orange-400',
    bgColor: 'bg-orange-500/10 border-orange-500/30',
    icon: 'MessageCircle',
    dataPoints: ['Posts', 'Comments', 'Subreddits', 'Users', 'Upvotes', 'Awards', 'Search', 'Trending'],
  },
  {
    id: 'bluesky',
    name: 'BlueSky',
    color: 'text-cyan-400',
    bgColor: 'bg-cyan-500/10 border-cyan-500/30',
    icon: 'Cloud',
    dataPoints: ['Posts', 'Profiles', 'Followers', 'Threads', 'Search', 'Media', 'Likes', 'Reposts'],
  },
  {
    id: 'facebook',
    name: 'Facebook',
    color: 'text-indigo-400',
    bgColor: 'bg-indigo-500/10 border-indigo-500/30',
    icon: 'Facebook',
    dataPoints: ['Public Pages', 'Groups', 'Posts', 'Comments', 'Engagement', 'Businesses', 'Marketplace', 'Ads'],
  },
  {
    id: 'instagram',
    name: 'Instagram',
    color: 'text-pink-400',
    bgColor: 'bg-pink-500/10 border-pink-500/30',
    icon: 'Instagram',
    dataPoints: ['Profiles', 'Posts', 'Reels', 'Followers', 'Bios', 'Comments', 'Hashtags', 'Engagement'],
  },
  // NEW FEATURE: Telegram MTProto & Channel Platform
  {
    id: 'telegram',
    name: 'Telegram',
    color: 'text-sky-400',
    bgColor: 'bg-sky-500/10 border-sky-500/30',
    icon: 'Send',
    dataPoints: ['Channels', 'Groups', 'Messages', 'Views', 'Reactions', 'Members', 'Links', 'Broadcasts'],
  },
];


export const features: FeatureItem[] = [
  { icon: 'Search', title: 'Multi-Platform Scraping', description: 'Scrape 9 core platforms from a single unified interface. Twitter/X, LinkedIn, Upwork, Fiverr, Reddit, Bluesky, Facebook, Instagram, and Telegram — all with structured, clean output.' },
  { icon: 'Calendar', title: 'Smart Scheduling', description: 'Set scrapers to run hourly, daily, or on custom cron intervals. Get alerts when jobs fail, automatic retries, and full run logs.' },
  { icon: 'Globe', title: 'Built-in Proxy Rotation', description: 'Smart proxy rotation across 50+ regions. Geo-target your scrapes, avoid blocks, and maintain 99.9% uptime with zero configuration.' },
  { icon: 'Database', title: 'Clean Structured Output', description: 'Get data in JSON, CSV, Excel, or via REST API. Every field is typed, validated, and ready to pipe into your analytics pipeline.' },
  { icon: 'BarChart3', title: 'Real-time Analytics', description: 'Track engagement metrics, sentiment analysis, and trend detection as data flows in. Visualize growth, reach, and influence in real time.' },
  { icon: 'Webhook', title: 'Webhooks & Integrations', description: 'Connect to 20+ services including Zapier, n8n, Airtable, Google Sheets, Slack, Discord, and webhooks. Automate your full workflow.' },
  { icon: 'Shield', title: 'Anti-Block Technology', description: 'Browser fingerprint rotation, CAPTCHA solving, rate-limit handling, and human-like behavior patterns baked in. Never get blocked.' },
  { icon: 'Code2', title: 'Developer-First API', description: 'Full REST API with SDKs for Python, JavaScript, and Go. Webhooks, pagination, and streaming support. MCP-compatible for AI agents.' },
];

export const faqs: FAQItem[] = [
  { question: 'Is it legal to scrape social media data?', answer: 'Scraping publicly available data is generally legal, but you should be aware of regulations like GDPR in the EU and CCPA in California. Always consult legal counsel for your specific use case, and avoid scraping personal data without a legitimate reason.' },
  { question: 'Do I need to log in to the platform to scrape?', answer: 'No. Most of our scrapers work with publicly available data and do not require login. For restricted or detailed content, we support authenticated sessions with cookie management for deeper access.' },
  { question: 'Can I scrape real-time data?', answer: 'Yes. Our scrapers support real-time and near-real-time data collection. Set up streaming webhooks to receive new posts, comments, or mentions as they appear on the platform.' },
  { question: 'How much data can I scrape?', answer: 'There is no hard limit. Our infrastructure scales horizontally — from 10 items to millions of records. Pricing is based on compute resources used, not data volume, making it cost-effective at any scale.' },
  { question: 'What formats can I export data in?', answer: 'Export scraped data as JSON, CSV, Excel (XLSX), or via our REST API with streaming support. You can also push data directly to integrations like Airtable, Google Sheets, or your own database.' },
  { question: 'How does proxy rotation work?', answer: 'We maintain a pool of residential and datacenter proxies across 50+ countries. Our system automatically rotates IPs, manages sessions, and handles retries — all transparently. You just select the geo-region you want.' },
  { question: 'Can I integrate this with my existing tools?', answer: 'Absolutely. We offer native integrations with Zapier, n8n, Make, Airtable, Google Sheets, Slack, Discord, GitHub, and more. Full REST API and webhooks let you connect to any system.' },
  { question: 'Is there a free tier?', answer: 'Yes. The free plan includes 1,000 scraped items per month, 1 scheduled task, and access to all platforms. No credit card required. Upgrade anytime as your needs grow.' },
];

export const jobs: ScraperJob[] = [
  { id: 'job_001', name: '@NASA Tweet Archive', platform: 'twitter', type: 'timeline', status: 'running', progress: 67, itemsScraped: 4823, totalItems: 7200, startedAt: '2026-10-07T08:30:00Z', completedAt: null, scheduled: true, owner: 'research-team', cost: 0, proxyRegion: 'US-East' },
  { id: 'job_002', name: '#AI Tech Hashtag Monitor', platform: 'twitter', type: 'hashtag', status: 'running', progress: 34, itemsScraped: 1203, totalItems: 3500, startedAt: '2026-10-07T09:15:00Z', completedAt: null, scheduled: false, owner: 'marketing', cost: 0, proxyRegion: 'US-West' },
  { id: 'job_003', name: 'NatGeo Profile Data', platform: 'instagram', type: 'profile', status: 'completed', progress: 100, itemsScraped: 894, totalItems: 894, startedAt: '2026-10-07T06:00:00Z', completedAt: '2026-10-07T06:22:00Z', scheduled: true, owner: 'analytics', cost: 0, proxyRegion: 'EU-West' },
  { id: 'job_004', name: 'Upwork AI Engineers', platform: 'upwork', type: 'search', status: 'queued', progress: 0, itemsScraped: 0, totalItems: 500, startedAt: '2026-10-07T10:00:00Z', completedAt: null, scheduled: false, owner: 'marketing', cost: 0, proxyRegion: 'US-East' },
  { id: 'job_005', name: 'Fiverr Web3 Specialists', platform: 'fiverr', type: 'search', status: 'completed', progress: 100, itemsScraped: 245, totalItems: 245, startedAt: '2026-10-06T14:30:00Z', completedAt: '2026-10-06T15:10:00Z', scheduled: true, owner: 'research-team', cost: 0, proxyRegion: 'US-East' },
  { id: 'job_006', name: 'r/MachineLearning Posts', platform: 'reddit', type: 'search', status: 'completed', progress: 100, itemsScraped: 3402, totalItems: 3402, startedAt: '2026-10-06T11:00:00Z', completedAt: '2026-10-06T11:18:00Z', scheduled: true, owner: 'analytics', cost: 0, proxyRegion: 'EU-West' },
  { id: 'job_007', name: '@elonmusk Follower List', platform: 'twitter', type: 'followers', status: 'failed', progress: 23, itemsScraped: 4500, totalItems: 80000, startedAt: '2026-10-06T09:00:00Z', completedAt: null, scheduled: false, owner: 'research-team', cost: 0, proxyRegion: 'US-East' },
  { id: 'job_008', name: 'LinkedIn Company Pages', platform: 'linkedin', type: 'profile', status: 'paused', progress: 55, itemsScraped: 234, totalItems: 400, startedAt: '2026-10-07T07:45:00Z', completedAt: null, scheduled: false, owner: 'sales', cost: 0, proxyRegion: 'US-West' },
  { id: 'job_009', name: 'BlueSky Trending Posts', platform: 'bluesky', type: 'search', status: 'completed', progress: 100, itemsScraped: 1850, totalItems: 1850, startedAt: '2026-10-07T05:00:00Z', completedAt: '2026-10-07T05:08:00Z', scheduled: true, owner: 'analytics', cost: 0, proxyRegion: 'US-East' },
  { id: 'job_010', name: 'Facebook Page Reviews', platform: 'facebook', type: 'media', status: 'running', progress: 88, itemsScraped: 1760, totalItems: 2000, startedAt: '2026-10-07T09:30:00Z', completedAt: null, scheduled: false, owner: 'marketing', cost: 0, proxyRegion: 'EU-West' },
];

const sentiments: Array<'positive' | 'neutral' | 'negative'> = ['positive', 'neutral', 'negative'];

function pickSentiment(): 'positive' | 'neutral' | 'negative' {
  return sentiments[Math.floor(Math.random() * 3)];
}

const sampleContents = [
  'Exploring the mysteries of deep space with new telescope data 🌌',
  'Just published our latest research on neural network architectures',
  'The future of AI is not about replacing humans but augmenting them',
  'Breaking: New exoplanet discovered in the habitable zone of a nearby star',
  'Thread: How transformer models changed NLP forever (1/10)',
  'Incredible footage of the aurora borealis from the ISS last night',
  'Our team just open-sourced a new scraping framework. Check it out!',
  'Data shows 300% increase in AI-related job postings this quarter',
  'Reminder: Web scraping ethics matter. Always respect robots.txt',
  'Just hit 1M followers! Thank you all for the incredible support',
  'New blog post: Building scalable data pipelines with zero infrastructure',
  'The intersection of quantum computing and machine learning is wild',
  'Hot take: Most companies dont need big data, they need clean data',
  'Excited to announce our partnership with leading research institutions',
  'How we reduced our scraping costs by 90% with smart proxy rotation',
  'Watch this amazing timelapse of the Milky Way from Death Valley',
  'Thread: 10 underrated Python libraries for data science (1/10)',
  'Our latest sentiment analysis model achieves 94% accuracy on social media',
  'The open web is the greatest dataset humanity has ever built',
  'Just shipped real-time streaming support for all scraper endpoints',
];

const usernames = ['NASA', 'NatGeo', 'elonmusk', 'OpenAI', 'lexfridman', 'MIT_CSAIL', 'DeepLearningAI', 'huggingface', 'vercel', 'github', 'stripe', 'AnthropicAI', 'GoogleAI', 'MetaAI', 'Microsoft', 'Tesla', 'SpaceX', 'ylecun', 'karpathy', 'sama'];
const displayNames = ['NASA', 'National Geographic', 'Elon Musk', 'OpenAI', 'Lex Fridman', 'MIT CSAIL', 'DeepLearningAI', 'Hugging Face', 'Vercel', 'GitHub', 'Stripe', 'Anthropic', 'Google AI', 'Meta AI', 'Microsoft', 'Tesla', 'SpaceX', 'Yann LeCun', 'Andrej Karpathy', 'Sam Altman'];
const locations = ['Washington, DC', 'Global', 'Austin, TX', 'San Francisco, CA', 'Boston, MA', 'Mountain View, CA', 'New York, NY', 'Remote', 'Menlo Park, CA', 'Redmond, WA', 'Palo Alto, CA', 'San Francisco, CA', 'Mountain View, CA', 'Menlo Park, CA', 'Redmond, WA', 'Austin, TX', 'Hawthorne, CA', 'New York, NY', 'San Francisco, CA', 'San Francisco, CA'];

function randomInt(min: number, max: number): number {
  return Math.floor(Math.random() * (max - min + 1)) + min;
}

function randomDate(daysBack: number): string {
  const date = new Date();
  date.setDate(date.getDate() - randomInt(0, daysBack));
  date.setHours(randomInt(0, 23), randomInt(0, 59), randomInt(0, 59));
  return date.toISOString();
}

export const scrapedItems: ScrapedItem[] = Array.from({ length: 80 }, (_, i) => {
  const idx = i % usernames.length;
  const isVerified = [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19].includes(idx) && Math.random() > 0.3;
  const supportedPlatforms: Platform[] = ['twitter', 'linkedin', 'upwork', 'fiverr', 'reddit', 'bluesky', 'facebook', 'instagram'];
  return {
    id: `item_${String(i + 1).padStart(4, '0')}`,
    platform: supportedPlatforms[i % supportedPlatforms.length],
    username: usernames[idx],
    displayName: displayNames[idx],
    url: `https://x.com/${usernames[idx]}/status/${randomInt(1000000000, 9999999999)}`,
    content: sampleContents[i % sampleContents.length],
    likes: randomInt(50, 500000),
    retweets: randomInt(10, 100000),
    replies: randomInt(5, 50000),
    views: randomInt(1000, 5000000),
    followers: randomInt(10000, 80000000),
    following: randomInt(50, 2000),
    isVerified,
    mediaCount: randomInt(0, 4),
    createdAt: randomDate(30),
    scrapedAt: randomDate(2),
    location: locations[idx],
    profilePicture: null,
    sentiment: pickSentiment(),
  };
});

export const scheduledTasks: ScheduledTask[] = [
  { id: 'sch_001', name: 'NASA Daily Timeline', platform: 'twitter', interval: 'daily', nextRun: '2026-10-08T08:00:00Z', lastRun: '2026-10-07T08:00:00Z', lastStatus: 'completed', enabled: true, itemsPerRun: 5000 },
  { id: 'sch_002', name: 'AI Hashtag Monitor', platform: 'twitter', interval: 'hourly', nextRun: '2026-10-07T11:00:00Z', lastRun: '2026-10-07T10:00:00Z', lastStatus: 'completed', enabled: true, itemsPerRun: 500 },
  { id: 'sch_003', name: 'LinkedIn Trending Weekly', platform: 'linkedin', interval: 'weekly', nextRun: '2026-10-14T00:00:00Z', lastRun: '2026-10-07T00:00:00Z', lastStatus: 'completed', enabled: true, itemsPerRun: 10000 },
  { id: 'sch_004', name: 'Reddit ML Posts', platform: 'reddit', interval: 'daily', nextRun: '2026-10-08T11:00:00Z', lastRun: '2026-10-07T11:00:00Z', lastStatus: 'completed', enabled: true, itemsPerRun: 2000 },
  { id: 'sch_005', name: 'Bluesky Intel Fetch', platform: 'bluesky', interval: 'daily', nextRun: '2026-10-08T14:30:00Z', lastRun: '2026-10-06T14:30:00Z', lastStatus: 'failed', enabled: false, itemsPerRun: 15000 },
  { id: 'sch_006', name: 'Instagram Profile Tracker', platform: 'instagram', interval: 'custom', nextRun: '2026-10-07T14:00:00Z', lastRun: '2026-10-07T06:00:00Z', lastStatus: 'completed', enabled: true, itemsPerRun: 1000 },
];

export const proxies: ProxyNode[] = [
  { id: 'px_01', region: 'US-East', countryCode: 'US', city: 'Ashburn', status: 'active', requests: 45230, successRate: 99.8, avgLatency: 45 },
  { id: 'px_02', region: 'US-West', countryCode: 'US', city: 'Los Angeles', status: 'active', requests: 32100, successRate: 99.5, avgLatency: 62 },
  { id: 'px_03', region: 'EU-West', countryCode: 'DE', city: 'Frankfurt', status: 'active', requests: 28700, successRate: 99.9, avgLatency: 38 },
  { id: 'px_04', region: 'EU-North', countryCode: 'SE', city: 'Stockholm', status: 'idle', requests: 5400, successRate: 99.2, avgLatency: 55 },
  { id: 'px_05', region: 'Asia-Pacific', countryCode: 'JP', city: 'Tokyo', status: 'active', requests: 19200, successRate: 98.7, avgLatency: 89 },
  { id: 'px_06', region: 'Asia-South', countryCode: 'IN', city: 'Mumbai', status: 'active', requests: 8800, successRate: 97.5, avgLatency: 120 },
  { id: 'px_07', region: 'South America', countryCode: 'BR', city: 'São Paulo', status: 'idle', requests: 3200, successRate: 98.1, avgLatency: 95 },
  { id: 'px_08', region: 'Oceania', countryCode: 'AU', city: 'Sydney', status: 'active', requests: 6700, successRate: 99.0, avgLatency: 110 },
  { id: 'px_09', region: 'UK', countryCode: 'GB', city: 'London', status: 'active', requests: 15400, successRate: 99.6, avgLatency: 42 },
  { id: 'px_10', region: 'Canada', countryCode: 'CA', city: 'Toronto', status: 'error', requests: 2100, successRate: 85.2, avgLatency: 78 },
];

export const integrations: Integration[] = [
  { id: 'int_01', name: 'Zapier', icon: 'Zap', category: 'Automation', connected: true, description: 'Connect scraper runs to 5,000+ apps' },
  { id: 'int_02', name: 'n8n', icon: 'Workflow', category: 'Automation', connected: true, description: 'Self-hosted workflow automation' },
  { id: 'int_03', name: 'Make.com', icon: 'LayoutGrid', category: 'Automation', connected: false, description: 'Visual workflow builder' },
  { id: 'int_04', name: 'Airtable', icon: 'Table', category: 'Storage', connected: true, description: 'Send data to Airtable bases' },
  { id: 'int_05', name: 'Google Sheets', icon: 'Sheet', category: 'Storage', connected: false, description: 'Export to Google Sheets' },
  { id: 'int_06', name: 'Slack', icon: 'MessageSquare', category: 'Notifications', connected: true, description: 'Get alerts in Slack channels' },
  { id: 'int_07', name: 'Discord', icon: 'Gamepad2', category: 'Notifications', connected: false, description: 'Webhook notifications to Discord' },
  { id: 'int_08', name: 'GitHub', icon: 'Github', category: 'Developer', connected: true, description: 'Commit scraped data to repos' },
  { id: 'int_09', name: 'Webhooks', icon: 'Webhook', category: 'Developer', connected: true, description: 'Custom HTTP callbacks on events' },
  { id: 'int_10', name: 'REST API', icon: 'Code2', category: 'Developer', connected: true, description: 'Full programmatic access' },
  { id: 'int_11', name: 'Keboola', icon: 'Database', category: 'Data Platform', connected: false, description: 'Data pipeline integration' },
  { id: 'int_12', name: 'Google Drive', icon: 'HardDrive', category: 'Storage', connected: false, description: 'Auto-export to Drive' },
];

export const stats = {
  totalJobs: 1847,
  activeJobs: 3,
  itemsScraped: 4823000,
  platformsConnected: 8,
  successRate: 99.2,
  monthlyCost: 0,
  computeUsed: 24.6,
  computeLimit: 999,
  storageUsed: 12.3,
  storageLimit: 999,
};

export const trendData = [
  { day: 'Mon', value: 320 },
  { day: 'Tue', value: 450 },
  { day: 'Wed', value: 380 },
  { day: 'Thu', value: 520 },
  { day: 'Fri', value: 610 },
  { day: 'Sat', value: 490 },
  { day: 'Sun', value: 580 },
];
