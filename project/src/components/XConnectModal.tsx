import { useState } from 'react';
import { ShieldCheck, Lock, ExternalLink, AlertCircle, CheckCircle2, Loader2, X, Info } from 'lucide-react';
import { api } from '@/api/client';

interface XConnectModalProps {
  isOpen: boolean;
  onClose: () => void;
  onSuccess: () => void;
  userEmail?: string;
}

export function XConnectModal({ isOpen, onClose, onSuccess, userEmail }: XConnectModalProps) {
  const [connecting, setConnecting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (!isOpen) return null;

  const handleConnect = async () => {
    setConnecting(true);
    setError(null);
    try {
      await api.connectXAccount(userEmail || 'admin');
      setConnecting(false);
      onSuccess();
    } catch (err: any) {
      console.error('X connect failed:', err);
      // Ethical & friendly user-facing message, never exposing raw backend error codes
      setError(
        err?.message?.includes('timed out') || err?.message?.includes('closed')
          ? 'Verification was cancelled or the login window was closed before completion. Please try again when ready.'
          : 'Safe verification could not be completed at this moment. Please click the button below to retry.'
      );
      setConnecting(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-3 sm:p-5 bg-black/80 backdrop-blur-md animate-fade-in overflow-y-auto">
      <div 
        className="relative w-full max-w-lg bg-gray-900 border border-gray-800 rounded-2xl shadow-2xl p-5 sm:p-7 overflow-hidden text-left my-auto max-h-[92vh] flex flex-col justify-between"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Glow accent */}
        <div className="absolute -top-24 -right-24 w-48 h-48 bg-emerald-500/10 rounded-full blur-3xl pointer-events-none" />
        <div className="absolute -bottom-24 -left-24 w-48 h-48 bg-cyan-500/10 rounded-full blur-3xl pointer-events-none" />

        {/* Close Button */}
        <button
          onClick={onClose}
          disabled={connecting}
          className="absolute top-4 right-4 p-2 text-gray-400 hover:text-white rounded-lg hover:bg-gray-800 transition-colors disabled:opacity-50 cursor-pointer"
          title="Close dialog"
        >
          <X size={18} />
        </button>

        <div className="overflow-y-auto pr-1 space-y-4">
          {/* Header Badge */}
          <div className="flex items-center gap-3">
            <div className="w-11 h-11 sm:w-12 sm:h-12 rounded-xl bg-gradient-to-br from-emerald-500/20 to-cyan-500/20 border border-emerald-500/30 flex items-center justify-center text-emerald-400 shadow-inner flex-shrink-0">
              <ShieldCheck size={24} />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <span className="text-[11px] uppercase tracking-wider font-semibold text-emerald-400 px-2 py-0.5 rounded-full bg-emerald-500/10 border border-emerald-500/20">
                  Security & Verified Search
                </span>
              </div>
              <h2 className="text-lg sm:text-xl font-bold text-white mt-1">Connect Your X (Twitter) Account</h2>
            </div>
          </div>

          {/* Trust & Transparency Box */}
          <div className="bg-gray-800/60 border border-gray-700/60 rounded-xl p-3.5 sm:p-4 space-y-3">
            <div className="flex items-start gap-3">
              <Lock size={17} className="text-emerald-400 flex-shrink-0 mt-0.5" />
              <div className="text-xs text-gray-300 leading-relaxed">
                <strong className="text-white block font-medium mb-0.5">100% Zero-Password Storage Guarantee</strong>
                We will never ask for, view, or store your Twitter password. You sign in directly on the official X login portal in a secure browser window on your device.
              </div>
            </div>
            <div className="flex items-start gap-3 border-t border-gray-700/40 pt-2.5">
              <CheckCircle2 size={17} className="text-cyan-400 flex-shrink-0 mt-0.5" />
              <div className="text-xs text-gray-300 leading-relaxed">
                <strong className="text-white block font-medium mb-0.5">One-Time Setup · Stays Connected</strong>
                Once connected, you will never be asked again. It only asks if you manually disconnect or if your session expires, keeping search results authentic and protecting your account from automated blocks.
              </div>
            </div>
          </div>

          {/* Friendly Guidance/Error Alert */}
          {error && (
            <div className="p-3 rounded-xl bg-amber-500/10 border border-amber-500/30 text-amber-300 text-xs flex items-start gap-2.5 animate-in fade-in duration-150">
              <Info size={16} className="flex-shrink-0 mt-0.5 text-amber-400" />
              <div>
                <p className="font-semibold text-white">Connection Assistance</p>
                <p className="mt-0.5 leading-relaxed text-amber-200/90">{error}</p>
              </div>
            </div>
          )}

          {/* Step-by-Step Connection Instructions */}
          <div className="space-y-2 text-xs text-gray-400 bg-gray-950/50 p-3.5 rounded-xl border border-gray-800">
            <p className="text-gray-300 font-semibold flex items-center gap-1.5">
              <CheckCircle2 size={14} className="text-emerald-400" /> How to connect safely (4 easy steps):
            </p>
            <ol className="list-decimal list-inside space-y-1.5 ml-0.5 text-gray-300/90 leading-relaxed">
              <li>Click the green <span className="text-white font-medium">"Launch Safe Connect Window"</span> button below.</li>
              <li>A secure browser window will open directly to <span className="text-cyan-400 font-mono">x.com/login</span>.</li>
              <li>Sign in using your regular Twitter credentials or 2-factor authentication.</li>
              <li>Once you reach your home feed, the window will automatically close and your account is safely verified.</li>
            </ol>
          </div>
        </div>

        {/* Action Buttons */}
        <div className="flex flex-col-reverse sm:flex-row items-center gap-3 pt-4 border-t border-gray-800/80 mt-2">
          <button
            type="button"
            onClick={onClose}
            disabled={connecting}
            className="w-full sm:w-auto sm:flex-1 px-4 py-2.5 rounded-xl border border-gray-700 text-xs sm:text-sm font-medium text-gray-300 hover:text-white hover:bg-gray-800 transition-colors disabled:opacity-50 cursor-pointer"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={handleConnect}
            disabled={connecting}
            className="w-full sm:w-auto sm:flex-[2] flex items-center justify-center gap-2 px-5 py-2.5 rounded-xl bg-gradient-to-r from-emerald-500 to-cyan-500 hover:from-emerald-400 hover:to-cyan-400 text-white text-xs sm:text-sm font-semibold shadow-lg shadow-emerald-500/20 hover:shadow-emerald-500/30 transition-all disabled:opacity-60 cursor-pointer"
          >
            {connecting ? (
              <>
                <Loader2 size={16} className="animate-spin" />
                <span>Waiting for Safe Login...</span>
              </>
            ) : (
              <>
                <span>Launch Safe Connect Window</span>
                <ExternalLink size={15} />
              </>
            )}
          </button>
        </div>
      </div>
    </div>
  );
}
