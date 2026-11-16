import React from 'react';
import { X, Check, Zap, Sparkles, Shield, ArrowRight } from 'lucide-react';

interface UpgradeSubscriptionModalProps {
  isOpen: boolean;
  onClose: () => void;
  userEmail?: string;
  onUpgradeSuccess?: () => void;
}

export function UpgradeSubscriptionModal({
  isOpen,
  onClose,
  userEmail,
  onUpgradeSuccess,
}: UpgradeSubscriptionModalProps) {
  if (!isOpen) return null;

  const plans = [
    {
      id: 'pro',
      name: 'Pro Scraper',
      badge: 'Most Popular',
      price: '$49',
      period: '/month',
      desc: 'Ideal for growth teams and active lead generation workflows.',
      limits: '25,000 items / month',
      features: [
        'Up to 2,500 items per single scraping job',
        'Multi-query keyword splitting & parallel execution',
        'Full sentiment & ICP lead scoring with LLM',
        'Direct CSV, JSON, and Webhook exports',
        'Auto-rotating premium proxies (US, EU, Global)',
        'Priority execution queue',
      ],
      cta: 'Upgrade to Pro Plan',
      primary: true,
    },
    {
      id: 'enterprise',
      name: 'Enterprise Scale',
      badge: 'Unlimited Power',
      price: '$199',
      period: '/month',
      desc: 'High-volume social intelligence with dedicated infrastructure.',
      limits: 'Unlimited extractions',
      features: [
        'Unlimited items per job & lifetime scraping',
        'Dedicated scraping nodes & ultra-fast throughput',
        'Custom LangGraph evaluation filters',
        'Custom webhooks, Zapier, & CRM direct push',
        '24/7 dedicated support & SLA guarantee',
        'Custom scheduled cron jobs & monitors',
      ],
      cta: 'Get Enterprise Plan',
      primary: false,
    },
  ];

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-3 sm:p-5 bg-black/80 backdrop-blur-md animate-in fade-in duration-200 overflow-y-auto">
      <div 
        className="relative w-full max-w-3xl max-h-[92vh] flex flex-col bg-gray-950 border border-gray-800 rounded-2xl sm:rounded-3xl shadow-2xl overflow-hidden my-auto"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Glow Effects */}
        <div className="absolute top-0 left-1/4 w-72 h-72 bg-emerald-500/10 rounded-full blur-3xl pointer-events-none" />
        <div className="absolute bottom-0 right-1/4 w-72 h-72 bg-cyan-500/10 rounded-full blur-3xl pointer-events-none" />

        {/* Close Button */}
        <button
          onClick={onClose}
          className="absolute top-3.5 right-3.5 sm:top-4 sm:right-4 z-20 p-1.5 sm:p-2 text-gray-400 hover:text-white rounded-xl bg-gray-900/60 hover:bg-gray-800 border border-gray-800/80 transition-colors"
          title="Close"
        >
          <X size={18} />
        </button>

        {/* Scrollable Content Container */}
        <div className="p-4 sm:p-6 overflow-y-auto custom-scrollbar space-y-5 sm:space-y-6">
          {/* Header */}
          <div className="text-center max-w-xl mx-auto pt-1 sm:pt-2">
            <div className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full bg-emerald-500/10 border border-emerald-500/30 text-emerald-400 text-[11px] font-semibold uppercase tracking-wider mb-2">
              <Sparkles size={13} /> Free Trial Limit Reached
            </div>
            <h2 className="text-xl sm:text-2xl font-bold text-white tracking-tight">
              You've Used All 10 Free Credits
            </h2>
            <p className="text-xs sm:text-sm text-gray-400 mt-1.5 leading-relaxed">
              Your 10-item free trial has completed. To launch new scraping jobs, extract high-intent leads, and unlock continuous real-time scraping, please upgrade your subscription.
            </p>
            {userEmail && (
              <p className="text-[11px] text-gray-500 mt-1 font-mono">
                Account: {userEmail}
              </p>
            )}
          </div>

          {/* Plan Cards */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4 relative z-10">
            {plans.map((p) => (
              <div
                key={p.id}
                className={`flex flex-col justify-between p-4 sm:p-5 rounded-2xl border transition-all ${
                  p.primary
                    ? 'bg-gradient-to-b from-gray-900 via-gray-900 to-emerald-950/20 border-emerald-500/40 shadow-lg shadow-emerald-500/10 ring-1 ring-emerald-500/30'
                    : 'bg-gray-900/60 border-gray-800 hover:border-gray-700'
                }`}
              >
                <div>
                  <div className="flex items-center justify-between mb-1.5">
                    <h3 className="text-base sm:text-lg font-bold text-white">{p.name}</h3>
                    <span
                      className={`text-[10px] sm:text-xs font-bold px-2 py-0.5 rounded-full ${
                        p.primary
                          ? 'bg-emerald-500/20 text-emerald-300 border border-emerald-500/30'
                          : 'bg-gray-800 text-gray-300 border border-gray-700'
                      }`}
                    >
                      {p.badge}
                    </span>
                  </div>
                  <p className="text-xs text-gray-400 mb-3">{p.desc}</p>

                  <div className="flex items-baseline gap-1 mb-3 pb-3 border-b border-gray-800/80">
                    <span className="text-2xl sm:text-3xl font-extrabold text-white">{p.price}</span>
                    <span className="text-xs text-gray-400">{p.period}</span>
                    <span className="ml-auto text-[11px] font-mono font-medium text-emerald-400 bg-emerald-500/10 px-2 py-0.5 rounded">
                      {p.limits}
                    </span>
                  </div>

                  <div className="space-y-2 mb-5">
                    {p.features.map((feat) => (
                      <div key={feat} className="flex items-start gap-2 text-xs text-gray-300">
                        <div className="w-3.5 h-3.5 rounded-full bg-emerald-500/20 text-emerald-400 flex items-center justify-center flex-shrink-0 mt-0.5">
                          <Check size={10} strokeWidth={3} />
                        </div>
                        <span>{feat}</span>
                      </div>
                    ))}
                  </div>
                </div>

                <div className="pt-2">
                  <button
                    onClick={() => {
                      alert(`Subscription checkout for ${p.name} has been initiated for ${userEmail || 'your account'}. Please contact your administrator or billing provider to activate instantly.`);
                      if (onUpgradeSuccess) onUpgradeSuccess();
                      onClose();
                    }}
                    className={`w-full py-2.5 px-3.5 rounded-xl font-semibold text-xs sm:text-sm flex items-center justify-center gap-2 transition-all cursor-pointer ${
                      p.primary
                        ? 'bg-gradient-to-r from-emerald-500 to-cyan-500 hover:from-emerald-400 hover:to-cyan-400 text-white shadow-md shadow-emerald-500/25'
                        : 'bg-gray-800 hover:bg-gray-700 text-white border border-gray-700'
                    }`}
                  >
                    <Zap size={14} />
                    <span>{p.cta}</span>
                    <ArrowRight size={13} />
                  </button>
                </div>
              </div>
            ))}
          </div>

          {/* Footer Guarantee */}
          <div className="pt-3 border-t border-gray-800/80 flex flex-col sm:flex-row items-center justify-between gap-2.5 text-[11px] text-gray-500">
            <div className="flex items-center gap-1.5">
              <Shield size={13} className="text-emerald-400" />
              <span>Secure 256-bit encrypted checkout · Cancel anytime without penalty</span>
            </div>
            <button
              onClick={onClose}
              className="text-gray-400 hover:text-white underline cursor-pointer text-[11px]"
            >
              I will upgrade later
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
