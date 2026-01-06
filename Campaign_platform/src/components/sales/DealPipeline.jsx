// Campaign_platform/src/components/sales/DealPipeline.jsx
// Kanban-style Deal Pipeline View

import { useState, useEffect, useCallback } from 'react';
import { 
  DollarSign, Plus, MoreVertical, ChevronRight, 
  User, Calendar, Building, Edit, Trash2, Eye,
  ArrowRight, Phone, Mail, Clock, TrendingUp
} from 'lucide-react';
import { Card } from '../ui/Card';
import { Button } from '../ui/Button';
import { Badge } from '../ui/Badge';
import { Modal } from '../ui/Modal';
import { FormField } from '../ui/FormField';
import { ConfirmDialog } from '../ui/ConfirmDialog';
import api from '../../utils/api';

const PIPELINE_STAGES = [
  { id: 'qualification', label: 'Qualification', color: 'bg-gray-100 border-gray-300' },
  { id: 'discovery', label: 'Discovery', color: 'bg-blue-50 border-blue-300' },
  { id: 'proposal', label: 'Proposal', color: 'bg-yellow-50 border-yellow-300' },
  { id: 'negotiation', label: 'Negotiation', color: 'bg-orange-50 border-orange-300' },
  { id: 'closed_won', label: 'Closed Won', color: 'bg-green-50 border-green-300' },
  { id: 'closed_lost', label: 'Closed Lost', color: 'bg-red-50 border-red-300' }
];

const STAGE_COLORS = {
  qualification: 'bg-gray-100 text-gray-700',
  discovery: 'bg-blue-100 text-blue-700',
  proposal: 'bg-yellow-100 text-yellow-700',
  negotiation: 'bg-orange-100 text-orange-700',
  closed_won: 'bg-green-100 text-green-700',
  closed_lost: 'bg-red-100 text-red-700'
};

