// Campaign_platform/src/pages/Support.jsx
// Support/Tickets Management Page

import { useState, useEffect, useCallback } from 'react';
import { 
  Ticket, Plus, Search, Filter, Clock, AlertTriangle, 
  CheckCircle2, XCircle, MoreVertical, MessageSquare,
  ArrowUpCircle, User, Building, Tag, ChevronRight
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
  open: 'bg-blue-100 text-blue-800',
  in_progress: 'bg-yellow-100 text-yellow-800',
  waiting_on_customer: 'bg-purple-100 text-purple-800',
  waiting_on_third_party: 'bg-gray-100 text-gray-800',
  resolved: 'bg-green-100 text-green-800',
  closed: 'bg-gray-200 text-gray-600',
  reopened: 'bg-orange-100 text-orange-800'
};

const PRIORITY_COLORS = {
  low: 'bg-gray-100 text-gray-600',
  medium: 'bg-blue-100 text-blue-700',
  high: 'bg-orange-100 text-orange-700',
  urgent: 'bg-red-100 text-red-700',
  critical: 'bg-red-200 text-red-800'
};

const CATEGORY_ICONS = {
  question: '❓',
  incident: '🔥',
  problem: '⚠️',
  feature_request: '💡',
  change_request: '🔄',
  billing: '💳',
  technical: '🔧',
  general: '📋'
};

const STATUS_OPTIONS = [
  { value: 'open', label: 'Open' },
  { value: 'in_progress', label: 'In Progress' },
  { value: 'waiting_on_customer', label: 'Waiting on Customer' },
  { value: 'resolved', label: 'Resolved' },
  { value: 'closed', label: 'Closed' }
];

const PRIORITY_OPTIONS = [
  { value: 'low', label: 'Low' },
  { value: 'medium', label: 'Medium' },
  { value: 'high', label: 'High' },
  { value: 'urgent', label: 'Urgent' },
  { value: 'critical', label: 'Critical' }
];

const CATEGORY_OPTIONS = [
  { value: 'question', label: 'Question' },
  { value: 'incident', label: 'Incident' },
  { value: 'problem', label: 'Problem' },
  { value: 'feature_request', label: 'Feature Request' },
  { value: 'billing', label: 'Billing' },
  { value: 'technical', label: 'Technical' },
  { value: 'general', label: 'General' }
];

