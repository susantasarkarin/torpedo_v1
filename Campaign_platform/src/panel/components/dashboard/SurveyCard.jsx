/**
 * Survey Card Component
 * Displays a single survey with details and start button
 */

import { useState } from 'react';

export default function SurveyCard({ survey, onStart }) {
  const [loading, setLoading] = useState(false);

  const handleStart = async () => {
    setLoading(true);
    try {
      await onStart(survey.id);
    } catch (error) {
      console.error('Failed to start survey:', error);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="panel-survey-card">
      <div className="flex justify-between items-start mb-3">
        <div>
          <h3 className="font-semibold text-gray-800 text-lg">{survey.title}</h3>
          {survey.category && (
            <span className="text-xs text-panel-primary bg-panel-primary-50 px-2 py-0.5 rounded-full">
              {survey.category}
            </span>
          )}
        </div>
        <div className="text-right">
          <div className="text-panel-accent font-bold text-lg">₹{survey.reward_points}</div>
          <div className="text-xs text-gray-500">Reward</div>
        </div>
      </div>

      <p className="text-gray-600 text-sm mb-4 line-clamp-2">
        {survey.description || 'Complete this survey to earn reward points.'}
      </p>

      <div className="flex items-center justify-between">
        <div className="flex items-center gap-1 text-gray-500 text-sm">
          <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
          </svg>
          <span>{survey.estimated_time} min</span>
        </div>

        <button
          onClick={handleStart}
          disabled={loading}
          className="panel-btn-primary text-sm py-2 px-4"
        >
          {loading ? (
            <>
              <svg className="animate-spin w-4 h-4" fill="none" viewBox="0 0 24 24">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" />
              </svg>
              Starting...
            </>
          ) : (
            'Start Survey'
          )}
        </button>
      </div>
    </div>
  );
}
