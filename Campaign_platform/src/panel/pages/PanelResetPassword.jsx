/**
 * Panel Reset Password Page
 * Landing page for the reset link emailed by /panel/forgot-password.
 * The token arrives as ?token=... and is exchanged for a new password.
 */

import { useState } from 'react';
import { Link, useSearchParams, useNavigate } from 'react-router-dom';
import { resetPassword } from '../services/panelApi';
import PrivacyModal from '../components/PrivacyModal';
import '../styles/panel.css';

export default function PanelResetPassword() {
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const token = searchParams.get('token') || '';

  const [password, setPassword] = useState('');
  const [confirm, setConfirm] = useState('');
  const [loading, setLoading] = useState(false);
  const [done, setDone] = useState(false);
  const [error, setError] = useState('');
  const [privacyOpen, setPrivacyOpen] = useState(false);

  // Mirrors the server-side rule in ResetPasswordRequest.password_strength so
  // the user isn't bounced by a 422 after submitting.
  const validate = () => {
    if (password.length < 8) return 'Password must be at least 8 characters.';
    if (!/[A-Z]/.test(password)) return 'Password must contain at least one uppercase letter.';
    if (!/[a-z]/.test(password)) return 'Password must contain at least one lowercase letter.';
    if (!/[0-9]/.test(password)) return 'Password must contain at least one digit.';
    if (password !== confirm) return 'Passwords do not match.';
    return '';
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (loading) return;

    const problem = validate();
    if (problem) {
      setError(problem);
      return;
    }

    setLoading(true);
    setError('');

    try {
      await resetPassword(token, password);
      setDone(true);
      setTimeout(() => navigate('/panel/login'), 3000);
    } catch (err) {
      setError(err.message || 'This reset link is invalid or has expired. Please request a new one.');
    } finally {
      setLoading(false);
    }
  };

  return (
    <main className="panel-auth-page">
      <section className="panel-auth-left">
        <div className="panel-auth-form panel-animate-in">
          <div className="mb-8">
            <Link to="/panel/login" className="inline-flex items-center gap-3">
              <img src="/newlogo.png" alt="Cogentix Research logo" style={{ height: 32 }} />
              <span className="text-xl font-bold text-gray-900">Cogentix Research</span>
            </Link>
          </div>

          {!token ? (
            <div className="text-center">
              <h1 className="text-2xl font-bold text-gray-800 mb-2">Link Missing</h1>
              <p className="text-gray-600 mb-6">
                This page needs a reset link from your email. Request a new one below.
              </p>
              <Link to="/panel/forgot-password" className="panel-btn-primary inline-flex py-3 px-6">
                Request Reset Link
              </Link>
            </div>
          ) : done ? (
            <div className="text-center">
              <div className="w-16 h-16 bg-panel-success-50 rounded-full flex items-center justify-center mx-auto mb-4">
                <svg className="w-8 h-8 text-panel-success" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
                </svg>
              </div>
              <h1 className="text-2xl font-bold text-gray-800 mb-2">Password Updated</h1>
              <p className="text-gray-600 mb-6">
                You can now sign in with your new password. Redirecting you to login…
              </p>
              <Link to="/panel/login" className="panel-btn-primary inline-flex py-3 px-6">
                Go to Login
              </Link>
            </div>
          ) : (
            <>
              <h1 className="text-2xl font-bold text-gray-800 mb-2">Choose a New Password</h1>
              <p className="text-gray-600 mb-6">
                Pick a password with at least 8 characters, including an uppercase letter,
                a lowercase letter and a digit.
              </p>

              {error && (
                <div className="mb-4 p-3 bg-red-50 border border-red-200 text-red-600 rounded-lg text-sm">
                  {error}
                </div>
              )}

              <form onSubmit={handleSubmit}>
                <div className="panel-form-group">
                  <label className="panel-form-label">New Password</label>
                  <input
                    type="password"
                    className="panel-form-input"
                    placeholder="Enter a new password"
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    required
                    autoComplete="new-password"
                  />
                </div>

                <div className="panel-form-group">
                  <label className="panel-form-label">Confirm Password</label>
                  <input
                    type="password"
                    className="panel-form-input"
                    placeholder="Re-enter the new password"
                    value={confirm}
                    onChange={(e) => setConfirm(e.target.value)}
                    required
                    autoComplete="new-password"
                  />
                </div>

                <button
                  type="submit"
                  disabled={loading}
                  className="panel-btn-primary w-full py-3 text-base"
                >
                  {loading ? 'Updating...' : 'Update Password'}
                </button>
              </form>

              <p className="mt-6 text-center text-gray-600">
                Remember your password?{' '}
                <Link to="/panel/login" className="text-panel-primary font-medium hover:underline">
                  Sign In
                </Link>
              </p>
            </>
          )}

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

      <section className="panel-auth-right panel-hero-bg">
        <div className="relative z-10 text-center text-white p-8 max-w-lg">
          <h2 className="text-4xl font-bold mb-4">Almost there!</h2>
          <p className="text-white/80 text-lg">
            Set your new password and you'll be back to earning rewards in seconds.
          </p>
        </div>
      </section>
    </main>
  );
}
