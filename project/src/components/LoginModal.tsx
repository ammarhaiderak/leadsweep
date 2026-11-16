import { useState, useEffect } from 'react';
import { Mail, Lock, X, CheckCircle2, AlertCircle, ArrowRight, Loader2 } from 'lucide-react';
import { api } from '@/api/client';

interface LoginModalProps {
  isOpen: boolean;
  onClose: () => void;
  onSuccess: (user: any) => void;
  initialMode?: 'signin' | 'reset';
  resetToken?: string;
  resetEmail?: string;
}

export function LoginModal({ isOpen, onClose, onSuccess, initialMode = 'signin', resetToken = '', resetEmail = '' }: LoginModalProps) {
  const [mode, setMode] = useState<'signin' | 'reset'>(initialMode);
  const [email, setEmail] = useState(resetEmail);
  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [tokenInput, setTokenInput] = useState(resetToken);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  useEffect(() => {
    if (isOpen) {
      setMode(initialMode);
      if (resetEmail) setEmail(resetEmail);
      if (resetToken) setTokenInput(resetToken);
      setError(null);
      setSuccess(null);
    }
  }, [isOpen, initialMode, resetEmail, resetToken]);

  if (!isOpen) return null;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setError(null);
    setSuccess(null);

    const cleanEmail = email.trim().toLowerCase();
    const cleanPassword = password.trim();

    try {
      if (mode === 'reset') {
        if (!tokenInput.trim()) {
          setError('Please provide your reset token.');
          setLoading(false);
          return;
        }
        if (!cleanPassword || cleanPassword.length < 6) {
          setError('Password must be at least 6 characters.');
          setLoading(false);
          return;
        }
        if (cleanPassword !== confirmPassword.trim()) {
          setError('Passwords do not match.');
          setLoading(false);
          return;
        }
        try {
          const res = await api.resetPassword(tokenInput.trim(), cleanEmail, cleanPassword);
          setSuccess(res.message || 'Password updated successfully! Please sign in with your new password.');
          setTimeout(() => {
            setMode('signin');
            setPassword('');
            setConfirmPassword('');
          }, 1500);
        } catch (resetErr: any) {
          setError(resetErr.message || 'Failed to update password.');
        }
        setLoading(false);
        return;
      }

      // Authenticate directly through backend API
      try {
        const res = await api.login(cleanEmail, cleanPassword);
        localStorage.setItem('leadsweep_auth_token', res.token);
        localStorage.setItem('leadsweep_auth_user', JSON.stringify(res.user));
        setSuccess('Authentication successful. Opening workspace...');
        setTimeout(() => {
          onSuccess(res.user);
          onClose();
        }, 500);
      } catch (backendErr: any) {
        // Enforce strict authorization - do not issue mock sessions
        let msg = backendErr?.message || 'Authentication failed. Please verify your credentials or wait for admin approval.';
        if (msg === 'Failed to fetch') {
          const resolvedUrl = typeof window !== 'undefined' ? `${window.location.origin}/v1/auth/login` : '/v1/auth/login';
          msg = `Cannot reach the server at ${resolvedUrl}`;
        }
        setError(msg);
      }
    } catch (err: any) {
      setError(err.message || 'Authentication failed. Please verify your credentials.');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="fixed inset-0 z-[100] flex items-center justify-center p-4 sm:p-6 bg-gray-950/85 backdrop-blur-md animate-in fade-in duration-200 overflow-y-auto">
      <div className="relative w-full max-w-sm sm:max-w-md bg-gray-900 border border-gray-800 rounded-2xl p-5 sm:p-7 shadow-2xl shadow-emerald-500/10 my-auto max-h-[85vh] overflow-y-auto scrollbar-thin">
        <button
          type="button"
          onClick={onClose}
          className="absolute top-4 right-4 p-1.5 text-gray-400 hover:text-white rounded-lg hover:bg-gray-800 transition-colors"
          aria-label="Close"
        >
          <X size={18} />
        </button>

        <div className="mb-4 text-left pr-6">
          <h2 className="text-xl sm:text-2xl font-bold text-white tracking-tight">
            {mode === 'signin'
              ? 'Sign In to LeadSweep'
              : 'Set New Password'}
          </h2>
          <p className="text-xs text-gray-400 mt-1 leading-relaxed">
            {mode === 'signin'
              ? 'Enter your email and password to access your workspace.'
              : 'Enter your verification token and create a new secure password.'}
          </p>
        </div>

        {error && (
          <div className="mb-4 flex items-center gap-2 p-3 rounded-xl bg-red-500/10 border border-red-500/30 text-red-400 text-xs">
            <AlertCircle size={15} className="shrink-0" />
            <span>{error}</span>
          </div>
        )}

        {success && (
          <div className="mb-4 flex items-start gap-2 p-3 rounded-xl bg-emerald-500/10 border border-emerald-500/30 text-emerald-400 text-xs">
            <CheckCircle2 size={16} className="shrink-0 mt-0.5" />
            <span className="leading-relaxed">{success}</span>
          </div>
        )}



        <form onSubmit={handleSubmit} className="space-y-3.5">
          <div>
            <label className="block text-xs font-semibold text-gray-400 uppercase tracking-wider mb-1">
              Email Address
            </label>
            <div className="relative">
              <Mail className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-500" />
              <input
                type="email"
                required
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="name@company.com"
                className="w-full bg-gray-950/90 border border-gray-800 focus:border-emerald-500 rounded-xl pl-9 pr-3.5 py-2 text-xs sm:text-sm text-white placeholder-gray-600 outline-none transition-colors"
              />
            </div>
          </div>

          {mode === 'signin' ? (
            <div>
              <div className="flex items-center justify-between mb-1">
                 <label className="block text-xs font-semibold text-gray-400 uppercase tracking-wider">
                  Password
                </label>
                <button
                  type="button"
                  onClick={async () => {
                    const cleanEmail = email.trim().toLowerCase();
                    if (!cleanEmail || !cleanEmail.includes('@')) {
                      setError("Please enter your registered email address first to reset your password.");
                      return;
                    }
                    setLoading(true);
                    setError(null);
                    setSuccess(null);
                    try {
                      const res = await api.forgotPassword(cleanEmail);
                      setSuccess(res.message || "Password reset instructions have been sent to your email. The administrator has also been notified.");
                    } catch (err: any) {
                      setError(err.message || "Failed to process password reset request.");
                    } finally {
                      setLoading(false);
                    }
                  }}
                  className="text-[11px] text-emerald-400 hover:text-emerald-300 transition-colors hover:underline"
                >
                  Forgot Password?
                </button>
              </div>
              <div className="relative">
                <Lock className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-500" />
                <input
                  type="password"
                  required
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder="••••••••••••"
                  className="w-full bg-gray-950/90 border border-gray-800 focus:border-emerald-500 rounded-xl pl-9 pr-3.5 py-2 text-xs sm:text-sm text-white placeholder-gray-600 outline-none transition-colors"
                />
              </div>
            </div>
          ) : (
            <>
              <div>
                <label className="block text-xs font-semibold text-gray-400 uppercase tracking-wider mb-1">
                  Reset Token
                </label>
                <input
                  type="text"
                  required
                  value={tokenInput}
                  onChange={(e) => setTokenInput(e.target.value)}
                  placeholder="Paste token received in email"
                  className="w-full bg-gray-950/90 border border-gray-800 focus:border-emerald-500 rounded-xl px-3.5 py-2 text-xs sm:text-sm text-white placeholder-gray-600 outline-none transition-colors"
                />
              </div>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                <div>
                  <label className="block text-xs font-semibold text-gray-400 uppercase tracking-wider mb-1">
                    New Password
                  </label>
                  <div className="relative">
                    <Lock className="absolute left-3 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-gray-500" />
                    <input
                      type="password"
                      required
                      value={password}
                      onChange={(e) => setPassword(e.target.value)}
                      placeholder="Min 6 characters"
                      className="w-full bg-gray-950/90 border border-gray-800 focus:border-emerald-500 rounded-xl pl-9 pr-3 py-2 text-xs sm:text-sm text-white placeholder-gray-600 outline-none transition-colors"
                    />
                  </div>
                </div>
                <div>
                  <label className="block text-xs font-semibold text-gray-400 uppercase tracking-wider mb-1">
                    Confirm Password
                  </label>
                  <div className="relative">
                    <Lock className="absolute left-3 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-gray-500" />
                    <input
                      type="password"
                      required
                      value={confirmPassword}
                      onChange={(e) => setConfirmPassword(e.target.value)}
                      placeholder="Re-enter password"
                      className="w-full bg-gray-950/90 border border-gray-800 focus:border-emerald-500 rounded-xl pl-9 pr-3 py-2 text-xs sm:text-sm text-white placeholder-gray-600 outline-none transition-colors"
                    />
                  </div>
                </div>
              </div>
            </>
          )}

          <div className="pt-2">
            <button
              type="submit"
              disabled={loading || !!success}
              className="w-full flex items-center justify-center gap-2 bg-gradient-to-r from-emerald-500 to-cyan-500 hover:from-emerald-400 hover:to-cyan-400 py-2.5 px-4 rounded-xl font-semibold text-xs sm:text-sm text-white transition-all shadow-lg shadow-emerald-500/20 disabled:opacity-50"
            >
              {loading ? (
                <>
                  <Loader2 size={16} className="animate-spin" />
                  <span>Processing...</span>
                </>
              ) : (
                <>
                  <span>
                    {mode === 'signin'
                      ? 'Sign In'
                      : 'Update Password & Save'}
                  </span>
                  <ArrowRight size={15} />
                </>
              )}
            </button>
          </div>
        </form>

        <div className="mt-4 pt-3 border-t border-gray-800/80 text-center">
          {mode === 'signin' ? (
            <p className="text-xs text-gray-400">
              No account? Ask the owner of this LeadSweep instance to add you from the Users page.
            </p>
          ) : (
            <p className="text-xs text-gray-400">
              Already have an account?{' '}
              <button
                type="button"
                onClick={() => {
                  setMode('signin');
                  setError(null);
                  setSuccess(null);
                }}
                className="font-semibold text-emerald-400 hover:text-emerald-300 transition-colors hover:underline"
              >
                Sign in
              </button>
            </p>
          )}
        </div>
      </div>
    </div>
  );
}
