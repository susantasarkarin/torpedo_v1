/**
 * Panel Profile Page
 * Editable profile form for panelists
 */

import { useState, useEffect } from 'react';
import { usePanelAuth } from '../context/PanelAuthContext';
import { getProfile, updateProfile } from '../services/panelApi';
import ProfileProgress from '../components/dashboard/ProfileProgress';
import '../styles/panel.css';

const COUNTRIES = [
  'India', 'United States', 'United Kingdom', 'Canada', 'Australia',
  'Germany', 'France', 'Brazil', 'Mexico', 'Japan', 'South Korea',
  'Singapore', 'Malaysia', 'Philippines', 'Indonesia', 'Thailand',
  'Vietnam', 'South Africa', 'Nigeria', 'Kenya', 'Egypt',
  'United Arab Emirates', 'Saudi Arabia', 'Other'
];

const LANGUAGES = ['English', 'Hindi', 'Spanish', 'French', 'German', 'Portuguese', 'Japanese', 'Korean', 'Chinese', 'Arabic', 'Other'];
const GENDERS = ['Male', 'Female', 'Other', 'Prefer not to say'];
const EDUCATION_LEVELS = ['High School', 'Some College', 'Bachelor\'s Degree', 'Master\'s Degree', 'Doctorate', 'Other'];
const INCOME_RANGES = ['Under ₹2.5 Lakh', '₹2.5 - 5 Lakh', '₹5 - 10 Lakh', '₹10 - 20 Lakh', 'Above ₹20 Lakh', 'Prefer not to say'];

