import { useState } from 'react';
import { Copy, Check, Code2, Terminal, Key, Webhook, Book } from 'lucide-react';

const apiKey = 'YOUR_API_KEY';
const sampleCode = `import { LeadSweep } from 'leadsweep';

const client = new LeadSweep({
  apiKey: '${apiKey}',
});

// Scrape tweets from a user timeline
const results = await client.scrape({
  platform: 'twitter',
  type: 'timeline',
  query: 'NASA',
  maxItems: 1000,
  options: {
    includeReplies: false,
    includeMedia: true,
    sentimentAnalysis: true,
    proxyRegion: 'auto',
  },
});

console.log(results.items);
// Output: Array of typed tweet objects`;

const endpoints = [
  { method: 'POST', path: '/v1/scrape', desc: 'Start a new scraping job' },
  { method: 'GET', path: '/v1/jobs/:id', desc: 'Get job status and progress' },
  { method: 'GET', path: '/v1/jobs', desc: 'List all jobs' },
  { method: 'GET', path: '/v1/data/:jobId', desc: 'Get scraped data from a job' },
  { method: 'POST', path: '/v1/schedules', desc: 'Create a scheduled task' },
  { method: 'GET', path: '/v1/platforms', desc: 'List supported platforms' },
  { method: 'POST', path: '/v1/webhooks', desc: 'Register a webhook endpoint' },
  { method: 'GET', path: '/v1/proxies', desc: 'List proxy regions and status' },
];

