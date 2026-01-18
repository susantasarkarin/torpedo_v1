/**
 * Panel Dashboard Page
 * Main dashboard showing available surveys and profile completion
 */

import { Link } from 'react-router-dom';
import { usePanelAuth } from '../context/PanelAuthContext';
import { useSurveys } from '../hooks/useSurveys';
import ProfileProgress from '../components/dashboard/ProfileProgress';
import SurveyCard from '../components/dashboard/SurveyCard';
import '../styles/panel.css';

export default function PanelDashboard() {
  const { profileCompletion, refreshProfileCompletion } = usePanelAuth();
  const { surveys, loading, error, startSurvey } = useSurveys();

  const handleStartSurvey = async (surveyId) => {
    try {
      const result = await startSurvey(surveyId);
      // If backend returns a redirect URL, navigate to it
      if (result.redirect_url) {
        window.open(result.redirect_url, '_blank');
      }
    } catch (err) {
      alert(err.message || 'Failed to start survey');
    }
  };

  return (
    <div className="panel-dashboard max-w-7xl mx-auto">
      {/* Main Content: Available Surveys */}
      <section className="bg-white rounded-xl shadow-sm border border-gray-100">
        <div className="p-6 border-b border-gray-100">
          <h2 className="text-xl font-semibold text-gray-800">Available Surveys</h2>
        </div>

        <div className="p-6">
          {loading ? (
            /* Loading State */
            <div className="space-y-4">
              {[1, 2, 3].map((i) => (
                <div key={i} className="animate-pulse">
                  <div className="h-24 bg-gray-100 rounded-lg"></div>
                </div>
              ))}
            </div>
          ) : error ? (
            /* Error State */
            <div className="panel-empty-state">
              <svg fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
              </svg>
              <h3 className="text-lg font-medium text-gray-800 mb-1">Something went wrong</h3>
              <p className="text-gray-500">{error}</p>
            </div>
          ) : surveys.length === 0 ? (
            /* Empty State */
            <div className="panel-empty-state">
              <svg fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2" />
              </svg>
              <h3 className="text-lg font-medium text-gray-800 mb-1">No Survey Available</h3>
              <p className="text-gray-500">
                Check back later for new surveys. We'll notify you when new surveys match your profile.
              </p>
            </div>
          ) : (
            /* Survey List */
            <div className="space-y-4">
              {surveys.map((survey) => (
                <SurveyCard
                  key={survey.id}
                  survey={survey}
                  onStart={handleStartSurvey}
                />
              ))}
            </div>
          )}
        </div>
      </section>

      {/* Sidebar: Profile */}
      <aside className="panel-profile-sidebar">
        <h3 className="text-xl font-semibold text-gray-800 mb-6">Profile</h3>

        {/* Profile Progress Ring */}
        <div className="mb-6">
          <ProfileProgress percentage={profileCompletion} />
        </div>

        {/* Edit Profile Button */}
        <Link
          to="/panel/profile"
          className="panel-btn-primary w-full"
        >
          Edit Profile Data
        </Link>

        {/* Profile Tip */}
        {profileCompletion < 100 && (
          <p className="mt-4 text-sm text-gray-500">
            Complete your profile to get more relevant surveys and earn more rewards!
          </p>
        )}
      </aside>
    </div>
  );
}
