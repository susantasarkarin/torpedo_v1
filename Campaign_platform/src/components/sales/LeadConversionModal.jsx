// Campaign_platform/src/components/sales/LeadConversionModal.jsx
// Modal for converting a lead to contact/deal

import { useState, useEffect } from 'react';
import { 
  UserPlus, Building, Briefcase, ArrowRight, 
  CheckCircle, AlertCircle, Loader2 
} from 'lucide-react';
import { Modal } from '../ui/Modal';
import { FormField } from '../ui/FormField';
import { Button } from '../ui/Button';
import { Card } from '../ui/Card';
import { Badge } from '../ui/Badge';
import api from '../../utils/api';

const CONVERSION_STEPS = [
  { id: 'review', label: 'Review Lead' },
  { id: 'contact', label: 'Create Contact' },
  { id: 'deal', label: 'Create Deal' },
  { id: 'complete', label: 'Complete' }
];

const DEAL_STAGES = [
  { value: 'qualification', label: 'Qualification' },
  { value: 'discovery', label: 'Discovery' },
  { value: 'proposal', label: 'Proposal' },
  { value: 'negotiation', label: 'Negotiation' },
  { value: 'won', label: 'Won' },
  { value: 'lost', label: 'Lost' }
];

export default function LeadConversionModal({ 
  isOpen, 
  onClose, 
  lead, 
  onConversionComplete 
}) {
  const [currentStep, setCurrentStep] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  
  // Contact form data
  const [contactData, setContactData] = useState({
    first_name: '',
    last_name: '',
    email: '',
    phone: '',
    company: '',
    title: '',
    source: 'lead_conversion'
  });
  
  // Deal form data
  const [dealData, setDealData] = useState({
    name: '',
    value: 0,
    currency: 'USD',
    stage: 'qualification',
    expected_close_date: '',
    notes: ''
  });
  
  // Whether to create each entity
  const [createContact, setCreateContact] = useState(true);
  const [createDeal, setCreateDeal] = useState(true);
  
  // Conversion result
  const [result, setResult] = useState(null);

  // Initialize form data from lead
  useEffect(() => {
    if (lead && isOpen) {
      // Parse lead name into first/last
      const nameParts = (lead.name || '').split(' ');
      const firstName = nameParts[0] || '';
      const lastName = nameParts.slice(1).join(' ') || '';
      
      setContactData({
        first_name: firstName,
        last_name: lastName,
        email: lead.email || '',
        phone: lead.phone || '',
        company: lead.company || lead.organization || '',
        title: lead.title || lead.job_title || '',
        source: 'lead_conversion'
      });
      
      setDealData({
        name: `Deal - ${lead.company || lead.name || 'New'}`,
        value: lead.estimated_value || 0,
        currency: 'USD',
        stage: 'qualification',
        expected_close_date: '',
        notes: lead.notes || ''
      });
      
      setCurrentStep(0);
      setResult(null);
      setError(null);
    }
  }, [lead, isOpen]);

  // Handle contact form change
  const handleContactChange = (field, value) => {
    setContactData(prev => ({ ...prev, [field]: value }));
  };

  // Handle deal form change
  const handleDealChange = (field, value) => {
    setDealData(prev => ({ ...prev, [field]: value }));
  };

  // Go to next step
  const nextStep = () => {
    if (currentStep < CONVERSION_STEPS.length - 1) {
      // Skip contact step if not creating contact
      if (currentStep === 0 && !createContact && !createDeal) {
        setError('Please select at least one entity to create');
        return;
      }
      if (currentStep === 1 && !createContact) {
        setCurrentStep(2);
      } else {
        setCurrentStep(prev => prev + 1);
      }
    }
  };

  // Go to previous step
  const prevStep = () => {
    if (currentStep > 0) {
      // Skip contact step if not creating contact
      if (currentStep === 2 && !createContact) {
        setCurrentStep(0);
      } else {
        setCurrentStep(prev => prev - 1);
      }
    }
  };

  // Execute conversion
  const executeConversion = async () => {
    try {
      setLoading(true);
      setError(null);
      
      const conversionResult = {
        lead_id: lead.id,
        contact: null,
        deal: null
      };
      
      // Create contact if selected
      if (createContact) {
        const contactPayload = {
          ...contactData,
          lead_id: lead.id
        };
        
        const contactResponse = await api.post('/api/contacts', contactPayload);
        if (contactResponse.data.success) {
          conversionResult.contact = contactResponse.data.data;
        }
      }
      
      // Create deal if selected
      if (createDeal) {
        const dealPayload = {
          ...dealData,
          lead_id: lead.id,
          contact_id: conversionResult.contact?.id,
          expected_close_date: dealData.expected_close_date 
            ? new Date(dealData.expected_close_date).toISOString() 
            : null
        };
        
        const dealResponse = await api.post('/api/deals', dealPayload);
        if (dealResponse.data.success) {
          conversionResult.deal = dealResponse.data.data;
        }
      }
      
      // Mark lead as converted
      await api.put(`/api/leads/${lead.id}`, {
        status: 'converted',
        converted_at: new Date().toISOString(),
        converted_to_contact_id: conversionResult.contact?.id,
        converted_to_deal_id: conversionResult.deal?.id
      });
      
      setResult(conversionResult);
      setCurrentStep(3); // Move to complete step
      
      if (onConversionComplete) {
        onConversionComplete(conversionResult);
      }
      
    } catch (err) {
      setError(err.response?.data?.detail || err.message);
    } finally {
      setLoading(false);
    }
  };

  // Render step indicator
  const renderStepIndicator = () => (
    <div className="flex items-center justify-center mb-6">
      {CONVERSION_STEPS.map((step, index) => (
        <div key={step.id} className="flex items-center">
          <div 
            className={`
              w-8 h-8 rounded-full flex items-center justify-center text-sm font-medium
              ${index < currentStep ? 'bg-green-500 text-white' : 
                index === currentStep ? 'bg-blue-500 text-white' : 
                'bg-gray-200 text-gray-500'}
            `}
          >
            {index < currentStep ? <CheckCircle className="w-5 h-5" /> : index + 1}
          </div>
          {index < CONVERSION_STEPS.length - 1 && (
            <div 
              className={`w-12 h-1 mx-2 ${
                index < currentStep ? 'bg-green-500' : 'bg-gray-200'
              }`}
            />
          )}
        </div>
      ))}
    </div>
  );

  // Step 1: Review Lead
  const renderReviewStep = () => (
    <div className="space-y-4">
      <Card className="p-4">
        <h3 className="font-medium mb-3">Lead Information</h3>
        <div className="grid grid-cols-2 gap-4 text-sm">
          <div>
            <span className="text-gray-500">Name:</span>
            <p className="font-medium">{lead?.name || 'N/A'}</p>
          </div>
          <div>
            <span className="text-gray-500">Email:</span>
            <p className="font-medium">{lead?.email || 'N/A'}</p>
          </div>
          <div>
            <span className="text-gray-500">Company:</span>
            <p className="font-medium">{lead?.company || lead?.organization || 'N/A'}</p>
          </div>
          <div>
            <span className="text-gray-500">Phone:</span>
            <p className="font-medium">{lead?.phone || 'N/A'}</p>
          </div>
          <div>
            <span className="text-gray-500">Source:</span>
            <p className="font-medium">{lead?.source || 'N/A'}</p>
          </div>
          <div>
            <span className="text-gray-500">Status:</span>
            <Badge className="bg-blue-100 text-blue-800">{lead?.status || 'new'}</Badge>
          </div>
        </div>
      </Card>
      
      <Card className="p-4">
        <h3 className="font-medium mb-3">Conversion Options</h3>
        <div className="space-y-3">
          <label className="flex items-center gap-3 p-3 border rounded-lg cursor-pointer hover:bg-gray-50">
            <input
              type="checkbox"
              checked={createContact}
              onChange={(e) => setCreateContact(e.target.checked)}
              className="w-5 h-5"
            />
            <div className="flex items-center gap-2">
              <UserPlus className="w-5 h-5 text-blue-500" />
              <div>
                <p className="font-medium">Create Contact</p>
                <p className="text-sm text-gray-500">Add as a contact in your CRM</p>
              </div>
            </div>
          </label>
          
          <label className="flex items-center gap-3 p-3 border rounded-lg cursor-pointer hover:bg-gray-50">
            <input
              type="checkbox"
              checked={createDeal}
              onChange={(e) => setCreateDeal(e.target.checked)}
              className="w-5 h-5"
            />
            <div className="flex items-center gap-2">
              <Briefcase className="w-5 h-5 text-green-500" />
              <div>
                <p className="font-medium">Create Deal</p>
                <p className="text-sm text-gray-500">Start tracking as a sales opportunity</p>
              </div>
            </div>
          </label>
        </div>
      </Card>
    </div>
  );

  // Step 2: Contact Details
  const renderContactStep = () => (
    <div className="space-y-4">
      <div className="flex items-center gap-2 mb-4">
        <UserPlus className="w-5 h-5 text-blue-500" />
        <h3 className="font-medium">Contact Details</h3>
      </div>
      
      <div className="grid grid-cols-2 gap-4">
        <FormField label="First Name" required>
          <input
            type="text"
            className="w-full px-3 py-2 border rounded-lg"
            value={contactData.first_name}
            onChange={(e) => handleContactChange('first_name', e.target.value)}
          />
        </FormField>
        
        <FormField label="Last Name">
          <input
            type="text"
            className="w-full px-3 py-2 border rounded-lg"
            value={contactData.last_name}
            onChange={(e) => handleContactChange('last_name', e.target.value)}
          />
        </FormField>
      </div>
      
      <FormField label="Email" required>
        <input
          type="email"
          className="w-full px-3 py-2 border rounded-lg"
          value={contactData.email}
          onChange={(e) => handleContactChange('email', e.target.value)}
        />
      </FormField>
      
      <FormField label="Phone">
        <input
          type="tel"
          className="w-full px-3 py-2 border rounded-lg"
          value={contactData.phone}
          onChange={(e) => handleContactChange('phone', e.target.value)}
        />
      </FormField>
      
      <div className="grid grid-cols-2 gap-4">
        <FormField label="Company">
          <input
            type="text"
            className="w-full px-3 py-2 border rounded-lg"
            value={contactData.company}
            onChange={(e) => handleContactChange('company', e.target.value)}
          />
        </FormField>
        
        <FormField label="Title">
          <input
            type="text"
            className="w-full px-3 py-2 border rounded-lg"
            value={contactData.title}
            onChange={(e) => handleContactChange('title', e.target.value)}
          />
        </FormField>
      </div>
    </div>
  );

  // Step 3: Deal Details
  const renderDealStep = () => (
    <div className="space-y-4">
      <div className="flex items-center gap-2 mb-4">
        <Briefcase className="w-5 h-5 text-green-500" />
        <h3 className="font-medium">Deal Details</h3>
      </div>
      
      <FormField label="Deal Name" required>
        <input
          type="text"
          className="w-full px-3 py-2 border rounded-lg"
          value={dealData.name}
          onChange={(e) => handleDealChange('name', e.target.value)}
          placeholder="e.g., Enterprise License - Acme Corp"
        />
      </FormField>
      
      <div className="grid grid-cols-2 gap-4">
        <FormField label="Value">
          <div className="flex">
            <select
              className="px-3 py-2 border border-r-0 rounded-l-lg bg-gray-50"
              value={dealData.currency}
              onChange={(e) => handleDealChange('currency', e.target.value)}
            >
              <option value="USD">$</option>
              <option value="EUR">€</option>
              <option value="GBP">£</option>
            </select>
            <input
              type="number"
              className="w-full px-3 py-2 border rounded-r-lg"
              value={dealData.value}
              onChange={(e) => handleDealChange('value', parseFloat(e.target.value) || 0)}
              min="0"
              step="0.01"
            />
          </div>
        </FormField>
        
        <FormField label="Stage">
          <select
            className="w-full px-3 py-2 border rounded-lg"
            value={dealData.stage}
            onChange={(e) => handleDealChange('stage', e.target.value)}
          >
            {DEAL_STAGES.map(stage => (
              <option key={stage.value} value={stage.value}>{stage.label}</option>
            ))}
          </select>
        </FormField>
      </div>
      
      <FormField label="Expected Close Date">
        <input
          type="date"
          className="w-full px-3 py-2 border rounded-lg"
          value={dealData.expected_close_date}
          onChange={(e) => handleDealChange('expected_close_date', e.target.value)}
        />
      </FormField>
      
      <FormField label="Notes">
        <textarea
          className="w-full px-3 py-2 border rounded-lg"
          rows={3}
          value={dealData.notes}
          onChange={(e) => handleDealChange('notes', e.target.value)}
          placeholder="Additional notes about this deal..."
        />
      </FormField>
    </div>
  );

  // Step 4: Complete
  const renderCompleteStep = () => (
    <div className="text-center py-8">
      <div className="w-16 h-16 bg-green-100 rounded-full flex items-center justify-center mx-auto mb-4">
        <CheckCircle className="w-8 h-8 text-green-500" />
      </div>
      <h3 className="text-xl font-semibold mb-2">Conversion Complete!</h3>
      <p className="text-gray-500 mb-6">
        Lead has been successfully converted.
      </p>
      
      {result && (
        <div className="space-y-3 text-left max-w-sm mx-auto">
          {result.contact && (
            <Card className="p-3 flex items-center gap-3">
              <UserPlus className="w-5 h-5 text-blue-500" />
              <div>
                <p className="font-medium">Contact Created</p>
                <p className="text-sm text-gray-500">
                  {result.contact.first_name} {result.contact.last_name}
                </p>
              </div>
            </Card>
          )}
          
          {result.deal && (
            <Card className="p-3 flex items-center gap-3">
              <Briefcase className="w-5 h-5 text-green-500" />
              <div>
                <p className="font-medium">Deal Created</p>
                <p className="text-sm text-gray-500">{result.deal.name}</p>
              </div>
            </Card>
          )}
        </div>
      )}
    </div>
  );

  // Render current step content
  const renderStepContent = () => {
    switch (currentStep) {
      case 0:
        return renderReviewStep();
      case 1:
        return createContact ? renderContactStep() : renderDealStep();
      case 2:
        return createDeal ? renderDealStep() : renderCompleteStep();
      case 3:
        return renderCompleteStep();
      default:
        return null;
    }
  };

  // Render footer actions
  const renderActions = () => {
    if (currentStep === 3) {
      return (
        <div className="flex justify-center">
          <Button onClick={onClose}>
            Done
          </Button>
        </div>
      );
    }
    
    const isLastDataStep = 
      (currentStep === 1 && !createDeal) ||
      (currentStep === 2 && createDeal);
    
    return (
      <div className="flex justify-between">
        <Button 
          variant="outline" 
          onClick={currentStep === 0 ? onClose : prevStep}
        >
          {currentStep === 0 ? 'Cancel' : 'Back'}
        </Button>
        
        {isLastDataStep ? (
          <Button onClick={executeConversion} disabled={loading}>
            {loading ? (
              <>
                <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                Converting...
              </>
            ) : (
              <>
                Convert Lead
                <ArrowRight className="w-4 h-4 ml-2" />
              </>
            )}
          </Button>
        ) : (
          <Button onClick={nextStep}>
            Next
            <ArrowRight className="w-4 h-4 ml-2" />
          </Button>
        )}
      </div>
    );
  };

  return (
    <Modal
      isOpen={isOpen}
      onClose={onClose}
      title="Convert Lead"
      size="lg"
    >
      <div className="min-h-[400px]">
        {renderStepIndicator()}
        
        {error && (
          <div className="mb-4 p-3 bg-red-50 border border-red-200 rounded-lg flex items-center gap-2 text-red-700">
            <AlertCircle className="w-5 h-5" />
            <span>{error}</span>
          </div>
        )}
        
        <div className="mb-6">
          {renderStepContent()}
        </div>
        
        <div className="pt-4 border-t">
          {renderActions()}
        </div>
      </div>
    </Modal>
  );
}
