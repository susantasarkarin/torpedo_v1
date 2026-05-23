/**
 * Panel Forgot Password Page
 * Password reset request page for panelists
 */

import { useState } from 'react';
import { Link } from 'react-router-dom';
import { forgotPassword } from '../services/panelApi';
import PrivacyModal from '../components/PrivacyModal';
import '../styles/panel.css';

export default function PanelForgotPassword() {
  const [email, setEmail] = useState('');
  const [loading, setLoading] = useState(false);
  const [submitted, setSubmitted] = useState(false);
  const [error, setError] = useState('');
  const [privacyOpen, setPrivacyOpen] = useState(false);

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (loading) return;

    setLoading(true);
    setError('');

    try {
      await forgotPassword(email);
      setSubmitted(true);
    } catch (err) {
      setError(err.message || 'Failed to send reset email. Please try again.');
    } finally {
      setLoading(false);
    }
  };

  return (
    <main className="panel-auth-page">
      {/* Left: Form */}
      <section className="panel-auth-left">
        <div className="panel-auth-form panel-animate-in">
          {/* Logo */}
          <div className="mb-8">
            <Link to="/panel/login" className="inline-flex items-center gap-3">
              <img src="/newlogo.png" alt="Cogentix Research logo" style={{height:32}} />
              <span className="text-xl font-bold text-gray-900">Cogentix Research</span>
            </Link>
          </div>

          {submitted ? (
            /* Success State */
            <div className="text-center">
              <div className="w-16 h-16 bg-panel-success-50 rounded-full flex items-center justify-center mx-auto mb-4">
                <svg className="w-8 h-8 text-panel-success" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
                </svg>
              </div>
              <h1 className="text-2xl font-bold text-gray-800 mb-2">Check Your Email</h1>
              <p className="text-gray-600 mb-6">
                If an account exists with <strong>{email}</strong>, we've sent password reset instructions.
              </p>
              <p className="text-gray-500 text-sm mb-6">
                Didn't receive the email? Check your spam folder or try again.
              </p>
              <Link to="/panel/login" className="panel-btn-primary inline-flex py-3 px-6">
                Back to Login
              </Link>
            </div>
          ) : (
            /* Form State */
            <>
              <h1 className="text-2xl font-bold text-gray-800 mb-2">Forgot Password?</h1>
              <p className="text-gray-600 mb-6">
                Enter your email address and we'll send you instructions to reset your password.
              </p>

              {/* Error Message */}
              {error && (
                <div className="mb-4 p-3 bg-red-50 border border-red-200 text-red-600 rounded-lg text-sm">
                  {error}
                </div>
              )}

              <form onSubmit={handleSubmit}>
                <div className="panel-form-group">
                  <label className="panel-form-label">Email Address</label>
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

                <button
                  type="submit"
                  disabled={loading}
                  className="panel-btn-primary w-full py-3 text-base"
                >
                  {loading ? 'Sending...' : 'Send Reset Link'}
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
            Don't worry, we've got you covered!
          </h2>
          <p className="text-white/80 text-lg">
            Password recovery is quick and easy. You'll be back to earning rewards in no time.
          </p>

          <div className="mt-8">
            <svg className="w-32 h-32 mx-auto text-white/30" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1} d="M15 7a2 2 0 012 2m4 0a6 6 0 01-7.743 5.743L11 17H9v2H7v2H4a1 1 0 01-1-1v-2.586a1 1 0 01.293-.707l5.964-5.964A6 6 0 1121 9z" />
            </svg>
          </div>
        </div>
      </section>
    </main>
  );
}
