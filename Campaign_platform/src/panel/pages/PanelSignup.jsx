/**
 * Panel Signup Page
 * Registration page for new survey panelists
 */

import { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { usePanelAuth } from '../context/PanelAuthContext';
import PrivacyModal from '../components/PrivacyModal';
import '../styles/panel.css';

const COUNTRIES = [
  'India', 'United States', 'United Kingdom', 'Canada', 'Australia',
  'Germany', 'France', 'Brazil', 'Mexico', 'Japan', 'South Korea',
  'Singapore', 'Malaysia', 'Philippines', 'Indonesia', 'Thailand',
  'Vietnam', 'South Africa', 'Nigeria', 'Kenya', 'Egypt',
  'United Arab Emirates', 'Saudi Arabia', 'Other'
];

const LANGUAGES = [
  'English', 'Hindi', 'Spanish', 'French', 'German', 'Portuguese',
  'Japanese', 'Korean', 'Chinese', 'Arabic', 'Other'
];

export default function PanelSignup() {
  const [formData, setFormData] = useState({
    first_name: '',
    last_name: '',
    email: '',
    country: '',
    language: 'English',
    password: '',
    confirm_password: '',
    agree_terms: false,
  });
  const [loading, setLoading] = useState(false);
  const [errors, setErrors] = useState({});
  const [privacyOpen, setPrivacyOpen] = useState(false);
  
  const { signup } = usePanelAuth();
  const navigate = useNavigate();

  const handleChange = (e) => {
    const { name, value, type, checked } = e.target;
    setFormData(prev => ({
      ...prev,
      [name]: type === 'checkbox' ? checked : value
    }));
    // Clear error when field is modified
    if (errors[name]) {
      setErrors(prev => ({ ...prev, [name]: null }));
    }
  };

  const validate = () => {
    const newErrors = {};
    
    if (!formData.first_name.trim()) newErrors.first_name = 'First name is required';
    if (!formData.last_name.trim()) newErrors.last_name = 'Last name is required';
    if (!formData.email.trim()) newErrors.email = 'Email is required';
    else if (!/\S+@\S+\.\S+/.test(formData.email)) newErrors.email = 'Invalid email format';
    if (!formData.country) newErrors.country = 'Country is required';
    
    if (!formData.password) {
      newErrors.password = 'Password is required';
    } else if (formData.password.length < 8) {
      newErrors.password = 'Password must be at least 8 characters';
    } else if (!/[A-Z]/.test(formData.password)) {
      newErrors.password = 'Password must contain an uppercase letter';
    } else if (!/[a-z]/.test(formData.password)) {
      newErrors.password = 'Password must contain a lowercase letter';
    } else if (!/[0-9]/.test(formData.password)) {
      newErrors.password = 'Password must contain a number';
    }
    
    if (formData.password !== formData.confirm_password) {
      newErrors.confirm_password = 'Passwords do not match';
    }
    
    if (!formData.agree_terms) {
      newErrors.agree_terms = 'You must agree to the terms';
    }
    
    setErrors(newErrors);
    return Object.keys(newErrors).length === 0;
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (loading) return;
    if (!validate()) return;

    setLoading(true);

    try {
      await signup({
        first_name: formData.first_name,
        last_name: formData.last_name,
        email: formData.email,
        country: formData.country,
        language: formData.language,
        password: formData.password,
        confirm_password: formData.confirm_password,
      });
      navigate('/panel/dashboard');
    } catch (err) {
      setErrors({ form: err.message || 'Registration failed. Please try again.' });
    } finally {
      setLoading(false);
    }
  };

  return (
    <main className="panel-auth-page">
      {/* Left: Signup Form */}
      <section className="panel-auth-left overflow-y-auto">
        <div className="panel-auth-form panel-animate-in py-8">
          {/* Logo */}
          <div className="mb-6">
            <Link to="/panel/login" className="inline-flex items-center gap-3">
              <img src="/newlogo.png" alt="Cogentix Research logo" style={{height:32}} />
              <span className="text-xl font-bold text-gray-900">Cogentix Research</span>
            </Link>
          </div>

          {/* Form Header */}
          <h1 className="text-2xl font-bold text-gray-800 mb-2">Create Your Account</h1>
          <p className="text-gray-600 mb-6">Join our panel and start earning rewards today!</p>

          {/* Form Error */}
          {errors.form && (
            <div className="mb-4 p-3 bg-red-50 border border-red-200 text-red-600 rounded-lg text-sm">
              {errors.form}
            </div>
          )}

          {/* Signup Form */}
          <form onSubmit={handleSubmit}>
            {/* Name Row */}
            <div className="grid grid-cols-2 gap-4">
              <div className="panel-form-group">
                <label className="panel-form-label">First Name *</label>
                <input
                  type="text"
                  name="first_name"
                  className={`panel-form-input ${errors.first_name ? 'error' : ''}`}
                  placeholder="John"
                  value={formData.first_name}
                  onChange={handleChange}
                />
                {errors.first_name && <p className="panel-form-error">{errors.first_name}</p>}
              </div>

              <div className="panel-form-group">
                <label className="panel-form-label">Last Name *</label>
                <input
                  type="text"
                  name="last_name"
                  className={`panel-form-input ${errors.last_name ? 'error' : ''}`}
                  placeholder="Doe"
                  value={formData.last_name}
                  onChange={handleChange}
                />
                {errors.last_name && <p className="panel-form-error">{errors.last_name}</p>}
              </div>
            </div>

            {/* Email */}
            <div className="panel-form-group">
              <label className="panel-form-label">Email *</label>
              <input
                type="email"
                name="email"
                className={`panel-form-input ${errors.email ? 'error' : ''}`}
                placeholder="john@example.com"
                value={formData.email}
                onChange={handleChange}
              />
              {errors.email && <p className="panel-form-error">{errors.email}</p>}
            </div>

            {/* Country & Language Row */}
            <div className="grid grid-cols-2 gap-4">
              <div className="panel-form-group">
                <label className="panel-form-label">Country *</label>
                <select
                  name="country"
                  className={`panel-form-input panel-form-select ${errors.country ? 'error' : ''}`}
                  value={formData.country}
                  onChange={handleChange}
                >
                  <option value="">Select Country</option>
                  {COUNTRIES.map(country => (
                    <option key={country} value={country}>{country}</option>
                  ))}
                </select>
                {errors.country && <p className="panel-form-error">{errors.country}</p>}
              </div>

              <div className="panel-form-group">
                <label className="panel-form-label">Language</label>
                <select
                  name="language"
                  className="panel-form-input panel-form-select"
                  value={formData.language}
                  onChange={handleChange}
                >
                  {LANGUAGES.map(lang => (
                    <option key={lang} value={lang}>{lang}</option>
                  ))}
                </select>
              </div>
            </div>

            {/* Password */}
            <div className="panel-form-group">
              <label className="panel-form-label">Password *</label>
              <input
                type="password"
                name="password"
                className={`panel-form-input ${errors.password ? 'error' : ''}`}
                placeholder="Min 8 chars, uppercase, lowercase, number"
                value={formData.password}
                onChange={handleChange}
              />
              {errors.password && <p className="panel-form-error">{errors.password}</p>}
            </div>

            {/* Confirm Password */}
            <div className="panel-form-group">
              <label className="panel-form-label">Confirm Password *</label>
              <input
                type="password"
                name="confirm_password"
                className={`panel-form-input ${errors.confirm_password ? 'error' : ''}`}
                placeholder="Re-enter your password"
                value={formData.confirm_password}
                onChange={handleChange}
              />
              {errors.confirm_password && <p className="panel-form-error">{errors.confirm_password}</p>}
            </div>

            {/* Terms Checkbox */}
            <div className="panel-form-group">
              <label className="flex items-start gap-2 cursor-pointer">
                <input
                  type="checkbox"
                  name="agree_terms"
                  checked={formData.agree_terms}
                  onChange={handleChange}
                  className="mt-1"
                />
                <span className="text-sm text-gray-600">
                  I agree to the{' '}
                  <Link to="/panel/terms" className="text-panel-primary hover:underline">Terms & Conditions</Link>
                  {' '}and{' '}
                  <button
                    type="button"
                    onClick={() => setPrivacyOpen(true)}
                    className="text-panel-primary hover:underline"
                    style={{ background: 'none', border: 'none', padding: 0, cursor: 'pointer' }}
                  >
                    Privacy Policy
                  </button>
                </span>
              </label>
              {errors.agree_terms && <p className="panel-form-error">{errors.agree_terms}</p>}
            </div>

            <button
              type="submit"
              disabled={loading}
              className="panel-btn-primary w-full py-3 text-base mt-2"
            >
              {loading ? 'Creating Account...' : 'Create Account'}
            </button>
          </form>

          {/* Login Link */}
          <p className="mt-6 text-center text-gray-600">
            Already have an account?{' '}
            <Link to="/panel/login" className="text-panel-primary font-medium hover:underline">
              Sign In
            </Link>
          </p>
        </div>
      </section>
      <PrivacyModal open={privacyOpen} onClose={() => setPrivacyOpen(false)} />

      {/* Right: Hero Section */}
      <section className="panel-auth-right panel-hero-bg">
        <div className="relative z-10 text-center text-white p-8 max-w-lg">
          <h2 className="text-4xl font-bold mb-4">
            Express your views and make an impact!
          </h2>
          
          {/* How It Works */}
          <div className="mt-8 text-left">
            <h3 className="text-xl font-semibold mb-4">How it works</h3>
            <div className="space-y-4">
              <div className="flex items-center gap-4">
                <div className="w-10 h-10 rounded-full bg-panel-accent flex items-center justify-center font-bold">1</div>
                <div>
                  <p className="font-medium">Sign Up</p>
                  <p className="text-white/70 text-sm">Create your free account</p>
                </div>
              </div>
              <div className="flex items-center gap-4">
                <div className="w-10 h-10 rounded-full bg-panel-accent flex items-center justify-center font-bold">2</div>
                <div>
                  <p className="font-medium">Take Surveys</p>
                  <p className="text-white/70 text-sm">Share your valuable opinions</p>
                </div>
              </div>
              <div className="flex items-center gap-4">
                <div className="w-10 h-10 rounded-full bg-panel-accent flex items-center justify-center font-bold">3</div>
                <div>
                  <p className="font-medium">Get Paid</p>
                  <p className="text-white/70 text-sm">Redeem rewards & gift cards</p>
                </div>
              </div>
            </div>
          </div>

          {/* Stats */}
          <div className="mt-8 grid grid-cols-3 gap-4">
            <div className="bg-white/10 rounded-lg p-3">
              <p className="text-2xl font-bold">9,999+</p>
              <p className="text-xs text-white/70">Rewards Earned</p>
            </div>
            <div className="bg-white/10 rounded-lg p-3">
              <p className="text-2xl font-bold">101+</p>
              <p className="text-xs text-white/70">Surveys Daily</p>
            </div>
            <div className="bg-white/10 rounded-lg p-3">
              <p className="text-2xl font-bold">101+</p>
              <p className="text-xs text-white/70">Panelists Joined</p>
            </div>
          </div>
        </div>
      </section>
    </main>
  );
}