export function ApiPage() {
  const [copied, setCopied] = useState(false);
  const [tab, setTab] = useState<'docs' | 'keys' | 'webhooks'>('docs');

  const copyKey = () => {
    navigator.clipboard?.writeText(apiKey);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div className="p-4 lg:p-6 space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-white">API Access</h1>
        <p className="text-sm text-gray-400 mt-1">Full REST API with SDKs for Python, JavaScript, and Go</p>
      </div>

      {/* Tabs */}
      <div className="flex items-center gap-2 border-b border-gray-800">
        {[
          { id: 'docs' as const, label: 'Documentation', icon: Book },
          { id: 'keys' as const, label: 'API Keys', icon: Key },
          { id: 'webhooks' as const, label: 'Webhooks', icon: Webhook },
        ].map((t) => {
          const Icon = t.icon;
          return (
            <button
              key={t.id}
              onClick={() => setTab(t.id)}
              className={`flex items-center gap-2 px-4 py-2.5 text-sm font-medium transition-colors border-b-2 -mb-px ${
                tab === t.id ? 'text-emerald-400 border-emerald-400' : 'text-gray-400 hover:text-white border-transparent'
              }`}
            >
              <Icon size={16} /> {t.label}
            </button>
          );
        })}
      </div>

      {tab === 'docs' && (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          {/* Code sample */}
          <div className="bg-gray-950 border border-gray-800 rounded-2xl overflow-hidden">
            <div className="flex items-center gap-2 px-4 py-3 border-b border-gray-800 bg-gray-900/50">
              <Terminal size={14} className="text-emerald-400" />
              <span className="text-xs text-gray-400 font-mono">scraper.ts</span>
            </div>
            <pre className="p-4 text-xs font-mono text-gray-300 overflow-x-auto leading-relaxed">
{sampleCode}
            </pre>
          </div>

          {/* Endpoints */}
          <div className="bg-gray-900 border border-gray-800 rounded-2xl p-6">
            <h2 className="text-base font-bold text-white flex items-center gap-2 mb-5">
              <Code2 size={18} className="text-cyan-400" /> REST API Endpoints
            </h2>
            <div className="space-y-2">
              {endpoints.map((ep) => (
                <div key={ep.path} className="flex items-center gap-3 p-3 rounded-xl bg-gray-950/50 hover:bg-gray-800/40 transition-colors">
                  <span className={`text-xs font-bold px-2 py-1 rounded-md font-mono ${
                    ep.method === 'GET' ? 'bg-sky-500/20 text-sky-400' : 'bg-emerald-500/20 text-emerald-400'
                  }`}>
                    {ep.method}
                  </span>
                  <code className="text-sm text-white font-mono flex-1">{ep.path}</code>
                  <span className="text-xs text-gray-500 hidden sm:block">{ep.desc}</span>
                </div>
              ))}
            </div>
            <div className="mt-5 p-4 bg-gradient-to-br from-emerald-500/10 to-cyan-500/5 border border-emerald-500/20 rounded-xl">
              <p className="text-sm text-gray-300">
                Base URL: <code className="text-emerald-400 font-mono">https://api.leadsweep.io/v1</code>
              </p>
              <p className="text-xs text-gray-500 mt-1">All requests require an API key in the Authorization header.</p>
            </div>
          </div>
        </div>
      )}

      {tab === 'keys' && (
        <div className="max-w-2xl space-y-6">
          <div className="bg-gray-900 border border-gray-800 rounded-2xl p-6">
            <h2 className="text-base font-bold text-white mb-2">Your API Key</h2>
            <p className="text-sm text-gray-400 mb-4">Use this key to authenticate all API requests. Keep it secret.</p>
            <div className="flex items-center gap-3 bg-gray-950 border border-gray-800 rounded-xl p-4">
              <Key size={16} className="text-emerald-400 flex-shrink-0" />
              <code className="text-sm text-white font-mono flex-1 truncate">{apiKey}</code>
              <button
                onClick={copyKey}
                className="flex items-center gap-1.5 text-xs font-medium text-gray-300 hover:text-white bg-gray-800 hover:bg-gray-700 px-3 py-2 rounded-lg transition-colors flex-shrink-0"
              >
                {copied ? <><Check size={14} className="text-emerald-400" /> Copied</> : <><Copy size={14} /> Copy</>}
              </button>
            </div>
          </div>

          <div className="bg-gray-900 border border-gray-800 rounded-2xl p-6">
            <h2 className="text-base font-bold text-white mb-4">Usage This Month</h2>
            <div className="grid grid-cols-3 gap-4">
              {[
                { label: 'API Calls', value: '12,430', limit: 'Unlimited' },
                { label: 'Items Scraped', value: '4,823', limit: '1,000 free' },
                { label: 'Rate Limit', value: '100/min', limit: 'Current' },
              ].map((s) => (
                <div key={s.label} className="text-center p-4 bg-gray-950/50 rounded-xl border border-gray-800">
                  <p className="text-lg font-bold text-white">{s.value}</p>
                  <p className="text-xs text-gray-400 mt-1">{s.label}</p>
                  <p className="text-xs text-emerald-400 mt-0.5">{s.limit}</p>
                </div>
              ))}
            </div>
          </div>

          <button className="flex items-center gap-2 bg-gray-800 hover:bg-gray-700 text-white px-4 py-2.5 rounded-xl font-medium text-sm transition-colors">
            <Key size={16} /> Generate New Key
          </button>
        </div>
      )}

      {tab === 'webhooks' && (
        <div className="max-w-2xl space-y-6">
          <div className="bg-gray-900 border border-gray-800 rounded-2xl p-6">
            <h2 className="text-base font-bold text-white mb-2">Webhook Endpoints</h2>
            <p className="text-sm text-gray-400 mb-4">Receive real-time notifications when jobs complete, fail, or reach milestones.</p>

            <div className="space-y-3">
              {[
                { url: 'https://hooks.myapp.com/leadsweep/job-complete', events: ['job.completed', 'job.failed'], status: 'active' },
                { url: 'https://api.myapp.com/v2/data-ingest', events: ['data.new', 'data.exported'], status: 'active' },
              ].map((hook, i) => (
                <div key={i} className="p-4 bg-gray-950/50 border border-gray-800 rounded-xl">
                  <div className="flex items-center justify-between mb-2">
                    <code className="text-sm text-white font-mono truncate flex-1">{hook.url}</code>
                    <span className="flex items-center gap-1 text-xs text-emerald-400 font-medium ml-3 flex-shrink-0">
                      <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse" /> Active
                    </span>
                  </div>
                  <div className="flex items-center gap-2 flex-wrap">
                    {hook.events.map((e) => (
                      <span key={e} className="text-xs px-2 py-1 rounded-md bg-gray-800 text-gray-300 font-mono">{e}</span>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          </div>

          <button className="flex items-center gap-2 bg-gradient-to-r from-emerald-500 to-cyan-500 hover:from-emerald-400 hover:to-cyan-400 text-white px-4 py-2.5 rounded-xl font-semibold text-sm transition-all shadow-lg shadow-emerald-500/20">
            <Webhook size={16} /> Add Webhook
          </button>
        </div>
      )}
    </div>
  );
}
