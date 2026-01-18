/**
 * Panel Login Page
 * Authentication page for survey panelists
 */

import { useState } from 'react';
import { Link, useNavigate, useLocation } from 'react-router-dom';
import { usePanelAuth } from '../context/PanelAuthContext';
import '../styles/panel.css';

export default function PanelLogin() {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  
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
            <Link to="/panel/login" className="inline-flex items-center gap-2">
              <span className="text-3xl font-bold text-panel-primary">
                Sur<span className="text-panel-accent">v</span>ey
              </span>
              <span className="bg-panel-primary text-white text-xs font-bold px-2 py-0.5 rounded">
                FIELDWORK
              </span>
            </Link>
          </div>

          {/* Form Header */}
          <h1 className="text-2xl font-bold text-gray-800 mb-2">Welcome Back!</h1>
          <p className="text-gray-600 mb-6">Sign in to continue taking surveys and earning rewards.</p>

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
              <Link to="/panel/privacy" className="hover:text-panel-primary">Privacy</Link>
              <Link to="/panel/faq" className="hover:text-panel-primary">FAQ</Link>
            </div>
          </div>
        </div>
      </section>

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
