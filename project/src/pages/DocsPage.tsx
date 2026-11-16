import { BookOpen, Terminal, Shield, Zap, Search, Layers, Sparkles } from 'lucide-react';
import type { PageId } from '@/App';

export function DocsPage({
  onNavigate,
}: {
  onNavigate: (page: PageId) => void;
  user?: any;
}) {
  return (
    <div className="space-y-8">
      <div className="p-4 lg:p-8 max-w-5xl mx-auto space-y-10">
        {/* Header */}
        <div className="space-y-3">
          <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full border border-emerald-500/30 bg-emerald-500/10 text-emerald-400 text-xs font-semibold">
            <BookOpen size={14} /> Official Documentation & User Guide
          </div>
          <h1 className="text-3xl font-bold text-white tracking-tight">
            How to Use LeadSweep & System Architecture
          </h1>
          <p className="text-gray-400 text-sm max-w-3xl leading-relaxed">
            Welcome to the comprehensive in-depth guide for LeadSweep. Learn how to harvest leads,
            extract social intelligence, perform $0-cost contact enrichment, and automate data collection.
          </p>
        </div>

      {/* 3 Steps Quick Start */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-5">
        <div className="p-6 bg-gray-900/80 border border-gray-800 rounded-2xl space-y-3">
          <div className="w-10 h-10 rounded-xl bg-emerald-500/10 border border-emerald-500/20 flex items-center justify-center text-emerald-400 font-bold">
            1
          </div>
          <h3 className="text-base font-semibold text-white">Create a Scraper Job</h3>
          <p className="text-xs text-gray-400 leading-relaxed">
            Navigate to <strong>New Scraper</strong>, choose your target platform (Twitter/X, LinkedIn, Reddit, etc.),
            select the extraction type (Search, Profile, Timeline), and input your keyword or query.
          </p>
        </div>

        <div className="p-6 bg-gray-900/80 border border-gray-800 rounded-2xl space-y-3">
          <div className="w-10 h-10 rounded-xl bg-cyan-500/10 border border-emerald-500/20 flex items-center justify-center text-cyan-400 font-bold">
            2
          </div>
          <h3 className="text-base font-semibold text-white">Monitor in Real-Time</h3>
          <p className="text-xs text-gray-400 leading-relaxed">
            Head to the <strong>Jobs</strong> dashboard. Watch the progress bar advance as posts and profiles are harvested
            and saved to your local high-performance SQLite database.
          </p>
        </div>

        <div className="p-6 bg-gray-900/80 border border-gray-800 rounded-2xl space-y-3">
          <div className="w-10 h-10 rounded-xl bg-sky-500/10 border border-emerald-500/20 flex items-center justify-center text-sky-400 font-bold">
            3
          </div>
          <h3 className="text-base font-semibold text-white">View & Download Leads</h3>
          <p className="text-xs text-gray-400 leading-relaxed">
            Click the <strong>3-dots (...)</strong> menu on any job to view leads directly in the web app or click download to export only that job's verified leads in clean CSV format.
          </p>
        </div>
      </div>

      {/* Architecture Deep Dive */}
      <div className="p-6 lg:p-8 bg-gray-900/60 border border-gray-800 rounded-3xl space-y-6">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-emerald-400/20 to-cyan-500/20 border border-emerald-500/30 flex items-center justify-center text-emerald-400">
            <Layers size={20} />
          </div>
          <div>
            <h2 className="text-xl font-bold text-white">Recommended $0 Architecture (Under the Hood)</h2>
            <p className="text-xs text-gray-400">Zero paid APIs, zero subscriptions, extreme speed & reliability</p>
          </div>
        </div>

        <div className="space-y-4 text-xs sm:text-sm text-gray-300 leading-relaxed">
          <div className="p-4 bg-gray-950/80 border border-gray-800/80 rounded-xl space-y-1">
            <h4 className="font-semibold text-emerald-400 flex items-center gap-2">
              <Zap size={14} /> 1. Data Collection Engine (Fastest Response, Zero Crash Risk)
            </h4>
            <p className="text-gray-400 text-xs">
              Unlike unstable Chromium-only scrapers, our engine uses pure HTTP sessions with session-cookie authentication.
              This guarantees instantaneous page responses, zero memory leaks, and 100% resistance to browser crashes.
            </p>
          </div>

          <div className="p-4 bg-gray-950/80 border border-gray-800/80 rounded-xl space-y-1">
            <h4 className="font-semibold text-cyan-400 flex items-center gap-2">
              <Search size={14} /> 2. OSINT Contact Enrichment (httpx + selectolax)
            </h4>
            <p className="text-gray-400 text-xs">
              Extracts websites, verified contact emails, LinkedIn URLs, and phone numbers from public profiles and company pages
              using ultra-fast native C parsers (<code className="text-gray-200">selectolax</code>) and async HTTP (<code className="text-gray-200">httpx</code>).
            </p>
          </div>

          <div className="p-4 bg-gray-950/80 border border-gray-800/80 rounded-xl space-y-1">
            <h4 className="font-semibold text-purple-400 flex items-center gap-2">
              <Shield size={14} /> 3. Controlled Fallback (Playwright)
            </h4>
            <p className="text-gray-400 text-xs">
              Playwright is invoked strictly as a controlled fallback only when heavy client-side JavaScript rendering or dynamic SPA hydration is detected.
            </p>
          </div>
        </div>
      </div>

      {/* Admin vs User Mode Explained */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        <div className="p-6 bg-gray-900 border border-gray-800 rounded-2xl space-y-3">
          <h3 className="text-base font-bold text-white flex items-center gap-2">
            <Shield size={16} className="text-emerald-400" /> Admin Mode
          </h3>
          <p className="text-xs text-gray-400 leading-relaxed">
            Accessed by authenticating with your system administrator credentials. Provides full management of:
          </p>
          <ul className="text-xs text-gray-300 space-y-1.5 list-disc list-inside">
            <li>Live Analytics and Performance Dashboard</li>
            <li>Proxy Network Management & auto-rotation</li>
            <li>Webhook and Third-Party Integrations</li>
            <li>System Configuration & Credentials Store</li>
          </ul>
        </div>

        <div className="p-6 bg-gray-900 border border-gray-800 rounded-2xl space-y-3">
          <h3 className="text-base font-bold text-white flex items-center gap-2">
            <Sparkles size={16} className="text-cyan-400" /> User Mode
          </h3>
          <p className="text-xs text-gray-400 leading-relaxed">
            Designed for focused, streamlined operation. Users added by the owner can sign in to:
          </p>
          <ul className="text-xs text-gray-300 space-y-1.5 list-disc list-inside">
            <li>Launch new search and profile scrapers</li>
            <li>Track live jobs and progress in real-time</li>
            <li>Filter and browse data in the Data Explorer</li>
            <li>Download targeted leads directly to CSV and JSON</li>
          </ul>
        </div>
      </div>

      {/* Production Architecture */}
      <div className="p-6 bg-gray-950 border border-gray-800 rounded-2xl space-y-4">
        <h3 className="text-sm font-bold text-white flex items-center gap-2">
          <Terminal size={16} className="text-emerald-400" /> Production System Architecture & Compliance
        </h3>
        <p className="text-xs text-gray-400 leading-relaxed">
          LeadSweep operates as a self-hosted, multi-platform intelligence pipeline with dedicated platform adapters (X/Twitter, LinkedIn, Upwork, Fiverr), strict deterministic relevance filters, and automated persistent scheduling.
        </p>
      </div>

        {/* Action Footer */}
        <div className="flex items-center justify-between pt-6 border-t border-gray-800">
          <button
            onClick={() => onNavigate('dashboard')}
            className="text-xs text-gray-400 hover:text-white transition-colors cursor-pointer"
          >
            ← Return to Dashboard
          </button>
          <button
            onClick={() => onNavigate('create')}
            className="flex items-center gap-2 bg-gradient-to-r from-emerald-500 to-cyan-500 hover:from-emerald-400 hover:to-cyan-400 px-5 py-2.5 rounded-xl font-semibold text-xs text-white transition-all shadow-lg shadow-emerald-500/20 cursor-pointer"
          >
            Launch a Scraper Now
          </button>
        </div>
      </div>
    </div>
  );
}