export default function DealPipeline({ 
  onDealClick,
  onDealCreate,
  refreshTrigger = 0
}) {
  const [deals, setDeals] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  
  // Drag state
  const [draggedDeal, setDraggedDeal] = useState(null);
  const [dragOverStage, setDragOverStage] = useState(null);
  
  // Modal states
  const [showDealModal, setShowDealModal] = useState(false);
  const [selectedDeal, setSelectedDeal] = useState(null);
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false);
  
  // Quick create
  const [quickCreateStage, setQuickCreateStage] = useState(null);
  const [quickCreateName, setQuickCreateName] = useState('');

  // Fetch deals
  const fetchDeals = useCallback(async () => {
    try {
      setLoading(true);
      const response = await api.get('/api/deals');
      if (response.data.success) {
        setDeals(response.data.items || response.data.data || []);
      }
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchDeals();
  }, [fetchDeals, refreshTrigger]);

  // Group deals by stage
  const dealsByStage = PIPELINE_STAGES.reduce((acc, stage) => {
    acc[stage.id] = deals.filter(d => d.stage === stage.id);
    return acc;
  }, {});

  // Calculate stage totals
  const stageTotals = PIPELINE_STAGES.reduce((acc, stage) => {
    const stageDeals = dealsByStage[stage.id] || [];
    acc[stage.id] = {
      count: stageDeals.length,
      value: stageDeals.reduce((sum, d) => sum + (d.value || 0), 0)
    };
    return acc;
  }, {});

  // Handle drag start
  const handleDragStart = (e, deal) => {
    setDraggedDeal(deal);
    e.dataTransfer.effectAllowed = 'move';
    e.dataTransfer.setData('text/plain', deal.id);
  };

  // Handle drag over
  const handleDragOver = (e, stageId) => {
    e.preventDefault();
    e.dataTransfer.dropEffect = 'move';
    setDragOverStage(stageId);
  };

  // Handle drag leave
  const handleDragLeave = () => {
    setDragOverStage(null);
  };

  // Handle drop
  const handleDrop = async (e, targetStage) => {
    e.preventDefault();
    setDragOverStage(null);
    
    if (!draggedDeal || draggedDeal.stage === targetStage) {
      setDraggedDeal(null);
      return;
    }
    
    try {
      await api.put(`/api/deals/${draggedDeal.id}`, { stage: targetStage });
      
      // Optimistic update
      setDeals(prev => prev.map(d => 
        d.id === draggedDeal.id ? { ...d, stage: targetStage } : d
      ));
    } catch (err) {
      console.error('Failed to update deal stage:', err);
      fetchDeals(); // Refresh to get correct state
    }
    
    setDraggedDeal(null);
  };

  // Handle quick create
  const handleQuickCreate = async (stageId) => {
    if (!quickCreateName.trim()) return;
    
    try {
      await api.post('/api/deals', {
        name: quickCreateName,
        stage: stageId,
        value: 0
      });
      
      setQuickCreateName('');
      setQuickCreateStage(null);
      fetchDeals();
      
      if (onDealCreate) {
        onDealCreate();
      }
    } catch (err) {
      console.error('Failed to create deal:', err);
    }
  };

  // Handle delete
  const handleDelete = async () => {
    if (!selectedDeal) return;
    
    try {
      await api.delete(`/api/deals/${selectedDeal.id}`);
      setShowDeleteConfirm(false);
      setSelectedDeal(null);
      fetchDeals();
    } catch (err) {
      console.error('Failed to delete deal:', err);
    }
  };

  // Move deal to next stage
  const moveToNextStage = async (deal) => {
    const currentIndex = PIPELINE_STAGES.findIndex(s => s.id === deal.stage);
    if (currentIndex < PIPELINE_STAGES.length - 2) { // Don't auto-move to closed_lost
      const nextStage = PIPELINE_STAGES[currentIndex + 1].id;
      try {
        await api.put(`/api/deals/${deal.id}`, { stage: nextStage });
        setDeals(prev => prev.map(d => 
          d.id === deal.id ? { ...d, stage: nextStage } : d
        ));
      } catch (err) {
        console.error('Failed to move deal:', err);
      }
    }
  };

  // Render deal card
  const renderDealCard = (deal) => {
    const isDragging = draggedDeal?.id === deal.id;
    
    return (
      <div
        key={deal.id}
        draggable
        onDragStart={(e) => handleDragStart(e, deal)}
        className={`
          bg-white border rounded-lg p-3 mb-2 cursor-grab active:cursor-grabbing
          hover:shadow-md transition-all
          ${isDragging ? 'opacity-50 ring-2 ring-blue-400' : ''}
        `}
      >
        {/* Header */}
        <div className="flex justify-between items-start mb-2">
          <h4 
            className="font-medium text-sm cursor-pointer hover:text-blue-600"
            onClick={() => onDealClick ? onDealClick(deal) : setSelectedDeal(deal)}
          >
            {deal.name}
          </h4>
          <div className="flex items-center gap-1">
            <button
              onClick={(e) => {
                e.stopPropagation();
                moveToNextStage(deal);
              }}
              className="p-1 hover:bg-gray-100 rounded"
              title="Move to next stage"
            >
              <ArrowRight className="w-3 h-3 text-gray-400" />
            </button>
            <button
              onClick={(e) => {
                e.stopPropagation();
                setSelectedDeal(deal);
                setShowDeleteConfirm(true);
              }}
              className="p-1 hover:bg-red-50 rounded"
            >
              <Trash2 className="w-3 h-3 text-gray-400 hover:text-red-500" />
            </button>
          </div>
        </div>
        
        {/* Value */}
        <div className="flex items-center gap-1 text-lg font-semibold text-green-600 mb-2">
          <DollarSign className="w-4 h-4" />
          {(deal.value || 0).toLocaleString()}
        </div>
        
        {/* Contact/Company */}
        {(deal.contact_name || deal.company) && (
          <div className="flex items-center gap-2 text-xs text-gray-500 mb-2">
            {deal.contact_name && (
              <span className="flex items-center gap-1">
                <User className="w-3 h-3" />
                {deal.contact_name}
              </span>
            )}
            {deal.company && (
              <span className="flex items-center gap-1">
                <Building className="w-3 h-3" />
                {deal.company}
              </span>
            )}
          </div>
        )}
        
        {/* Expected close date */}
        {deal.expected_close_date && (
          <div className="flex items-center gap-1 text-xs text-gray-400">
            <Calendar className="w-3 h-3" />
            {new Date(deal.expected_close_date).toLocaleDateString()}
          </div>
        )}
        
        {/* Probability indicator */}
        {deal.probability != null && (
          <div className="mt-2">
            <div className="flex justify-between text-xs text-gray-400 mb-1">
              <span>Probability</span>
              <span>{deal.probability}%</span>
            </div>
            <div className="w-full bg-gray-200 rounded-full h-1">
              <div 
                className="bg-blue-500 h-1 rounded-full"
                style={{ width: `${deal.probability}%` }}
              />
            </div>
          </div>
        )}
      </div>
    );
  };

  // Render stage column
  const renderStageColumn = (stage) => {
    const stageDeals = dealsByStage[stage.id] || [];
    const totals = stageTotals[stage.id];
    const isDropTarget = dragOverStage === stage.id && draggedDeal?.stage !== stage.id;
    
    return (
      <div 
        key={stage.id}
        className={`
          flex-shrink-0 w-72 rounded-lg border-2 
          ${stage.color}
          ${isDropTarget ? 'ring-2 ring-blue-400 border-blue-400' : ''}
        `}
        onDragOver={(e) => handleDragOver(e, stage.id)}
        onDragLeave={handleDragLeave}
        onDrop={(e) => handleDrop(e, stage.id)}
      >
        {/* Stage Header */}
        <div className="p-3 border-b">
          <div className="flex items-center justify-between mb-1">
            <h3 className="font-semibold text-sm">{stage.label}</h3>
            <Badge className="bg-white/50">{totals.count}</Badge>
          </div>
          <div className="flex items-center text-sm text-gray-600">
            <DollarSign className="w-3 h-3" />
            {totals.value.toLocaleString()}
          </div>
        </div>
        
        {/* Deals List */}
        <div className="p-2 min-h-[200px] max-h-[calc(100vh-300px)] overflow-y-auto">
          {stageDeals.map(renderDealCard)}
          
          {/* Quick Create */}
          {quickCreateStage === stage.id ? (
            <div className="bg-white border rounded-lg p-2">
              <input
                type="text"
                className="w-full px-2 py-1 text-sm border rounded mb-2"
                placeholder="Deal name..."
                value={quickCreateName}
                onChange={(e) => setQuickCreateName(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') handleQuickCreate(stage.id);
                  if (e.key === 'Escape') {
                    setQuickCreateStage(null);
                    setQuickCreateName('');
                  }
                }}
                autoFocus
              />
              <div className="flex gap-1">
                <Button size="sm" onClick={() => handleQuickCreate(stage.id)}>
                  Add
                </Button>
                <Button 
                  size="sm" 
                  variant="outline"
                  onClick={() => {
                    setQuickCreateStage(null);
                    setQuickCreateName('');
                  }}
                >
                  Cancel
                </Button>
              </div>
            </div>
          ) : (
            <button
              onClick={() => setQuickCreateStage(stage.id)}
              className="w-full p-2 text-sm text-gray-400 hover:text-gray-600 hover:bg-white/50 rounded flex items-center justify-center gap-1"
            >
              <Plus className="w-4 h-4" />
              Add deal
            </button>
          )}
        </div>
      </div>
    );
  };

  // Pipeline stats
  const renderStats = () => {
    const totalValue = deals.reduce((sum, d) => sum + (d.value || 0), 0);
    const activeDeals = deals.filter(d => !d.stage?.startsWith('closed_')).length;
    const wonValue = deals
      .filter(d => d.stage === 'closed_won')
      .reduce((sum, d) => sum + (d.value || 0), 0);
    
    return (
      <div className="flex gap-6 mb-4 text-sm">
        <div>
          <span className="text-gray-500">Total Pipeline:</span>
          <span className="ml-2 font-semibold text-lg">${totalValue.toLocaleString()}</span>
        </div>
        <div>
          <span className="text-gray-500">Active Deals:</span>
          <span className="ml-2 font-semibold">{activeDeals}</span>
        </div>
        <div>
          <span className="text-gray-500">Won:</span>
          <span className="ml-2 font-semibold text-green-600">${wonValue.toLocaleString()}</span>
        </div>
      </div>
    );
  };

  if (loading && deals.length === 0) {
    return (
      <div className="flex gap-4 overflow-x-auto pb-4">
        {PIPELINE_STAGES.map(stage => (
          <div key={stage.id} className="flex-shrink-0 w-72 h-96 bg-gray-100 rounded-lg animate-pulse" />
        ))}
      </div>
    );
  }

  return (
    <div>
      {/* Stats */}
      {renderStats()}
      
      {/* Pipeline Columns */}
      <div className="flex gap-4 overflow-x-auto pb-4">
        {PIPELINE_STAGES.map(renderStageColumn)}
      </div>
      
      {/* Deal Detail Modal */}
      <Modal
        isOpen={showDealModal && selectedDeal != null}
        onClose={() => {
          setShowDealModal(false);
          setSelectedDeal(null);
        }}
        title={selectedDeal?.name || 'Deal Details'}
        size="lg"
      >
        {selectedDeal && (
          <div className="space-y-4">
            <div className="flex items-center gap-4">
              <div className="text-3xl font-bold text-green-600">
                ${(selectedDeal.value || 0).toLocaleString()}
              </div>
              <Badge className={STAGE_COLORS[selectedDeal.stage]}>
                {PIPELINE_STAGES.find(s => s.id === selectedDeal.stage)?.label}
              </Badge>
            </div>
            
            <div className="grid grid-cols-2 gap-4 text-sm">
              {selectedDeal.contact_name && (
                <div>
                  <span className="text-gray-500">Contact:</span>
                  <p className="font-medium">{selectedDeal.contact_name}</p>
                </div>
              )}
              {selectedDeal.company && (
                <div>
                  <span className="text-gray-500">Company:</span>
                  <p className="font-medium">{selectedDeal.company}</p>
                </div>
              )}
              {selectedDeal.expected_close_date && (
                <div>
                  <span className="text-gray-500">Expected Close:</span>
                  <p className="font-medium">
                    {new Date(selectedDeal.expected_close_date).toLocaleDateString()}
                  </p>
                </div>
              )}
              {selectedDeal.probability != null && (
                <div>
                  <span className="text-gray-500">Probability:</span>
                  <p className="font-medium">{selectedDeal.probability}%</p>
                </div>
              )}
            </div>
            
            {selectedDeal.notes && (
              <div>
                <span className="text-gray-500 text-sm">Notes:</span>
                <p className="mt-1 text-sm whitespace-pre-wrap">{selectedDeal.notes}</p>
              </div>
            )}
          </div>
        )}
      </Modal>
      
      {/* Delete Confirmation */}
      <ConfirmDialog
        isOpen={showDeleteConfirm}
        onClose={() => {
          setShowDeleteConfirm(false);
          setSelectedDeal(null);
        }}
        onConfirm={handleDelete}
        title="Delete Deal"
        message={`Are you sure you want to delete "${selectedDeal?.name}"? This action cannot be undone.`}
        confirmText="Delete"
        variant="danger"
      />
    </div>
  );
}
