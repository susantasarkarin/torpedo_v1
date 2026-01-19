/**
 * Agent Progress Component
 * 
 * Fixed bottom-right floating panel that shows real-time progress
 * of running agent jobs. Displays:
 * - Active job count
 * - Individual job progress bars
 * - Completion notifications
 * 
 * Can be minimized when not needed.
 */

import React, { useState, useEffect } from 'react';
import { 
  Zap, ChevronDown, ChevronUp, X, CheckCircle, 
  AlertCircle, Clock, Loader2
} from 'lucide-react';
import { useLeadAgent } from '../contexts/LeadAgentContext';

// Progress bar component
const ProgressBar = ({ progress, status }) => {
  const getColor = () => {
    switch (status) {
      case 'completed': return 'bg-green-500';
      case 'failed': return 'bg-red-500';
      default: return 'bg-orange-500';
    }
  };

  return (
    <div className="h-1.5 bg-gray-200 rounded-full overflow-hidden">
      <div 
        className={`h-full transition-all duration-500 ${getColor()}`}
        style={{ width: `${progress}%` }}
      />
    </div>
  );
};

// Individual job item
const JobItem = ({ job, onDismiss }) => {
  const getStatusIcon = () => {
    switch (job.status) {
      case 'completed':
        return <CheckCircle className="w-4 h-4 text-green-500" />;
      case 'failed':
        return <AlertCircle className="w-4 h-4 text-red-500" />;
      case 'running':
        return <Loader2 className="w-4 h-4 text-orange-500 animate-spin" />;
      default:
        return <Clock className="w-4 h-4 text-gray-400" />;
    }
  };

  return (
    <div className="p-3 bg-gray-50 rounded-lg">
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-2">
          {getStatusIcon()}
          <span className="font-medium text-sm text-gray-900">
            {job.agent_name || 'Agent Pipeline'}
          </span>
        </div>
        {(job.status === 'completed' || job.status === 'failed') && (
          <button
            onClick={() => onDismiss(job.job_id)}
            className="text-gray-400 hover:text-gray-600"
          >
            <X className="w-4 h-4" />
          </button>
        )}
      </div>
      
      <ProgressBar progress={job.progress || 0} status={job.status} />
      
      <div className="flex justify-between mt-2">
        <span className="text-xs text-gray-500">
          {job.current_step || job.status}
        </span>
        <span className="text-xs font-medium text-gray-700">
          {job.progress || 0}%
        </span>
      </div>
      
      {job.status === 'completed' && job.result && (
        <div className="mt-2 text-xs text-green-600">
          ✓ {job.result.leads_generated || 0} leads generated
        </div>
      )}
      
      {job.status === 'failed' && job.error && (
        <div className="mt-2 text-xs text-red-600">
          Error: {job.error}
        </div>
      )}
    </div>
  );
};

export default function AgentProgress() {
  const { jobs, fetchJobs } = useLeadAgent();
  const [isMinimized, setIsMinimized] = useState(false);
  const [dismissedJobs, setDismissedJobs] = useState(new Set());
  const [notifications, setNotifications] = useState([]);

  // Filter active and recent jobs
  const activeJobs = jobs.filter(j => 
    j.status === 'running' || j.status === 'pending'
  );
  
  const recentJobs = jobs.filter(j => 
    (j.status === 'completed' || j.status === 'failed') &&
    !dismissedJobs.has(j.job_id) &&
    // Only show jobs from the last 5 minutes
    new Date(j.completed_at || j.started_at) > new Date(Date.now() - 5 * 60 * 1000)
  );

  const displayJobs = [...activeJobs, ...recentJobs].slice(0, 5);
  const hasActiveJobs = activeJobs.length > 0;

  // Poll for updates when jobs are active
  useEffect(() => {
    if (!hasActiveJobs) return;
    
    const interval = setInterval(() => {
      fetchJobs();
    }, 3000);
    
    return () => clearInterval(interval);
  }, [hasActiveJobs, fetchJobs]);

  // Track completions for notifications
  useEffect(() => {
    const previouslyRunning = new Set(
      notifications.filter(n => n.status === 'running').map(n => n.job_id)
    );
    
    jobs.forEach(job => {
      if (job.status === 'completed' && previouslyRunning.has(job.job_id)) {
        // Job just completed - could trigger a toast notification here
        console.log(`Job ${job.job_id} completed!`);
      }
    });
    
    setNotifications(jobs);
  }, [jobs]);

  // Dismiss a job from the list
  const handleDismiss = (jobId) => {
    setDismissedJobs(prev => new Set([...prev, jobId]));
  };

  // Don't render if no jobs to show
  if (displayJobs.length === 0) {
    return null;
  }

  return (
    <div 
      className={`fixed bottom-4 right-4 z-50 transition-all duration-300 ${
        isMinimized ? 'w-auto' : 'w-80'
      }`}
    >
      {/* Minimized State */}
      {isMinimized ? (
        <button
          onClick={() => setIsMinimized(false)}
          className={`flex items-center gap-2 px-4 py-3 rounded-full shadow-lg ${
            hasActiveJobs 
              ? 'bg-orange-500 text-white animate-pulse' 
              : 'bg-white text-gray-700'
          }`}
        >
          <Zap className="w-5 h-5" />
          <span className="font-medium">
            {hasActiveJobs ? `${activeJobs.length} Running` : 'View Jobs'}
          </span>
          <ChevronUp className="w-4 h-4" />
        </button>
      ) : (
        /* Expanded State */
        <div className="bg-white rounded-lg shadow-xl border border-gray-200 overflow-hidden">
          {/* Header */}
          <div className="flex items-center justify-between px-4 py-3 bg-gray-50 border-b">
            <div className="flex items-center gap-2">
              <Zap className={`w-5 h-5 ${hasActiveJobs ? 'text-orange-500' : 'text-gray-400'}`} />
              <span className="font-semibold text-gray-900">
                Agent Jobs
              </span>
              {hasActiveJobs && (
                <span className="px-2 py-0.5 text-xs font-medium bg-orange-100 text-orange-700 rounded-full">
                  {activeJobs.length} active
                </span>
              )}
            </div>
            <button
              onClick={() => setIsMinimized(true)}
              className="text-gray-400 hover:text-gray-600"
            >
              <ChevronDown className="w-5 h-5" />
            </button>
          </div>

          {/* Jobs List */}
          <div className="p-3 space-y-2 max-h-96 overflow-y-auto">
            {displayJobs.length === 0 ? (
              <div className="text-center py-6 text-gray-500">
                <Zap className="w-8 h-8 mx-auto text-gray-300 mb-2" />
                <p className="text-sm">No active jobs</p>
              </div>
            ) : (
              displayJobs.map(job => (
                <JobItem 
                  key={job.job_id} 
                  job={job} 
                  onDismiss={handleDismiss}
                />
              ))
            )}
          </div>

          {/* Footer */}
          {activeJobs.length > 5 && (
            <div className="px-4 py-2 bg-gray-50 border-t text-center">
              <span className="text-xs text-gray-500">
                +{activeJobs.length - 5} more jobs running
              </span>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