export default function PanelProfile() {
  const { profileCompletion, refreshProfileCompletion, updatePanelistData } = usePanelAuth();
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [success, setSuccess] = useState(false);
  const [error, setError] = useState('');
  const [profile, setProfile] = useState({
    first_name: '',
    last_name: '',
    email: '',
    phone: '',
    date_of_birth: '',
    gender: '',
    address: '',
    city: '',
    postal_code: '',
    country: '',
    language: '',
    occupation: '',
    education: '',
    income_range: '',
  });

  useEffect(() => {
    loadProfile();
  }, []);

  const loadProfile = async () => {
    setLoading(true);
    try {
      const data = await getProfile();
      setProfile({
        first_name: data.first_name || '',
        last_name: data.last_name || '',
        email: data.email || '',
        phone: data.phone || '',
        date_of_birth: data.date_of_birth || '',
        gender: data.gender || '',
        address: data.address || '',
        city: data.city || '',
        postal_code: data.postal_code || '',
        country: data.country || '',
        language: data.language || '',
        occupation: data.occupation || '',
        education: data.education || '',
        income_range: data.income_range || '',
      });
    } catch (err) {
      setError('Failed to load profile');
    } finally {
      setLoading(false);
    }
  };

  const handleChange = (e) => {
    const { name, value } = e.target;
    setProfile(prev => ({ ...prev, [name]: value }));
    setSuccess(false);
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (saving) return;

    setSaving(true);
    setError('');
    setSuccess(false);

    try {
      const result = await updateProfile(profile);
      setSuccess(true);
      // Update local auth context
      updatePanelistData({
        firstName: profile.first_name,
        lastName: profile.last_name,
      });
      // Refresh completion percentage
      await refreshProfileCompletion();
    } catch (err) {
      setError(err.message || 'Failed to update profile');
    } finally {
      setSaving(false);
    }
  };

  if (loading) {
    return (
      <div className="max-w-4xl mx-auto p-6">
        <div className="animate-pulse space-y-4">
          <div className="h-8 bg-gray-200 rounded w-1/4"></div>
          <div className="h-64 bg-gray-200 rounded"></div>
        </div>
      </div>
    );
  }

  return (
    <div className="max-w-4xl mx-auto p-6">
      <div className="bg-white rounded-xl shadow-sm border border-gray-100">
        {/* Header */}
        <div className="p-6 border-b border-gray-100 flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-semibold text-gray-800">My Profile</h1>
            <p className="text-gray-500 text-sm mt-1">
              Complete your profile to receive more relevant surveys
            </p>
          </div>
          <ProfileProgress percentage={profileCompletion} size={80} />
        </div>

        {/* Form */}
        <form onSubmit={handleSubmit} className="p-6">
          {/* Messages */}
          {error && (
            <div className="mb-6 p-3 bg-red-50 border border-red-200 text-red-600 rounded-lg text-sm">
              {error}
            </div>
          )}
          {success && (
            <div className="mb-6 p-3 bg-green-50 border border-green-200 text-green-600 rounded-lg text-sm">
              Profile updated successfully!
            </div>
          )}

          {/* Personal Information */}
          <div className="mb-8">
            <h3 className="text-lg font-medium text-gray-800 mb-4">Personal Information</h3>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div className="panel-form-group">
                <label className="panel-form-label">First Name</label>
                <input
                  type="text"
                  name="first_name"
                  className="panel-form-input"
                  value={profile.first_name}
                  onChange={handleChange}
                />
              </div>
              <div className="panel-form-group">
                <label className="panel-form-label">Last Name</label>
                <input
                  type="text"
                  name="last_name"
                  className="panel-form-input"
                  value={profile.last_name}
                  onChange={handleChange}
                />
              </div>
              <div className="panel-form-group">
                <label className="panel-form-label">Email</label>
                <input
                  type="email"
                  name="email"
                  className="panel-form-input bg-gray-50"
                  value={profile.email}
                  disabled
                />
              </div>
              <div className="panel-form-group">
                <label className="panel-form-label">Phone</label>
                <input
                  type="tel"
                  name="phone"
                  className="panel-form-input"
                  placeholder="+91 98765 43210"
                  value={profile.phone}
                  onChange={handleChange}
                />
              </div>
              <div className="panel-form-group">
                <label className="panel-form-label">Date of Birth</label>
                <input
                  type="date"
                  name="date_of_birth"
                  className="panel-form-input"
                  value={profile.date_of_birth}
                  onChange={handleChange}
                />
              </div>
              <div className="panel-form-group">
                <label className="panel-form-label">Gender</label>
                <select
                  name="gender"
                  className="panel-form-input panel-form-select"
                  value={profile.gender}
                  onChange={handleChange}
                >
                  <option value="">Select Gender</option>
                  {GENDERS.map(g => <option key={g} value={g}>{g}</option>)}
                </select>
              </div>
            </div>
          </div>

          {/* Location */}
          <div className="mb-8">
            <h3 className="text-lg font-medium text-gray-800 mb-4">Location</h3>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div className="panel-form-group md:col-span-2">
                <label className="panel-form-label">Address</label>
                <input
                  type="text"
                  name="address"
                  className="panel-form-input"
                  placeholder="Street address"
                  value={profile.address}
                  onChange={handleChange}
                />
              </div>
              <div className="panel-form-group">
                <label className="panel-form-label">City</label>
                <input
                  type="text"
                  name="city"
                  className="panel-form-input"
                  value={profile.city}
                  onChange={handleChange}
                />
              </div>
              <div className="panel-form-group">
                <label className="panel-form-label">Postal Code</label>
                <input
                  type="text"
                  name="postal_code"
                  className="panel-form-input"
                  value={profile.postal_code}
                  onChange={handleChange}
                />
              </div>
              <div className="panel-form-group">
                <label className="panel-form-label">Country</label>
                <select
                  name="country"
                  className="panel-form-input panel-form-select"
                  value={profile.country}
                  onChange={handleChange}
                >
                  <option value="">Select Country</option>
                  {COUNTRIES.map(c => <option key={c} value={c}>{c}</option>)}
                </select>
              </div>
              <div className="panel-form-group">
                <label className="panel-form-label">Language</label>
                <select
                  name="language"
                  className="panel-form-input panel-form-select"
                  value={profile.language}
                  onChange={handleChange}
                >
                  <option value="">Select Language</option>
                  {LANGUAGES.map(l => <option key={l} value={l}>{l}</option>)}
                </select>
              </div>
            </div>
          </div>

          {/* Demographics */}
          <div className="mb-8">
            <h3 className="text-lg font-medium text-gray-800 mb-4">Demographics</h3>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div className="panel-form-group">
                <label className="panel-form-label">Occupation</label>
                <input
                  type="text"
                  name="occupation"
                  className="panel-form-input"
                  placeholder="e.g. Software Engineer"
                  value={profile.occupation}
                  onChange={handleChange}
                />
              </div>
              <div className="panel-form-group">
                <label className="panel-form-label">Education</label>
                <select
                  name="education"
                  className="panel-form-input panel-form-select"
                  value={profile.education}
                  onChange={handleChange}
                >
                  <option value="">Select Education Level</option>
                  {EDUCATION_LEVELS.map(e => <option key={e} value={e}>{e}</option>)}
                </select>
              </div>
              <div className="panel-form-group">
                <label className="panel-form-label">Annual Income Range</label>
                <select
                  name="income_range"
                  className="panel-form-input panel-form-select"
                  value={profile.income_range}
                  onChange={handleChange}
                >
                  <option value="">Select Income Range</option>
                  {INCOME_RANGES.map(i => <option key={i} value={i}>{i}</option>)}
                </select>
              </div>
            </div>
          </div>

          {/* Submit Button */}
          <div className="flex justify-end pt-4 border-t border-gray-100">
            <button
              type="submit"
              disabled={saving}
              className="panel-btn-primary py-3 px-8"
            >
              {saving ? 'Saving...' : 'Save Changes'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
