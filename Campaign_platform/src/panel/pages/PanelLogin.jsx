/**
 * Panel Login Page
 * Authentication page for survey panelists
 */

import { useState } from 'react';
import { Link, useNavigate, useLocation, useSearchParams } from 'react-router-dom';
import { usePanelAuth } from '../context/PanelAuthContext';
import { resendVerification } from '../services/panelApi';
import PrivacyModal from '../components/PrivacyModal';
import '../styles/panel.css';

// Outcomes of GET /api/panel/verify-email, which redirects here with ?verified=
const VERIFY_MESSAGES = {
  '1': { tone: 'success', text: 'Your email is confirmed — you can sign in now.' },
  expired: { tone: 'error', text: 'That confirmation link has expired. Sign in and we\'ll send a new one.' },
  invalid: { tone: 'error', text: 'That confirmation link is not valid, or it has already been used.' },
};

export default function PanelLogin() {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [privacyOpen, setPrivacyOpen] = useState(false);
  const [resendNote, setResendNote] = useState('');

  const [searchParams] = useSearchParams();
  // ?resend=1 is the CTA target of the "confirm your email" reminder drip —
  // the original token may be long expired, so offer a fresh one directly.
  const verifyNotice = searchParams.get('resend')
    ? { tone: 'error', text: 'Enter your email address below and we\'ll send a fresh confirmation link.' }
    : VERIFY_MESSAGES[searchParams.get('verified')] || null;

  const handleResendVerification = async () => {
    if (!email) {
      setResendNote('Enter your email address above first.');
      return;
    }
    try {
      await resendVerification(email);
    } catch {
      // The endpoint is deliberately non-committal; a failure here still must
      // not reveal whether the address exists.
    }
    setResendNote('If that account exists and is unconfirmed, a new confirmation email is on its way.');
  };

  const { login } = usePanelAuth();
  const navigate = useNavigate();
  const location = useLocation();

  const from = location.state?.from?.pathname || '/panel/dashboard';

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (loading) return;

    setLoading(true);
    setError('');

    try {
      await login(email, password);
      navigate(from, { replace: true });
    } catch (err) {
      setError(err.message || 'Invalid email or password');
    } finally {
      setLoading(false);
    }
  };

  return (
    <main className="panel-auth-page">
      {/* Left: Login Form */}
      <section className="panel-auth-left">
        <div className="panel-auth-form panel-animate-in">
          {/* Logo */}
          <div className="mb-8">
            <Link to="/panel/login" className="inline-flex items-center gap-3">
              <img src="/newlogo.png" alt="Cogentix Research logo" style={{height:32}} />
              <span className="text-xl font-bold text-gray-900">Cogentix Research</span>
            </Link>
          </div>

          {/* Form Header */}
          <h1 className="text-2xl font-bold text-gray-800 mb-2">Welcome Back!</h1>
          <p className="text-gray-600 mb-6">Sign in to continue taking surveys and earning rewards.</p>

          {/* Double opt-in outcome, passed back by the verify-email redirect */}
          {verifyNotice && (
            <div
              className={`mb-4 p-3 rounded-lg text-sm border ${
                verifyNotice.tone === 'success'
                  ? 'bg-green-50 border-green-200 text-green-700'
                  : 'bg-amber-50 border-amber-200 text-amber-700'
              }`}
            >
              {verifyNotice.text}
              {verifyNotice.tone === 'error' && (
                <>
                  {' '}
                  <button
                    type="button"
                    onClick={handleResendVerification}
                    className="underline font-medium"
                    style={{ background: 'none', border: 'none', padding: 0, cursor: 'pointer' }}
                  >
                    Resend confirmation email
                  </button>
                </>
              )}
            </div>
          )}

          {resendNote && (
            <div className="mb-4 p-3 bg-blue-50 border border-blue-200 text-blue-700 rounded-lg text-sm">
              {resendNote}
            </div>
          )}

          {/* Error Message */}
          {error && (
            <div className="mb-4 p-3 bg-red-50 border border-red-200 text-red-600 rounded-lg text-sm">
              {error}
            </div>
          )}

          {/* Login Form */}
          <form onSubmit={handleSubmit}>
            <div className="panel-form-group">
              <label className="panel-form-label">Email</label>
              <input
                type="email"
                className="panel-form-input"
                placeholder="Enter your email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                required
                autoComplete="email"
              />
            </div>

            <div className="panel-form-group">
              <label className="panel-form-label">Password</label>
              <input
                type="password"
                className="panel-form-input"
                placeholder="Enter your password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
                autoComplete="current-password"
              />
            </div>

            <div className="flex justify-end mb-4">
              <Link to="/panel/forgot-password" className="text-sm text-panel-primary hover:underline">
                Forgot Password?
              </Link>
            </div>

            <button
              type="submit"
              disabled={loading}
              className="panel-btn-primary w-full py-3 text-base"
            >
              {loading ? 'Signing in...' : 'Sign In'}
            </button>
          </form>

          {/* Signup Link */}
          <p className="mt-6 text-center text-gray-600">
            Don't have an account?{' '}
            <Link to="/panel/signup" className="text-panel-primary font-medium hover:underline">
              Sign Up FREE
            </Link>
          </p>

          {/* Footer Links */}
          <div className="mt-8 pt-6 border-t border-gray-200 text-center">
            <div className="flex justify-center gap-4 text-sm text-gray-500">
              <Link to="/panel/terms" className="hover:text-panel-primary">Terms</Link>
              <button
                type="button"
                onClick={() => setPrivacyOpen(true)}
                className="hover:text-panel-primary"
                style={{ background: 'none', border: 'none', padding: 0, cursor: 'pointer' }}
              >
                Privacy
              </button>
              <Link to="/panel/faq" className="hover:text-panel-primary">FAQ</Link>
            </div>
          </div>
        </div>
      </section>
      <PrivacyModal open={privacyOpen} onClose={() => setPrivacyOpen(false)} />

      {/* Right: Hero Section */}
      <section className="panel-auth-right panel-hero-bg">
        <div className="relative z-10 text-center text-white p-8 max-w-lg">
          <h2 className="text-4xl font-bold mb-4">
            Express your views and make an impact!
          </h2>
          <p className="text-white/80 text-lg mb-8">
            Join thousands of panelists earning rewards by sharing their opinions.
          </p>

          {/* Stats Badges */}
          <div className="flex flex-col gap-3 items-center">
            <div className="panel-stat-badge">
              <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
              </svg>
              <span>More than 20,000 surveys completed!</span>
            </div>
            <div className="panel-stat-badge">
              <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 7h8m0 0v8m0-8l-8 8-4-4-6 6" />
              </svg>
              <span>30+ surveys available everyday!</span>
            </div>
          </div>

          {/* Bonus Banner */}
          <div className="mt-8 bg-panel-accent/90 rounded-lg p-4">
            <p className="font-bold text-lg">🎁 Sign Up & Get FREE BONUS!</p>
            <p className="text-white/90 text-sm">Start earning from day one</p>
          </div>
        </div>
      </section>
    </main>
  );
}
