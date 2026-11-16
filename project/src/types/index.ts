export type Platform =
  | 'twitter'
  | 'linkedin'
  | 'upwork'
  | 'fiverr'
  | 'instagram'
  | 'facebook'
  | 'reddit'
  | 'bluesky'
  | 'telegram'; // NEW FEATURE: Telegram MTProto Platform


export type JobStatus = 'running' | 'completed' | 'queued' | 'failed' | 'paused' | 'partial' | 'cancelled';
// UPDATED LOGIC: Expanded ScraperType union with Telegram specific types
export type ScraperType =
  | 'profile'
  | 'search'
  | 'hashtag'
  | 'timeline'
  | 'replies'
  | 'followers'
  | 'media'
  | 'lists'
  | 'channel_messages' // NEW FEATURE: Telegram Channel/Group messages
  | 'keyword_search'   // NEW FEATURE: Telegram Keyword search
  | 'group_members'    // NEW FEATURE: Telegram Group members
  | 'channel_info'     // NEW FEATURE: Telegram Channel info
  | 'subreddit_posts'  // NEW FEATURE: Reddit subreddit discovery
  | 'intent_search'   // NEW FEATURE: Reddit commercial-intent discovery
  | 'user_tweets';

export type ExportFormat = 'json' | 'csv' | 'excel' | 'api';

export interface ScraperJob {
  id: string;
  name: string;
  platform: Platform;
  type: ScraperType;
  status: JobStatus;
  error?: string;
  progress: number;
  itemsScraped: number;
  totalItems: number | null;
  startedAt: string;
  completedAt: string | null;
  scheduled: boolean;
  owner: string;
  cost: number;
  proxyRegion: string;
}

export interface ScrapedItem {
  id: string;
  platform: Platform;
  username: string;
  displayName: string;
  url: string;
  content: string;
  likes: number;
  retweets: number;
  replies: number;
  views: number;
  followers: number;
  following: number;
  isVerified: boolean;
  mediaCount: number;
  createdAt: string;
  scrapedAt: string;
  location: string | null;
  profilePicture: string | null;
  sentiment: 'positive' | 'neutral' | 'negative' | null;
  leadScore?: number;
  leadBadge?: string;
  isLead?: boolean;
  leadReason?: string;
  leadAction?: string;
  leadCategory?: string;
  evidenceSpans?: string[];
  // NEW FEATURE: Telegram specific message metadata fields
  channel?: string;
  // NEW FEATURE: Reddit specific metadata fields
  subreddit?: string;
  title?: string;
  source_mode?: string;
  source_provider?: string;
  senderId?: string | number;
  senderUsername?: string;
  forwards?: number;
  reactions?: number;
  mediaType?: string;
}


export interface ScheduledTask {
  id: string;
  name: string;
  platform: Platform;
  interval: 'hourly' | 'daily' | 'weekly' | 'custom';
  nextRun: string;
  lastRun: string | null;
  lastStatus: JobStatus;
  enabled: boolean;
  itemsPerRun: number;
}

export interface ProxyNode {
  id: string;
  region: string;
  countryCode: string;
  city: string;
  status: 'active' | 'idle' | 'error';
  requests: number;
  successRate: number;
  avgLatency: number;
}

export interface Integration {
  id: string;
  name: string;
  icon: string;
  category: string;
  connected: boolean;
  description: string;
}

export interface FAQItem {
  question: string;
  answer: string;
}

export interface FeatureItem {
  icon: string;
  title: string;
  description: string;
}

export interface PlatformInfo {
  id: Platform;
  name: string;
  color: string;
  bgColor: string;
  dataPoints: string[];
  icon: string;
}
