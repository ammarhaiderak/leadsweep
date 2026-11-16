import type { Platform, JobStatus } from '@/types';
import {
  Twitter,
  Instagram,
  Facebook,
  Linkedin,
  MessageCircle,
  Cloud,
  Briefcase,
  Layers,
  Send, // NEW FEATURE: Telegram icon
} from 'lucide-react';

const platformIcons: Record<Platform, typeof Twitter> = {
  twitter: Twitter,
  linkedin: Linkedin,
  upwork: Briefcase,
  fiverr: Layers,
  instagram: Instagram,
  facebook: Facebook,
  reddit: MessageCircle,
  bluesky: Cloud,
  telegram: Send, // NEW FEATURE: Telegram icon mapping
};


export function PlatformIcon({ platform, className = '' }: { platform: Platform | string; className?: string }) {
  const platKey = (platform || 'twitter').toLowerCase() as Platform;
  const Icon = platformIcons[platKey] || Twitter;
  return <Icon className={className} />;
}

const statusConfig: Record<JobStatus, { label: string; color: string; dot: string }> = {
  running: { label: 'Running', color: 'text-emerald-400 bg-emerald-500/10 border-emerald-500/30', dot: 'bg-emerald-400 animate-pulse' },
  completed: { label: 'Completed', color: 'text-sky-400 bg-sky-500/10 border-sky-500/30', dot: 'bg-sky-400' },
  queued: { label: 'Queued', color: 'text-amber-400 bg-amber-500/10 border-amber-500/30', dot: 'bg-amber-400' },
  failed: { label: 'Failed', color: 'text-red-400 bg-red-500/10 border-red-500/30', dot: 'bg-red-400' },
  paused: { label: 'Paused', color: 'text-gray-400 bg-gray-500/10 border-gray-500/30', dot: 'bg-gray-400' },
  partial: { label: 'Partial', color: 'text-amber-400 bg-amber-500/10 border-amber-500/30', dot: 'bg-amber-400' },
  cancelled: { label: 'Cancelled', color: 'text-zinc-400 bg-zinc-500/10 border-zinc-500/30', dot: 'bg-zinc-400' },
};

export function StatusBadge({ status }: { status: JobStatus }) {
  const config = statusConfig[status] || statusConfig.failed;
  return (
    <span className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium border ${config.color}`}>
      <span className={`w-1.5 h-1.5 rounded-full ${config.dot}`} />
      {config.label}
    </span>
  );
}

export function formatNumber(n: number): string {
  if (n >= 1_000_000) return (n / 1_000_000).toFixed(1).replace('.0', '') + 'M';
  if (n >= 1_000) return (n / 1_000).toFixed(1).replace('.0', '') + 'K';
  return n.toString();
}

export function formatDate(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
}

export function timeAgo(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  return `${days}d ago`;
}
