// Campaign_platform/src/pages/Projects.jsx
// Project Management Page

import { useState, useEffect, useCallback } from 'react';
import { 
  FolderKanban, Plus, Search, Filter, Calendar, Users, 
  Clock, CheckCircle2, AlertCircle, MoreVertical, Trash2,
  Edit, Eye, Archive, TrendingUp, Target, DollarSign
} from 'lucide-react';
import { PageLayout, PageHeader } from '../components/ui/PageLayout';
import { Card } from '../components/ui/Card';
import { Button } from '../components/ui/Button';
import { Badge } from '../components/ui/Badge';
import { Modal } from '../components/ui/Modal';
import { FormField } from '../components/ui/FormField';
import { ConfirmDialog } from '../components/ui/ConfirmDialog';
import { EmptyState } from '../components/ui/EmptyState';
import { Skeleton } from '../components/ui/Skeleton';
import { ActivityTimeline } from '../components/ui/ActivityTimeline';
import { Table } from '../components/ui/Table';
import api from '../utils/api';

const STATUS_COLORS = {
  planning: 'bg-gray-100 text-gray-800',
  active: 'bg-green-100 text-green-800',
  on_hold: 'bg-yellow-100 text-yellow-800',
  completed: 'bg-blue-100 text-blue-800',
  cancelled: 'bg-red-100 text-red-800'
};

const PRIORITY_COLORS = {
  low: 'bg-gray-100 text-gray-600',
  medium: 'bg-blue-100 text-blue-700',
  high: 'bg-orange-100 text-orange-700',
  critical: 'bg-red-100 text-red-700'
};

const STATUS_OPTIONS = [
  { value: 'planning', label: 'Planning' },
  { value: 'active', label: 'Active' },
  { value: 'on_hold', label: 'On Hold' },
  { value: 'completed', label: 'Completed' },
  { value: 'cancelled', label: 'Cancelled' }
];

const PRIORITY_OPTIONS = [
  { value: 'low', label: 'Low' },
  { value: 'medium', label: 'Medium' },
  { value: 'high', label: 'High' },
  { value: 'critical', label: 'Critical' }
];

