import { useState } from 'react';
import {
  Zap, Workflow, LayoutGrid, Table, Sheet, MessageSquare,
  Gamepad2, Github, Webhook, Code2, Database, HardDrive,
  Check, Plus, Search,
} from 'lucide-react';
import { integrations } from '@/data/mockData';

const iconMap: Record<string, typeof Zap> = {
  Zap, Workflow, LayoutGrid, Table, Sheet, MessageSquare, Gamepad2, Github, Webhook, Code2, Database, HardDrive,
};

export function IntegrationsPage() {
  const [items, setItems] = useState(integrations);
  const [search, setSearch] = useState('');
  const [category, setCategory] = useState('all');

  const categories = ['all', ...Array.from(new Set(integrations.map((i) => i.category)))];

  const filtered = items.filter((i) => {
    const matchesSearch = i.name.toLowerCase().includes(search.toLowerCase()) || i.description.toLowerCase().includes(search.toLowerCase());
    const matchesCategory = category === 'all' || i.category === category;
    return matchesSearch && matchesCategory;
  });

  const toggleConnected = (id: string) => {
    setItems(items.map((i) => (i.id === id ? { ...i, connected: !i.connected } : i)));
  };

  const connectedCount = items.filter((i) => i.connected).length;

  return (
    <div className="p-4 lg:p-6 space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-white">Integrations</h1>
        <p className="text-sm text-gray-400 mt-1">{connectedCount} connected · {items.length} available</p>
      </div>

      {/* Search and filter */}
      <div className="flex flex-col lg:flex-row items-stretch lg:items-center gap-3">
        <div className="flex items-center gap-2 bg-gray-900 border border-gray-800 rounded-lg px-3 py-2.5 flex-1">
          <Search size={16} className="text-gray-500" />
          <input
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search integrations..."
            className="bg-transparent text-sm text-white placeholder-gray-500 outline-none flex-1"
          />
        </div>
        <div className="flex items-center gap-2 overflow-x-auto pb-1">
          {categories.map((cat) => (
            <button
              key={cat}
              onClick={() => setCategory(cat)}
              className={`px-3 py-2 rounded-lg text-sm font-medium whitespace-nowrap transition-all ${
                category === cat
                  ? 'bg-gray-800 text-white border border-gray-700'
                  : 'text-gray-400 hover:text-white hover:bg-gray-800/50'
              }`}
            >
              {cat === 'all' ? 'All' : cat}
            </button>
          ))}
        </div>
      </div>

      {/* Integration cards */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
        {filtered.map((integration) => {
          const Icon = iconMap[integration.icon] || Zap;
          return (
            <div
              key={integration.id}
              className="bg-gray-900 border border-gray-800 rounded-2xl p-5 hover:border-gray-700 transition-colors"
            >
              <div className="flex items-start justify-between mb-4">
                <div className="w-11 h-11 rounded-xl bg-gradient-to-br from-gray-800 to-gray-700 border border-gray-700 flex items-center justify-center">
                  <Icon className="w-5 h-5 text-white" />
                </div>
                {integration.connected && (
                  <span className="flex items-center gap-1 text-xs text-emerald-400 font-medium">
                    <Check size={12} /> Connected
                  </span>
                )}
              </div>
              <h3 className="text-base font-bold text-white mb-1">{integration.name}</h3>
              <p className="text-xs text-gray-500 mb-1">{integration.category}</p>
              <p className="text-sm text-gray-400 mb-4 leading-relaxed">{integration.description}</p>
              <button
                onClick={() => toggleConnected(integration.id)}
                className={`w-full py-2.5 rounded-xl text-sm font-semibold transition-all ${
                  integration.connected
                    ? 'bg-gray-800 text-gray-400 hover:bg-gray-700 hover:text-white'
                    : 'bg-gradient-to-r from-emerald-500 to-cyan-500 hover:from-emerald-400 hover:to-cyan-400 text-white shadow-lg shadow-emerald-500/20'
                }`}
              >
                {integration.connected ? 'Disconnect' : (
                  <span className="flex items-center justify-center gap-1.5"><Plus size={14} /> Connect</span>
                )}
              </button>
            </div>
          );
        })}
      </div>
    </div>
  );
}
