/**
 * Agent Dashboard
 * 
 * Main dashboard for AI Lead Generation agents showing:
 * - Daily quota usage
 * - Active and completed jobs
 * - Quick run controls
 * - Results and analytics
 */

import React, { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { 
  Zap, Users, Clock, CheckCircle, XCircle, 
  Play, Pause, Settings, RefreshCw, Building2,
  TrendingUp, Mail, Target, AlertCircle, ChevronRight
} from 'lucide-react';
import { useLeadAgent } from '../../contexts/LeadAgentContext';
import { Button } from '../../components/ui/Button';
import { Card, CardHeader, CardTitle, CardContent } from '../../components/ui/Card';

// Status badge component
const StatusBadge = ({ status }) => {
  const statusConfig = {
    pending: { color: 'bg-gray-100 text-gray-700', icon: Clock },
    running: { color: 'bg-blue-100 text-blue-700', icon: Play },
    completed: { color: 'bg-green-100 text-green-700', icon: CheckCircle },
    failed: { color: 'bg-red-100 text-red-700', icon: XCircle },
  };
  
  const config = statusConfig[status] || statusConfig.pending;
  const Icon = config.icon;
  
  return (
    <span className={`inline-flex items-center gap-1 px-2 py-1 rounded-full text-xs font-medium ${config.color}`}>
      <Icon className="w-3 h-3" />
      {status}
    </span>
  );
};

// Progress bar component
const ProgressBar = ({ progress, className = '' }) => (
  <div className={`h-2 bg-gray-200 rounded-full overflow-hidden ${className}`}>
    <div 
      className="h-full bg-orange-500 transition-all duration-300"
      style={{ width: `${progress}%` }}
    />
  </div>
);

export default function AgentDashboard() {
  const navigate = useNavigate();
  const { 
    quota, 
    jobs, 
    fetchQuota, 
    fetchJobs, 
    runAgents, 
    cancelJob,
    isLoading 
  } = useLeadAgent();
  
  const [quickRunOpen, setQuickRunOpen] = useState(false);
  const [quickRunType, setQuickRunType] = useState('all');

  // Fetch data on mount
  useEffect(() => {
    fetchQuota();
    fetchJobs();
    
    // Refresh every 30 seconds
    const interval = setInterval(() => {
      fetchQuota();
      fetchJobs();
    }, 30000);
    
    return () => clearInterval(interval);
  }, [fetchQuota, fetchJobs]);

  // Calculate stats
  const stats = {
    totalJobs: jobs.length,
    activeJobs: jobs.filter(j => j.status === 'running').length,
    completedJobs: jobs.filter(j => j.status === 'completed').length,
    totalLeadsGenerated: jobs.reduce((sum, j) => sum + (j.result?.leads_generated || 0), 0),
  };

  // Handle quick run
  const handleQuickRun = async () => {
    try {
      await runAgents({
        run_type: quickRunType,
        batch_size: 10,
      });
      setQuickRunOpen(false);
      fetchJobs();
    } catch (err) {
      console.error('Quick run failed:', err);
    }
  };

  return (
    <div className="min-h-screen bg-gray-50 py-8">
      <div className="max-w-7xl mx-auto px-4">
        {/* Header */}
        <div className="flex items-center justify-between mb-8">
          <div>
            <h1 className="text-2xl font-bold text-gray-900">AI Agent Dashboard</h1>
            <p className="text-gray-600">Monitor and control your lead generation agents</p>
          </div>
          <div className="flex gap-3">
            <Button
              variant="outline"
              onClick={() => {
                fetchQuota();
                fetchJobs();
              }}
              loading={isLoading}
            >
              <RefreshCw className="w-4 h-4 mr-2" />
              Refresh
            </Button>
            <Button
              variant="outline"
              onClick={() => navigate('/sales/agent-settings')}
            >
              <Settings className="w-4 h-4 mr-2" />
              Settings
            </Button>
            <Button
              variant="primary"
              onClick={() => navigate('/sales/company-upload')}
            >
              <Building2 className="w-4 h-4 mr-2" />
              Upload Companies
            </Button>
          </div>
        </div>

        {/* Stats Grid */}
        <div className="grid grid-cols-1 md:grid-cols-4 gap-4 mb-8">
          {/* Quota Card */}
          <Card>
            <CardContent className="pt-6">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-sm text-gray-500">Daily Quota</p>
                  <p className="text-2xl font-bold text-gray-900">
                    {quota.leads_today} / {quota.limit}
                  </p>
                </div>
                <div className="p-3 bg-orange-100 rounded-full">
                  <Target className="w-6 h-6 text-orange-600" />
                </div>
              </div>
              <ProgressBar 
                progress={(quota.leads_today / quota.limit) * 100} 
                className="mt-4"
              />
              <p className="text-xs text-gray-500 mt-2">
                {quota.remaining} leads remaining today
              </p>
            </CardContent>
          </Card>

          {/* Active Jobs */}
          <Card>
            <CardContent className="pt-6">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-sm text-gray-500">Active Jobs</p>
                  <p className="text-2xl font-bold text-gray-900">{stats.activeJobs}</p>
                </div>
                <div className="p-3 bg-blue-100 rounded-full">
                  <Zap className="w-6 h-6 text-blue-600" />
                </div>
              </div>
              <p className="text-xs text-gray-500 mt-4">
                {stats.completedJobs} completed today
              </p>
            </CardContent>
          </Card>

          {/* Leads Generated */}
          <Card>
            <CardContent className="pt-6">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-sm text-gray-500">Leads Generated</p>
                  <p className="text-2xl font-bold text-gray-900">{stats.totalLeadsGenerated}</p>
                </div>
                <div className="p-3 bg-green-100 rounded-full">
                  <Users className="w-6 h-6 text-green-600" />
                </div>
              </div>
              <p className="text-xs text-gray-500 mt-4">
                From {stats.totalJobs} total jobs
              </p>
            </CardContent>
          </Card>

          {/* Quick Run */}
          <Card className="cursor-pointer hover:shadow-md transition-shadow" onClick={() => setQuickRunOpen(true)}>
            <CardContent className="pt-6">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-sm text-gray-500">Quick Run</p>
                  <p className="text-lg font-bold text-gray-900">Start Agents</p>
                </div>
                <div className="p-3 bg-purple-100 rounded-full">
                  <Play className="w-6 h-6 text-purple-600" />
                </div>
              </div>
              <p className="text-xs text-gray-500 mt-4">
                Click to run lead generation
              </p>
            </CardContent>
          </Card>
        </div>

        {/* Active Jobs */}
        {stats.activeJobs > 0 && (
          <Card className="mb-8">
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <Zap className="w-5 h-5 text-blue-600" />
                Active Jobs
              </CardTitle>
            </CardHeader>
            <CardContent>
              <div className="space-y-4">
                {jobs.filter(j => j.status === 'running').map((job) => (
                  <div key={job.job_id} className="p-4 bg-blue-50 rounded-lg">
                    <div className="flex items-center justify-between mb-2">
                      <div>
                        <span className="font-medium text-gray-900">{job.agent_name}</span>
                        <StatusBadge status={job.status} />
                      </div>
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => cancelJob(job.job_id)}
                      >
                        <Pause className="w-4 h-4" />
                      </Button>
                    </div>
                    <ProgressBar progress={job.progress || 0} />
                    <div className="flex justify-between mt-2 text-sm text-gray-600">
                      <span>{job.current_step || 'Processing...'}</span>
                      <span>{job.progress || 0}%</span>
                    </div>
                  </div>
                ))}
              </div>
            </CardContent>
          </Card>
        )}

        {/* Recent Jobs Table */}
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Clock className="w-5 h-5" />
              Recent Jobs
            </CardTitle>
          </CardHeader>
          <CardContent>
            {jobs.length === 0 ? (
              <div className="text-center py-12">
                <Zap className="w-12 h-12 mx-auto text-gray-400 mb-4" />
                <h3 className="text-lg font-medium text-gray-900 mb-2">No jobs yet</h3>
                <p className="text-gray-500 mb-4">
                  Upload companies or run agents to get started
                </p>
                <Button
                  variant="primary"
                  onClick={() => navigate('/sales/company-upload')}
                >
                  Upload Companies
                </Button>
              </div>
            ) : (
              <div className="overflow-x-auto">
                <table className="min-w-full divide-y divide-gray-200">
                  <thead className="bg-gray-50">
                    <tr>
                      <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Job ID</th>
                      <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Agent</th>
                      <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Status</th>
                      <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Progress</th>
                      <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Leads</th>
                      <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Started</th>
                      <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Actions</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-200">
                    {jobs.slice(0, 20).map((job) => (
                      <tr key={job.job_id} className="hover:bg-gray-50">
                        <td className="px-4 py-3">
                          <code className="text-xs text-gray-600">
                            {job.job_id.slice(0, 8)}...
                          </code>
                        </td>
                        <td className="px-4 py-3 font-medium text-gray-900">
                          {job.agent_name || 'Pipeline'}
                        </td>
                        <td className="px-4 py-3">
                          <StatusBadge status={job.status} />
                        </td>
                        <td className="px-4 py-3">
                          <div className="w-24">
                            <ProgressBar progress={job.progress || 0} />
                          </div>
                        </td>
                        <td className="px-4 py-3 text-gray-600">
                          {job.result?.leads_generated || '-'}
                        </td>
                        <td className="px-4 py-3 text-sm text-gray-500">
                          {job.started_at ? new Date(job.started_at).toLocaleTimeString() : '-'}
                        </td>
                        <td className="px-4 py-3">
                          <button className="text-orange-600 hover:text-orange-700">
                            <ChevronRight className="w-4 h-4" />
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </CardContent>
        </Card>

        {/* Quick Run Modal */}
        {quickRunOpen && (
          <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
            <Card className="w-full max-w-md mx-4">
              <CardHeader>
                <CardTitle>Quick Run Agents</CardTitle>
              </CardHeader>
              <CardContent>
                <div className="space-y-4">
                  <div>
                    <label className="block text-sm font-medium text-gray-700 mb-2">
                      Run Type
                    </label>
                    <select
                      value={quickRunType}
                      onChange={(e) => setQuickRunType(e.target.value)}
                      className="w-full border border-gray-300 rounded-md px-3 py-2"
                    >
                      <option value="all">Full Pipeline (All Agents)</option>
                      <option value="discovery">Company Discovery Only</option>
                      <option value="contacts">Contact Finder Only</option>
                      <option value="enrich">Lead Enricher Only</option>
                      <option value="score">Lead Scorer Only</option>
                      <option value="outreach">Outreach Composer Only</option>
                    </select>
                  </div>

                  {quota.remaining < 10 && (
                    <div className="p-3 bg-yellow-50 border border-yellow-200 rounded-lg flex items-start gap-2">
                      <AlertCircle className="w-5 h-5 text-yellow-600 flex-shrink-0 mt-0.5" />
                      <div>
                        <p className="text-sm text-yellow-800 font-medium">Low Quota</p>
                        <p className="text-xs text-yellow-600">
                          Only {quota.remaining} leads remaining today
                        </p>
                      </div>
                    </div>
                  )}

                  <div className="flex gap-3 pt-4">
                    <Button
                      variant="outline"
                      className="flex-1"
                      onClick={() => setQuickRunOpen(false)}
                    >
                      Cancel
                    </Button>
                    <Button
                      variant="primary"
                      className="flex-1"
                      onClick={handleQuickRun}
                      loading={isLoading}
                      disabled={quota.remaining === 0}
                    >
                      <Play className="w-4 h-4 mr-2" />
                      Run Agents
                    </Button>
                  </div>
                </div>
              </CardContent>
            </Card>
          </div>
        )}
      </div>
    </div>
  );
}