export default function Support() {
  const [tickets, setTickets] = useState([]);
  const [stats, setStats] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  
  // Filters
  const [filters, setFilters] = useState({
    status: '',
    priority: '',
    category: '',
    sla_breached: null,
    search: ''
  });
  
  // Modal states
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [showDetailModal, setShowDetailModal] = useState(false);
  const [selectedTicket, setSelectedTicket] = useState(null);
  const [comments, setComments] = useState([]);
  const [activities, setActivities] = useState([]);
  const [newComment, setNewComment] = useState('');
  const [isInternalNote, setIsInternalNote] = useState(false);
  
  // Resolution modal
  const [showResolveModal, setShowResolveModal] = useState(false);
  const [resolution, setResolution] = useState('');
  const [closeOnResolve, setCloseOnResolve] = useState(false);
  
  // Form state
  const [formData, setFormData] = useState({
    subject: '',
    description: '',
    priority: 'medium',
    category: 'general',
    contact_name: '',
    contact_email: '',
    tags: []
  });
  const [formErrors, setFormErrors] = useState({});
  const [submitting, setSubmitting] = useState(false);

  // Fetch tickets
  const fetchTickets = useCallback(async () => {
    try {
      setLoading(true);
      const params = new URLSearchParams();
      if (filters.status) params.append('status', filters.status);
      if (filters.priority) params.append('priority', filters.priority);
      if (filters.category) params.append('category', filters.category);
      if (filters.sla_breached !== null) params.append('sla_breached', filters.sla_breached);
      
      const response = await api.get(`/api/support/tickets?${params}`);
      if (response.data.success) {
        let items = response.data.items || [];
        
        // Client-side search filter
        if (filters.search) {
          const searchLower = filters.search.toLowerCase();
          items = items.filter(t => 
            t.subject?.toLowerCase().includes(searchLower) ||
            t.ticket_number?.toLowerCase().includes(searchLower) ||
            t.contact_name?.toLowerCase().includes(searchLower) ||
            t.contact_email?.toLowerCase().includes(searchLower)
          );
        }
        
        setTickets(items);
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
      const response = await api.get('/api/support/tickets/stats');
      if (response.data.success) {
        setStats(response.data.data);
      }
    } catch (err) {
      console.error('Failed to fetch stats:', err);
    }
  }, []);

  // Fetch ticket details
  const fetchTicketDetails = useCallback(async (ticketId) => {
    try {
      const [commentsRes, activitiesRes] = await Promise.all([
        api.get(`/api/support/tickets/${ticketId}/comments`),
        api.get(`/api/support/tickets/${ticketId}/activities`)
      ]);
      
      if (commentsRes.data.success) {
        setComments(commentsRes.data.data || []);
      }
      if (activitiesRes.data.success) {
        setActivities(activitiesRes.data.data || []);
      }
    } catch (err) {
      console.error('Failed to fetch ticket details:', err);
    }
  }, []);

  useEffect(() => {
    fetchTickets();
    fetchStats();
  }, [fetchTickets, fetchStats]);

  useEffect(() => {
    if (selectedTicket && showDetailModal) {
      fetchTicketDetails(selectedTicket.id);
    }
  }, [selectedTicket, showDetailModal, fetchTicketDetails]);

  // Handle form submit
  const handleSubmit = async (e) => {
    e.preventDefault();
    
    // Validation
    const errors = {};
    if (!formData.subject?.trim()) errors.subject = 'Subject is required';
    if (!formData.description?.trim()) errors.description = 'Description is required';
    
    if (Object.keys(errors).length > 0) {
      setFormErrors(errors);
      return;
    }
    
    try {
      setSubmitting(true);
      await api.post('/api/support/tickets', formData);
      setShowCreateModal(false);
      resetForm();
      fetchTickets();
      fetchStats();
    } catch (err) {
      setFormErrors({ submit: err.response?.data?.detail || err.message });
    } finally {
      setSubmitting(false);
    }
  };

  // Handle add comment
  const handleAddComment = async () => {
    if (!newComment.trim() || !selectedTicket) return;
    
    try {
      await api.post(`/api/support/tickets/${selectedTicket.id}/comments`, null, {
        params: {
          content: newComment,
          is_internal: isInternalNote
        }
      });
      
      setNewComment('');
      setIsInternalNote(false);
      fetchTicketDetails(selectedTicket.id);
      fetchTickets();
    } catch (err) {
      console.error('Failed to add comment:', err);
    }
  };

  // Handle resolve ticket
  const handleResolve = async () => {
    if (!resolution.trim() || !selectedTicket) return;
    
    try {
      await api.post(`/api/support/tickets/${selectedTicket.id}/resolve`, {
        resolution,
        close_ticket: closeOnResolve
      });
      
      setShowResolveModal(false);
      setResolution('');
      setCloseOnResolve(false);
      setShowDetailModal(false);
      fetchTickets();
      fetchStats();
    } catch (err) {
      console.error('Failed to resolve ticket:', err);
    }
  };

  // Handle status change
  const handleStatusChange = async (ticketId, newStatus) => {
    try {
      await api.put(`/api/support/tickets/${ticketId}`, { status: newStatus });
      fetchTickets();
      if (selectedTicket?.id === ticketId) {
        const response = await api.get(`/api/support/tickets/${ticketId}`);
        if (response.data.success) {
          setSelectedTicket(response.data.data);
        }
      }
    } catch (err) {
      console.error('Failed to update status:', err);
    }
  };

  // Reset form
  const resetForm = () => {
    setFormData({
      subject: '',
      description: '',
      priority: 'medium',
      category: 'general',
      contact_name: '',
      contact_email: '',
      tags: []
    });
    setFormErrors({});
  };

  // Calculate SLA indicator
  const getSLAIndicator = (ticket) => {
    const sla = ticket.sla_status;
    if (!sla) return null;
    
    if (sla.response_breached || sla.resolution_breached) {
      return <Badge className="bg-red-100 text-red-800">SLA Breached</Badge>;
    }
    
    const resolutionRemaining = sla.resolution_time_remaining;
    if (resolutionRemaining !== null && resolutionRemaining < 2) {
      return <Badge className="bg-orange-100 text-orange-800">SLA At Risk</Badge>;
    }
    
    return null;
  };

  // Render stats cards
  const renderStats = () => {
    if (!stats) return null;
    
    return (
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-5 gap-4 mb-6">
        <Card className="p-4">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-sm text-gray-500">Open</p>
              <p className="text-2xl font-bold text-blue-600">{stats.open_tickets}</p>
            </div>
            <Ticket className="w-8 h-8 text-blue-500" />
          </div>
        </Card>
        
        <Card className="p-4">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-sm text-gray-500">In Progress</p>
              <p className="text-2xl font-bold text-yellow-600">{stats.in_progress_tickets}</p>
            </div>
            <Clock className="w-8 h-8 text-yellow-500" />
          </div>
        </Card>
        
        <Card className="p-4">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-sm text-gray-500">Resolved</p>
              <p className="text-2xl font-bold text-green-600">{stats.resolved_tickets}</p>
            </div>
            <CheckCircle2 className="w-8 h-8 text-green-500" />
          </div>
        </Card>
        
        <Card className="p-4">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-sm text-gray-500">SLA Breached</p>
              <p className="text-2xl font-bold text-red-600">{stats.sla_breached_count}</p>
            </div>
            <AlertTriangle className="w-8 h-8 text-red-500" />
          </div>
        </Card>
        
        <Card className="p-4">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-sm text-gray-500">Avg Response</p>
              <p className="text-2xl font-bold">{stats.avg_response_time_hours?.toFixed(1)}h</p>
            </div>
            <Clock className="w-8 h-8 text-gray-500" />
          </div>
        </Card>
      </div>
    );
  };

  // Render ticket row
  const renderTicketRow = (ticket) => (
    <tr 
      key={ticket.id} 
      className="hover:bg-gray-50 cursor-pointer"
      onClick={() => {
        setSelectedTicket(ticket);
        setShowDetailModal(true);
      }}
    >
      <td className="px-4 py-3">
        <div className="flex items-center gap-2">
          <span className="text-gray-400">{CATEGORY_ICONS[ticket.category] || '📋'}</span>
          <div>
            <span className="font-mono text-xs text-gray-500">{ticket.ticket_number}</span>
            <p className="font-medium">{ticket.subject}</p>
          </div>
        </div>
      </td>
      <td className="px-4 py-3">
        <Badge className={STATUS_COLORS[ticket.status] || 'bg-gray-100'}>
          {ticket.status?.replace(/_/g, ' ')}
        </Badge>
      </td>
      <td className="px-4 py-3">
        <Badge className={PRIORITY_COLORS[ticket.priority] || 'bg-gray-100'}>
          {ticket.priority}
        </Badge>
      </td>
      <td className="px-4 py-3">
        <div className="flex items-center gap-2">
          {ticket.contact_name && (
            <>
              <User className="w-4 h-4 text-gray-400" />
              <span className="text-sm">{ticket.contact_name}</span>
            </>
          )}
        </div>
      </td>
      <td className="px-4 py-3">
        {getSLAIndicator(ticket)}
      </td>
      <td className="px-4 py-3 text-sm text-gray-500">
        {new Date(ticket.created_at).toLocaleDateString()}
      </td>
      <td className="px-4 py-3">
        <Button 
          variant="ghost" 
          size="sm"
          onClick={(e) => {
            e.stopPropagation();
            setSelectedTicket(ticket);
            setShowDetailModal(true);
          }}
        >
          <ChevronRight className="w-4 h-4" />
        </Button>
      </td>
    </tr>
  );

  return (
    <PageLayout>
      <PageHeader
        title="Support"
        subtitle="Manage support tickets and customer inquiries"
        icon={<Ticket className="w-6 h-6" />}
        actions={
          <Button onClick={() => setShowCreateModal(true)}>
            <Plus className="w-4 h-4 mr-2" />
            New Ticket
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
                placeholder="Search tickets..."
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
          
          <select
            className="px-4 py-2 border rounded-lg"
            value={filters.category}
            onChange={(e) => setFilters(f => ({ ...f, category: e.target.value }))}
          >
            <option value="">All Categories</option>
            {CATEGORY_OPTIONS.map(opt => (
              <option key={opt.value} value={opt.value}>{opt.label}</option>
            ))}
          </select>
          
          <Button
            variant={filters.sla_breached === true ? 'primary' : 'outline'}
            onClick={() => setFilters(f => ({ 
              ...f, 
              sla_breached: f.sla_breached === true ? null : true 
            }))}
          >
            <AlertTriangle className="w-4 h-4 mr-2" />
            SLA Breached
          </Button>
        </div>
      </Card>
      
      {/* Tickets Table */}
      {loading ? (
        <Card className="p-4">
          {[1, 2, 3, 4, 5].map(i => (
            <div key={i} className="flex items-center gap-4 py-3 border-b last:border-0">
              <Skeleton className="h-4 w-24" />
              <Skeleton className="h-4 w-48 flex-1" />
              <Skeleton className="h-6 w-20" />
              <Skeleton className="h-6 w-16" />
            </div>
          ))}
        </Card>
      ) : error ? (
        <Card className="p-8 text-center">
          <AlertTriangle className="w-12 h-12 text-red-500 mx-auto mb-4" />
          <p className="text-red-600">{error}</p>
        </Card>
      ) : tickets.length === 0 ? (
        <EmptyState
          icon={<Ticket className="w-12 h-12" />}
          title="No tickets found"
          description="No support tickets match your filters"
          action={
            <Button onClick={() => setShowCreateModal(true)}>
              <Plus className="w-4 h-4 mr-2" />
              Create Ticket
            </Button>
          }
        />
      ) : (
        <Card className="overflow-hidden">
          <table className="w-full">
            <thead className="bg-gray-50">
              <tr>
                <th className="px-4 py-3 text-left text-sm font-medium text-gray-600">Ticket</th>
                <th className="px-4 py-3 text-left text-sm font-medium text-gray-600">Status</th>
                <th className="px-4 py-3 text-left text-sm font-medium text-gray-600">Priority</th>
                <th className="px-4 py-3 text-left text-sm font-medium text-gray-600">Contact</th>
                <th className="px-4 py-3 text-left text-sm font-medium text-gray-600">SLA</th>
                <th className="px-4 py-3 text-left text-sm font-medium text-gray-600">Created</th>
                <th className="px-4 py-3"></th>
              </tr>
            </thead>
            <tbody className="divide-y">
              {tickets.map(renderTicketRow)}
            </tbody>
          </table>
        </Card>
      )}
      
      {/* Create Modal */}
      <Modal
        isOpen={showCreateModal}
        onClose={() => {
          setShowCreateModal(false);
          resetForm();
        }}
        title="Create Ticket"
        size="lg"
      >
        <form onSubmit={handleSubmit} className="space-y-4">
          <FormField label="Subject" required error={formErrors.subject}>
            <input
              type="text"
              className="w-full px-3 py-2 border rounded-lg"
              value={formData.subject}
              onChange={(e) => setFormData(f => ({ ...f, subject: e.target.value }))}
              placeholder="Brief summary of the issue"
            />
          </FormField>
          
          <FormField label="Description" required error={formErrors.description}>
            <textarea
              className="w-full px-3 py-2 border rounded-lg"
              rows={4}
              value={formData.description}
              onChange={(e) => setFormData(f => ({ ...f, description: e.target.value }))}
              placeholder="Detailed description of the issue..."
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
            
            <FormField label="Category">
              <select
                className="w-full px-3 py-2 border rounded-lg"
                value={formData.category}
                onChange={(e) => setFormData(f => ({ ...f, category: e.target.value }))}
              >
                {CATEGORY_OPTIONS.map(opt => (
                  <option key={opt.value} value={opt.value}>{opt.label}</option>
                ))}
              </select>
            </FormField>
          </div>
          
          <div className="grid grid-cols-2 gap-4">
            <FormField label="Contact Name">
              <input
                type="text"
                className="w-full px-3 py-2 border rounded-lg"
                value={formData.contact_name}
                onChange={(e) => setFormData(f => ({ ...f, contact_name: e.target.value }))}
                placeholder="Customer name"
              />
            </FormField>
            
            <FormField label="Contact Email">
              <input
                type="email"
                className="w-full px-3 py-2 border rounded-lg"
                value={formData.contact_email}
                onChange={(e) => setFormData(f => ({ ...f, contact_email: e.target.value }))}
                placeholder="customer@example.com"
              />
            </FormField>
          </div>
          
          {formErrors.submit && (
            <p className="text-red-500 text-sm">{formErrors.submit}</p>
          )}
          
          <div className="flex justify-end gap-2 pt-4 border-t">
            <Button type="button" variant="outline" onClick={() => {
              setShowCreateModal(false);
              resetForm();
            }}>
              Cancel
            </Button>
            <Button type="submit" disabled={submitting}>
              {submitting ? 'Creating...' : 'Create Ticket'}
            </Button>
          </div>
        </form>
      </Modal>
      
      {/* Detail Modal */}
      <Modal
        isOpen={showDetailModal}
        onClose={() => {
          setShowDetailModal(false);
          setSelectedTicket(null);
          setComments([]);
          setActivities([]);
        }}
        title={selectedTicket?.ticket_number || 'Ticket Details'}
        size="xl"
      >
        {selectedTicket && (
          <div className="space-y-6">
            {/* Header */}
            <div className="flex justify-between items-start">
              <div>
                <h2 className="text-xl font-semibold">{selectedTicket.subject}</h2>
                <div className="flex items-center gap-2 mt-2">
                  <Badge className={STATUS_COLORS[selectedTicket.status]}>
                    {selectedTicket.status?.replace(/_/g, ' ')}
                  </Badge>
                  <Badge className={PRIORITY_COLORS[selectedTicket.priority]}>
                    {selectedTicket.priority}
                  </Badge>
                  {getSLAIndicator(selectedTicket)}
                </div>
              </div>
              
              <div className="flex gap-2">
                {selectedTicket.status !== 'resolved' && selectedTicket.status !== 'closed' && (
                  <Button onClick={() => setShowResolveModal(true)}>
                    <CheckCircle2 className="w-4 h-4 mr-2" />
                    Resolve
                  </Button>
                )}
                {selectedTicket.status === 'resolved' && (
                  <Button onClick={() => handleStatusChange(selectedTicket.id, 'closed')}>
                    <XCircle className="w-4 h-4 mr-2" />
                    Close
                  </Button>
                )}
              </div>
            </div>
            
            {/* Description */}
            <Card className="p-4">
              <h3 className="font-medium mb-2">Description</h3>
              <p className="text-gray-600 whitespace-pre-wrap">{selectedTicket.description}</p>
            </Card>
            
            {/* Contact Info */}
            {(selectedTicket.contact_name || selectedTicket.contact_email) && (
              <Card className="p-4">
                <h3 className="font-medium mb-2">Contact Information</h3>
                <div className="flex items-center gap-4 text-sm">
                  {selectedTicket.contact_name && (
                    <div className="flex items-center gap-2">
                      <User className="w-4 h-4 text-gray-400" />
                      <span>{selectedTicket.contact_name}</span>
                    </div>
                  )}
                  {selectedTicket.contact_email && (
                    <a href={`mailto:${selectedTicket.contact_email}`} className="text-blue-600 hover:underline">
                      {selectedTicket.contact_email}
                    </a>
                  )}
                </div>
              </Card>
            )}
            
            {/* Comments */}
            <div>
              <h3 className="font-medium mb-3">Comments ({comments.length})</h3>
              <div className="space-y-3 max-h-64 overflow-y-auto mb-4">
                {comments.map(comment => (
                  <Card 
                    key={comment.id} 
                    className={`p-3 ${comment.is_internal ? 'bg-yellow-50 border-yellow-200' : ''}`}
                  >
                    <div className="flex justify-between items-start mb-2">
                      <div className="flex items-center gap-2">
                        <span className="font-medium text-sm">{comment.author_name || 'Agent'}</span>
                        {comment.is_internal && (
                          <Badge className="bg-yellow-100 text-yellow-800 text-xs">Internal</Badge>
                        )}
                      </div>
                      <span className="text-xs text-gray-400">
                        {new Date(comment.created_at).toLocaleString()}
                      </span>
                    </div>
                    <p className="text-sm text-gray-600">{comment.content}</p>
                  </Card>
                ))}
                {comments.length === 0 && (
                  <p className="text-gray-400 text-sm">No comments yet</p>
                )}
              </div>
              
              {/* Add Comment */}
              <div className="flex gap-2">
                <div className="flex-1">
                  <textarea
                    className="w-full px-3 py-2 border rounded-lg text-sm"
                    rows={2}
                    placeholder="Add a comment..."
                    value={newComment}
                    onChange={(e) => setNewComment(e.target.value)}
                  />
                  <label className="flex items-center gap-2 mt-1 text-sm text-gray-600">
                    <input
                      type="checkbox"
                      checked={isInternalNote}
                      onChange={(e) => setIsInternalNote(e.target.checked)}
                    />
                    Internal note (not visible to customer)
                  </label>
                </div>
                <Button onClick={handleAddComment} disabled={!newComment.trim()}>
                  <MessageSquare className="w-4 h-4" />
                </Button>
              </div>
            </div>
            
            {/* Activity Log */}
            <div>
              <h3 className="font-medium mb-3">Activity</h3>
              <ActivityTimeline 
                items={activities.map(a => ({
                  id: a.id,
                  title: a.action?.replace(/_/g, ' '),
                  description: a.description,
                  timestamp: a.created_at,
                  user: a.actor_name
                }))}
              />
            </div>
          </div>
        )}
      </Modal>
      
      {/* Resolve Modal */}
      <Modal
        isOpen={showResolveModal}
        onClose={() => {
          setShowResolveModal(false);
          setResolution('');
          setCloseOnResolve(false);
        }}
        title="Resolve Ticket"
        size="md"
      >
        <div className="space-y-4">
          <FormField label="Resolution" required>
            <textarea
              className="w-full px-3 py-2 border rounded-lg"
              rows={4}
              placeholder="Describe how the issue was resolved..."
              value={resolution}
              onChange={(e) => setResolution(e.target.value)}
            />
          </FormField>
          
          <label className="flex items-center gap-2">
            <input
              type="checkbox"
              checked={closeOnResolve}
              onChange={(e) => setCloseOnResolve(e.target.checked)}
            />
            <span className="text-sm">Also close the ticket</span>
          </label>
          
          <div className="flex justify-end gap-2 pt-4 border-t">
            <Button variant="outline" onClick={() => {
              setShowResolveModal(false);
              setResolution('');
              setCloseOnResolve(false);
            }}>
              Cancel
            </Button>
            <Button onClick={handleResolve} disabled={!resolution.trim()}>
              <CheckCircle2 className="w-4 h-4 mr-2" />
              Resolve Ticket
            </Button>
          </div>
        </div>
      </Modal>
    </PageLayout>
  );
}