export default function Projects() {
  const [projects, setProjects] = useState([]);
  const [stats, setStats] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  
  // Filters
  const [filters, setFilters] = useState({
    status: '',
    priority: '',
    search: ''
  });
  
  // Modal states
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [showDetailModal, setShowDetailModal] = useState(false);
  const [selectedProject, setSelectedProject] = useState(null);
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false);
  
  // Form state
  const [formData, setFormData] = useState({
    name: '',
    description: '',
    priority: 'medium',
    start_date: '',
    target_end_date: '',
    budget: 0,
    tags: []
  });
  const [formErrors, setFormErrors] = useState({});
  const [submitting, setSubmitting] = useState(false);

  // Fetch projects
  const fetchProjects = useCallback(async () => {
    try {
      setLoading(true);
      const params = new URLSearchParams();
      if (filters.status) params.append('status', filters.status);
      if (filters.priority) params.append('priority', filters.priority);
      
      const response = await api.get(`/api/projects?${params}`);
      if (response.data.success) {
        let items = response.data.items || [];
        
        // Client-side search filter
        if (filters.search) {
          const searchLower = filters.search.toLowerCase();
          items = items.filter(p => 
            p.name?.toLowerCase().includes(searchLower) ||
            p.code?.toLowerCase().includes(searchLower) ||
            p.description?.toLowerCase().includes(searchLower)
          );
        }
        
        setProjects(items);
      }
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }, [filters]);

  // Fetch stats
  const fetchStats = useCallback(async () => {
    try {
      const response = await api.get('/api/projects/stats');
      if (response.data.success) {
        setStats(response.data.data);
      }
    } catch (err) {
      console.error('Failed to fetch stats:', err);
    }
  }, []);

  useEffect(() => {
    fetchProjects();
    fetchStats();
  }, [fetchProjects, fetchStats]);

  // Handle form submit
  const handleSubmit = async (e) => {
    e.preventDefault();
    
    // Validation
    const errors = {};
    if (!formData.name?.trim()) errors.name = 'Project name is required';
    
    if (Object.keys(errors).length > 0) {
      setFormErrors(errors);
      return;
    }
    
    try {
      setSubmitting(true);
      
      const payload = {
        ...formData,
        start_date: formData.start_date ? new Date(formData.start_date).toISOString() : null,
        target_end_date: formData.target_end_date ? new Date(formData.target_end_date).toISOString() : null
      };
      
      if (selectedProject) {
        await api.put(`/api/projects/${selectedProject.id}`, payload);
      } else {
        await api.post('/api/projects', payload);
      }
      
      setShowCreateModal(false);
      resetForm();
      fetchProjects();
      fetchStats();
    } catch (err) {
      setFormErrors({ submit: err.response?.data?.detail || err.message });
    } finally {
      setSubmitting(false);
    }
  };

  // Handle delete
  const handleDelete = async () => {
    if (!selectedProject) return;
    
    try {
      await api.delete(`/api/projects/${selectedProject.id}`);
      setShowDeleteConfirm(false);
      setSelectedProject(null);
      fetchProjects();
      fetchStats();
    } catch (err) {
      setError(err.message);
    }
  };

  // Handle archive
  const handleArchive = async (project) => {
    try {
      await api.post(`/api/projects/${project.id}/archive`);
      fetchProjects();
      fetchStats();
    } catch (err) {
      setError(err.message);
    }
  };

  // Reset form
  const resetForm = () => {
    setFormData({
      name: '',
      description: '',
      priority: 'medium',
      start_date: '',
      target_end_date: '',
      budget: 0,
      tags: []
    });
    setFormErrors({});
    setSelectedProject(null);
  };

  // Open edit modal
  const openEditModal = (project) => {
    setSelectedProject(project);
    setFormData({
      name: project.name || '',
      description: project.description || '',
      priority: project.priority || 'medium',
      start_date: project.start_date ? project.start_date.split('T')[0] : '',
      target_end_date: project.target_end_date ? project.target_end_date.split('T')[0] : '',
      budget: project.budget || 0,
      tags: project.tags || []
    });
    setShowCreateModal(true);
  };

  // Render stats cards
  const renderStats = () => {
    if (!stats) return null;
    
    return (
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4 mb-6">
        <Card className="p-4">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-sm text-gray-500">Total Projects</p>
              <p className="text-2xl font-bold">{stats.total_projects}</p>
            </div>
            <FolderKanban className="w-8 h-8 text-blue-500" />
          </div>
        </Card>
        
        <Card className="p-4">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-sm text-gray-500">Active Projects</p>
              <p className="text-2xl font-bold text-green-600">{stats.active_projects}</p>
            </div>
            <TrendingUp className="w-8 h-8 text-green-500" />
          </div>
        </Card>
        
        <Card className="p-4">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-sm text-gray-500">Completed Tasks</p>
              <p className="text-2xl font-bold">{stats.completed_tasks} / {stats.total_tasks}</p>
            </div>
            <CheckCircle2 className="w-8 h-8 text-blue-500" />
          </div>
        </Card>
        
        <Card className="p-4">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-sm text-gray-500">Budget Spent</p>
              <p className="text-2xl font-bold">${stats.total_spent?.toLocaleString()}</p>
              <p className="text-xs text-gray-400">of ${stats.total_budget?.toLocaleString()}</p>
            </div>
            <DollarSign className="w-8 h-8 text-green-500" />
          </div>
        </Card>
      </div>
    );
  };

  // Render project card
  const renderProjectCard = (project) => (
    <Card key={project.id} className="p-4 hover:shadow-lg transition-shadow">
      <div className="flex justify-between items-start mb-3">
        <div>
          <div className="flex items-center gap-2 mb-1">
            <span className="text-xs text-gray-400 font-mono">{project.code}</span>
            <Badge className={STATUS_COLORS[project.status] || 'bg-gray-100'}>
              {project.status?.replace('_', ' ')}
            </Badge>
          </div>
          <h3 className="font-semibold text-lg">{project.name}</h3>
        </div>
        <Badge className={PRIORITY_COLORS[project.priority] || 'bg-gray-100'}>
          {project.priority}
        </Badge>
      </div>
      
      {project.description && (
        <p className="text-sm text-gray-600 mb-3 line-clamp-2">{project.description}</p>
      )}
      
      {/* Progress bar */}
      <div className="mb-3">
        <div className="flex justify-between text-xs text-gray-500 mb-1">
          <span>Progress</span>
          <span>{project.progress_percent || 0}%</span>
        </div>
        <div className="w-full bg-gray-200 rounded-full h-2">
          <div 
            className="bg-blue-600 h-2 rounded-full transition-all"
            style={{ width: `${project.progress_percent || 0}%` }}
          />
        </div>
      </div>
      
      {/* Info row */}
      <div className="flex items-center gap-4 text-sm text-gray-500 mb-3">
        <div className="flex items-center gap-1">
          <Target className="w-4 h-4" />
          <span>{project.completed_tasks || 0}/{project.total_tasks || 0} tasks</span>
        </div>
        {project.target_end_date && (
          <div className="flex items-center gap-1">
            <Calendar className="w-4 h-4" />
            <span>{new Date(project.target_end_date).toLocaleDateString()}</span>
          </div>
        )}
      </div>
      
      {/* Team members */}
      {project.team_members?.length > 0 && (
        <div className="flex items-center gap-1 mb-3">
          <Users className="w-4 h-4 text-gray-400" />
          <div className="flex -space-x-2">
            {project.team_members.slice(0, 3).map((member, idx) => (
              <div 
                key={idx}
                className="w-6 h-6 rounded-full bg-blue-500 text-white text-xs flex items-center justify-center border-2 border-white"
                title={member.user_name}
              >
                {member.user_name?.[0] || '?'}
              </div>
            ))}
            {project.team_members.length > 3 && (
              <div className="w-6 h-6 rounded-full bg-gray-300 text-gray-600 text-xs flex items-center justify-center border-2 border-white">
                +{project.team_members.length - 3}
              </div>
            )}
          </div>
        </div>
      )}
      
      {/* Actions */}
      <div className="flex justify-end gap-2 pt-2 border-t">
        <Button 
          variant="ghost" 
          size="sm"
          onClick={() => {
            setSelectedProject(project);
            setShowDetailModal(true);
          }}
        >
          <Eye className="w-4 h-4" />
        </Button>
        <Button 
          variant="ghost" 
          size="sm"
          onClick={() => openEditModal(project)}
        >
          <Edit className="w-4 h-4" />
        </Button>
        <Button 
          variant="ghost" 
          size="sm"
          onClick={() => handleArchive(project)}
        >
          <Archive className="w-4 h-4" />
        </Button>
        <Button 
          variant="ghost" 
          size="sm"
          onClick={() => {
            setSelectedProject(project);
            setShowDeleteConfirm(true);
          }}
        >
          <Trash2 className="w-4 h-4 text-red-500" />
        </Button>
      </div>
    </Card>
  );

  return (
    <PageLayout>
      <PageHeader
        title="Projects"
        subtitle="Manage your projects and tasks"
        icon={<FolderKanban className="w-6 h-6" />}
        actions={
          <Button onClick={() => setShowCreateModal(true)}>
            <Plus className="w-4 h-4 mr-2" />
            New Project
          </Button>
        }
      />
      
      {/* Stats */}
      {renderStats()}
      
      {/* Filters */}
      <Card className="p-4 mb-6">
        <div className="flex flex-wrap gap-4">
          <div className="flex-1 min-w-[200px]">
            <div className="relative">
              <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 w-4 h-4 text-gray-400" />
              <input
                type="text"
                placeholder="Search projects..."
                className="w-full pl-10 pr-4 py-2 border rounded-lg"
                value={filters.search}
                onChange={(e) => setFilters(f => ({ ...f, search: e.target.value }))}
              />
            </div>
          </div>
          
          <select
            className="px-4 py-2 border rounded-lg"
            value={filters.status}
            onChange={(e) => setFilters(f => ({ ...f, status: e.target.value }))}
          >
            <option value="">All Statuses</option>
            {STATUS_OPTIONS.map(opt => (
              <option key={opt.value} value={opt.value}>{opt.label}</option>
            ))}
          </select>
          
          <select
            className="px-4 py-2 border rounded-lg"
            value={filters.priority}
            onChange={(e) => setFilters(f => ({ ...f, priority: e.target.value }))}
          >
            <option value="">All Priorities</option>
            {PRIORITY_OPTIONS.map(opt => (
              <option key={opt.value} value={opt.value}>{opt.label}</option>
            ))}
          </select>
        </div>
      </Card>
      
      {/* Project Grid */}
      {loading ? (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {[1, 2, 3, 4, 5, 6].map(i => (
            <Card key={i} className="p-4">
              <Skeleton className="h-6 w-1/3 mb-2" />
              <Skeleton className="h-4 w-full mb-4" />
              <Skeleton className="h-2 w-full mb-2" />
              <Skeleton className="h-4 w-2/3" />
            </Card>
          ))}
        </div>
      ) : error ? (
        <Card className="p-8 text-center">
          <AlertCircle className="w-12 h-12 text-red-500 mx-auto mb-4" />
          <p className="text-red-600">{error}</p>
        </Card>
      ) : projects.length === 0 ? (
        <EmptyState
          icon={<FolderKanban className="w-12 h-12" />}
          title="No projects found"
          description="Get started by creating your first project"
          action={
            <Button onClick={() => setShowCreateModal(true)}>
              <Plus className="w-4 h-4 mr-2" />
              Create Project
            </Button>
          }
        />
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {projects.map(renderProjectCard)}
        </div>
      )}
      
      {/* Create/Edit Modal */}
      <Modal
        isOpen={showCreateModal}
        onClose={() => {
          setShowCreateModal(false);
          resetForm();
        }}
        title={selectedProject ? 'Edit Project' : 'Create Project'}
        size="lg"
      >
        <form onSubmit={handleSubmit} className="space-y-4">
          <FormField
            label="Project Name"
            required
            error={formErrors.name}
          >
            <input
              type="text"
              className="w-full px-3 py-2 border rounded-lg"
              value={formData.name}
              onChange={(e) => setFormData(f => ({ ...f, name: e.target.value }))}
              placeholder="Enter project name"
            />
          </FormField>
          
          <FormField label="Description">
            <textarea
              className="w-full px-3 py-2 border rounded-lg"
              rows={3}
              value={formData.description}
              onChange={(e) => setFormData(f => ({ ...f, description: e.target.value }))}
              placeholder="Project description..."
            />
          </FormField>
          
          <div className="grid grid-cols-2 gap-4">
            <FormField label="Priority">
              <select
                className="w-full px-3 py-2 border rounded-lg"
                value={formData.priority}
                onChange={(e) => setFormData(f => ({ ...f, priority: e.target.value }))}
              >
                {PRIORITY_OPTIONS.map(opt => (
                  <option key={opt.value} value={opt.value}>{opt.label}</option>
                ))}
              </select>
            </FormField>
            
            <FormField label="Budget">
              <input
                type="number"
                className="w-full px-3 py-2 border rounded-lg"
                value={formData.budget}
                onChange={(e) => setFormData(f => ({ ...f, budget: parseFloat(e.target.value) || 0 }))}
                min="0"
                step="0.01"
              />
            </FormField>
          </div>
          
          <div className="grid grid-cols-2 gap-4">
            <FormField label="Start Date">
              <input
                type="date"
                className="w-full px-3 py-2 border rounded-lg"
                value={formData.start_date}
                onChange={(e) => setFormData(f => ({ ...f, start_date: e.target.value }))}
              />
            </FormField>
            
            <FormField label="Target End Date">
              <input
                type="date"
                className="w-full px-3 py-2 border rounded-lg"
                value={formData.target_end_date}
                onChange={(e) => setFormData(f => ({ ...f, target_end_date: e.target.value }))}
              />
            </FormField>
          </div>
          
          {formErrors.submit && (
            <p className="text-red-500 text-sm">{formErrors.submit}</p>
          )}
          
          <div className="flex justify-end gap-2 pt-4 border-t">
            <Button 
              type="button" 
              variant="outline"
              onClick={() => {
                setShowCreateModal(false);
                resetForm();
              }}
            >
              Cancel
            </Button>
            <Button type="submit" disabled={submitting}>
              {submitting ? 'Saving...' : selectedProject ? 'Update Project' : 'Create Project'}
            </Button>
          </div>
        </form>
      </Modal>
      
      {/* Delete Confirmation */}
      <ConfirmDialog
        isOpen={showDeleteConfirm}
        onClose={() => setShowDeleteConfirm(false)}
        onConfirm={handleDelete}
        title="Delete Project"
        message={`Are you sure you want to delete "${selectedProject?.name}"? This action cannot be undone and will delete all associated tasks.`}
        confirmText="Delete"
        variant="danger"
      />
    </PageLayout>
  );
}
