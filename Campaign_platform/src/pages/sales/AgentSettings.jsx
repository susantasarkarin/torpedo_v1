/**
 * Agent Settings
 * 
 * Configuration page for AI Lead Generation agents.
 * Allows users to:
 * - Select and manage agent presets
 * - Configure individual agent prompts
 * - Set scoring criteria and thresholds
 * - Preview agent behavior
 */

import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { 
  Settings, Save, RotateCcw, Copy, Trash2, Plus,
  Building2, Users, Sparkles, Star, Mail, 
  ChevronDown, ChevronRight, Check, AlertCircle
} from 'lucide-react';
import { useLeadAgent } from '../../contexts/LeadAgentContext';
import { Button } from '../../components/ui/Button';
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from '../../components/ui/Card';

// Agent definitions with icons and default prompts
const AGENT_DEFINITIONS = {
  company_discovery: {
    name: 'Company Discovery',
    icon: Building2,
    color: 'blue',
    description: 'Finds companies matching your Ideal Customer Profile (ICP)',
    defaultPrompt: `You are an expert B2B researcher. Search the web to find 10 companies that match this profile:

Industry: {industry}
Company Size: {size}
Location: {location}
Keywords: {keywords}

For each company, provide:
- Company name
- Domain/website
- Industry
- Approximate employee count
- Headquarters location
- Brief description

Return results as JSON array.`
  },
  contact_finder: {
    name: 'Contact Finder',
    icon: Users,
    color: 'green',
    description: 'Finds decision-makers and their contact information',
    defaultPrompt: `You are an expert at finding B2B contacts. For the company "{company_name}" ({domain}), find up to 3 decision-makers in these roles:

Target Roles: {target_roles}

For each contact, provide:
- Full name
- Job title
- LinkedIn URL (if available)
- Email pattern or verified email
- Department

Return results as JSON array.`
  },
  lead_enricher: {
    name: 'Lead Enricher',
    icon: Sparkles,
    color: 'purple',
    description: 'Enriches leads with additional data and insights',
    defaultPrompt: `You are a B2B data enrichment specialist. Enrich this lead with additional information:

Name: {name}
Company: {company}
Title: {title}

Find and add:
- Company funding/revenue info
- Recent company news
- Contact's professional background
- Social media profiles
- Technologies used by the company

Return enriched data as JSON.`
  },
  lead_scorer: {
    name: 'Lead Scorer',
    icon: Star,
    color: 'yellow',
    description: 'Scores and prioritizes leads based on fit and intent',
    defaultPrompt: `You are a lead scoring expert. Score this lead from 0-100:

Lead: {name} - {title} at {company}
Company Info: {company_info}

Scoring Criteria:
- ICP Fit (0-40): How well does the company match our ideal customer?
- Role Fit (0-30): Is this person a decision-maker for our product?
- Timing Signals (0-30): Any buying signals or recent relevant events?

Return JSON with:
- total_score (0-100)
- icp_fit_score
- role_fit_score
- timing_score
- classification (hot/warm/cold)
- reasoning`
  },
  outreach_composer: {
    name: 'Outreach Composer',
    icon: Mail,
    color: 'orange',
    description: 'Generates personalized email outreach drafts',
    defaultPrompt: `You are an expert cold email copywriter. Write a personalized outreach email:

Recipient: {name}, {title} at {company}
Company Info: {company_info}
Our Product: {our_product}
Value Proposition: {value_prop}

Requirements:
- Subject line under 50 characters
- Email body under 150 words
- Personalized opening referencing their company/role
- Clear value proposition
- Soft call-to-action
- Professional but conversational tone

Return JSON with:
- subject
- body
- personalization_points (array of what was personalized)`
  }
};

export default function AgentSettings() {
  const navigate = useNavigate();
  const { 
    configs, 
    defaultConfigs,
    fetchConfigs, 
    saveConfig, 
    deleteConfig,
    seedDefaultConfigs,
    isLoading 
  } = useLeadAgent();

  // State
  const [selectedConfig, setSelectedConfig] = useState(null);
  const [editedConfig, setEditedConfig] = useState(null);
  const [expandedAgents, setExpandedAgents] = useState({});
  const [hasChanges, setHasChanges] = useState(false);
  const [saveSuccess, setSaveSuccess] = useState(false);
  const [error, setError] = useState(null);

  // Fetch configs on mount
  useEffect(() => {
    fetchConfigs();
  }, [fetchConfigs]);

  // Create new config
  const handleNewConfig = () => {
    const newConfig = {
      config_id: null,
      name: 'New Configuration',
      description: 'Custom agent configuration',
      is_default: false,
      agents: {
        company_discovery: {
          enabled: true,
          prompt: AGENT_DEFINITIONS.company_discovery.defaultPrompt,
          temperature: 0.7,
        },
        contact_finder: {
          enabled: true,
          prompt: AGENT_DEFINITIONS.contact_finder.defaultPrompt,
          temperature: 0.7,
        },
        lead_enricher: {
          enabled: true,
          prompt: AGENT_DEFINITIONS.lead_enricher.defaultPrompt,
          temperature: 0.7,
        },
        lead_scorer: {
          enabled: true,
          prompt: AGENT_DEFINITIONS.lead_scorer.defaultPrompt,
          temperature: 0.3,
        },
        outreach_composer: {
          enabled: true,
          prompt: AGENT_DEFINITIONS.outreach_composer.defaultPrompt,
          temperature: 0.8,
        },
      },
      icp: {
        industries: [],
        company_sizes: [],
        locations: [],
        keywords: [],
      },
      scoring: {
        min_score_threshold: 50,
        auto_classify: true,
      },
    };
    
    setSelectedConfig(newConfig);
    setEditedConfig(newConfig);
    setHasChanges(true);
  };

  // Select existing config
  const handleSelectConfig = (config) => {
    setSelectedConfig(config);
    setEditedConfig(JSON.parse(JSON.stringify(config)));
    setHasChanges(false);
    setExpandedAgents({});
  };

  // Update config field
  const updateConfig = (path, value) => {
    setEditedConfig(prev => {
      const updated = { ...prev };
      const keys = path.split('.');
      let current = updated;
      
      for (let i = 0; i < keys.length - 1; i++) {
        current = current[keys[i]];
      }
      
      current[keys[keys.length - 1]] = value;
      return updated;
    });
    setHasChanges(true);
  };

  // Save config
  const handleSave = async () => {
    setError(null);
    setSaveSuccess(false);
    
    try {
      await saveConfig(editedConfig);
      setSaveSuccess(true);
      setHasChanges(false);
      fetchConfigs();
      
      setTimeout(() => setSaveSuccess(false), 3000);
    } catch (err) {
      setError(err.message);
    }
  };

  // Delete config
  const handleDelete = async () => {
    if (!selectedConfig?.config_id) return;
    if (!confirm('Are you sure you want to delete this configuration?')) return;
    
    try {
      await deleteConfig(selectedConfig.config_id);
      setSelectedConfig(null);
      setEditedConfig(null);
      fetchConfigs();
    } catch (err) {
      setError(err.message);
    }
  };

  // Duplicate config
  const handleDuplicate = () => {
    if (!selectedConfig) return;
    
    const duplicated = {
      ...JSON.parse(JSON.stringify(selectedConfig)),
      config_id: null,
      name: `${selectedConfig.name} (Copy)`,
      is_default: false,
    };
    
    setSelectedConfig(duplicated);
    setEditedConfig(duplicated);
    setHasChanges(true);
  };

  // Reset to defaults
  const handleReset = () => {
    if (!selectedConfig) return;
    setEditedConfig(JSON.parse(JSON.stringify(selectedConfig)));
    setHasChanges(false);
  };

  // Toggle agent expansion
  const toggleAgent = (agentKey) => {
    setExpandedAgents(prev => ({
      ...prev,
      [agentKey]: !prev[agentKey]
    }));
  };

  // All configs combined
  const allConfigs = [...defaultConfigs, ...configs];

  return (
    <div className="min-h-screen bg-gray-50 py-8">
      <div className="max-w-7xl mx-auto px-4">
        {/* Header */}
        <div className="flex items-center justify-between mb-8">
          <div>
            <h1 className="text-2xl font-bold text-gray-900">Agent Settings</h1>
            <p className="text-gray-600">Configure your AI lead generation agents</p>
          </div>
          <div className="flex gap-3">
            <Button
              variant="outline"
              onClick={() => navigate('/sales/agent-dashboard')}
            >
              Back to Dashboard
            </Button>
          </div>
        </div>

        <div className="grid grid-cols-12 gap-6">
          {/* Config List Sidebar */}
          <div className="col-span-3">
            <Card>
              <CardHeader>
                <CardTitle className="text-sm">Configurations</CardTitle>
              </CardHeader>
              <CardContent className="p-0">
                <div className="divide-y">
                  {allConfigs.map((config) => (
                    <button
                      key={config.config_id}
                      onClick={() => handleSelectConfig(config)}
                      className={`w-full px-4 py-3 text-left hover:bg-gray-50 transition-colors ${
                        selectedConfig?.config_id === config.config_id ? 'bg-orange-50 border-l-2 border-orange-500' : ''
                      }`}
                    >
                      <div className="font-medium text-gray-900 flex items-center gap-2">
                        {config.name}
                        {config.is_default && (
                          <span className="text-xs bg-blue-100 text-blue-700 px-1.5 py-0.5 rounded">
                            Preset
                          </span>
                        )}
                      </div>
                      <div className="text-xs text-gray-500 truncate">
                        {config.description}
                      </div>
                    </button>
                  ))}
                </div>
                
                <div className="p-4 border-t">
                  <Button
                    variant="outline"
                    size="sm"
                    className="w-full"
                    onClick={handleNewConfig}
                  >
                    <Plus className="w-4 h-4 mr-2" />
                    New Configuration
                  </Button>
                </div>
              </CardContent>
            </Card>

            {/* Seed Defaults */}
            {defaultConfigs.length === 0 && (
              <Card className="mt-4">
                <CardContent className="pt-6">
                  <p className="text-sm text-gray-600 mb-4">
                    No presets found. Load default configurations?
                  </p>
                  <Button
                    variant="primary"
                    size="sm"
                    className="w-full"
                    onClick={seedDefaultConfigs}
                    loading={isLoading}
                  >
                    Load Default Presets
                  </Button>
                </CardContent>
              </Card>
            )}
          </div>

          {/* Config Editor */}
          <div className="col-span-9">
            {!editedConfig ? (
              <Card>
                <CardContent className="py-16 text-center">
                  <Settings className="w-12 h-12 mx-auto text-gray-400 mb-4" />
                  <h3 className="text-lg font-medium text-gray-900 mb-2">
                    Select a Configuration
                  </h3>
                  <p className="text-gray-500 mb-4">
                    Choose a configuration from the sidebar to edit, or create a new one
                  </p>
                  <Button variant="primary" onClick={handleNewConfig}>
                    <Plus className="w-4 h-4 mr-2" />
                    Create New Configuration
                  </Button>
                </CardContent>
              </Card>
            ) : (
              <>
                {/* Error/Success messages */}
                {error && (
                  <div className="mb-4 p-4 bg-red-50 border border-red-200 rounded-lg flex items-center gap-3">
                    <AlertCircle className="w-5 h-5 text-red-500" />
                    <span className="text-red-700">{error}</span>
                  </div>
                )}
                
                {saveSuccess && (
                  <div className="mb-4 p-4 bg-green-50 border border-green-200 rounded-lg flex items-center gap-3">
                    <Check className="w-5 h-5 text-green-500" />
                    <span className="text-green-700">Configuration saved successfully!</span>
                  </div>
                )}

                {/* Basic Info */}
                <Card className="mb-6">
                  <CardHeader>
                    <CardTitle>Basic Information</CardTitle>
                  </CardHeader>
                  <CardContent>
                    <div className="grid grid-cols-2 gap-4">
                      <div>
                        <label className="block text-sm font-medium text-gray-700 mb-1">
                          Configuration Name
                        </label>
                        <input
                          type="text"
                          value={editedConfig.name}
                          onChange={(e) => updateConfig('name', e.target.value)}
                          className="w-full border border-gray-300 rounded-md px-3 py-2"
                          disabled={editedConfig.is_default}
                        />
                      </div>
                      <div>
                        <label className="block text-sm font-medium text-gray-700 mb-1">
                          Description
                        </label>
                        <input
                          type="text"
                          value={editedConfig.description}
                          onChange={(e) => updateConfig('description', e.target.value)}
                          className="w-full border border-gray-300 rounded-md px-3 py-2"
                          disabled={editedConfig.is_default}
                        />
                      </div>
                    </div>
                  </CardContent>
                </Card>

                {/* ICP Settings */}
                <Card className="mb-6">
                  <CardHeader>
                    <CardTitle>Ideal Customer Profile (ICP)</CardTitle>
                    <CardDescription>
                      Define your target companies for the Company Discovery agent
                    </CardDescription>
                  </CardHeader>
                  <CardContent>
                    <div className="grid grid-cols-2 gap-4">
                      <div>
                        <label className="block text-sm font-medium text-gray-700 mb-1">
                          Industries (comma-separated)
                        </label>
                        <input
                          type="text"
                          value={editedConfig.icp?.industries?.join(', ') || ''}
                          onChange={(e) => updateConfig('icp.industries', e.target.value.split(',').map(s => s.trim()).filter(Boolean))}
                          className="w-full border border-gray-300 rounded-md px-3 py-2"
                          placeholder="SaaS, FinTech, HealthTech"
                        />
                      </div>
                      <div>
                        <label className="block text-sm font-medium text-gray-700 mb-1">
                          Company Sizes
                        </label>
                        <input
                          type="text"
                          value={editedConfig.icp?.company_sizes?.join(', ') || ''}
                          onChange={(e) => updateConfig('icp.company_sizes', e.target.value.split(',').map(s => s.trim()).filter(Boolean))}
                          className="w-full border border-gray-300 rounded-md px-3 py-2"
                          placeholder="50-100, 100-500, 500+"
                        />
                      </div>
                      <div>
                        <label className="block text-sm font-medium text-gray-700 mb-1">
                          Locations
                        </label>
                        <input
                          type="text"
                          value={editedConfig.icp?.locations?.join(', ') || ''}
                          onChange={(e) => updateConfig('icp.locations', e.target.value.split(',').map(s => s.trim()).filter(Boolean))}
                          className="w-full border border-gray-300 rounded-md px-3 py-2"
                          placeholder="USA, UK, Germany"
                        />
                      </div>
                      <div>
                        <label className="block text-sm font-medium text-gray-700 mb-1">
                          Keywords
                        </label>
                        <input
                          type="text"
                          value={editedConfig.icp?.keywords?.join(', ') || ''}
                          onChange={(e) => updateConfig('icp.keywords', e.target.value.split(',').map(s => s.trim()).filter(Boolean))}
                          className="w-full border border-gray-300 rounded-md px-3 py-2"
                          placeholder="cloud, enterprise, B2B"
                        />
                      </div>
                    </div>
                  </CardContent>
                </Card>

                {/* Agent Configurations */}
                <Card className="mb-6">
                  <CardHeader>
                    <CardTitle>Agent Prompts</CardTitle>
                    <CardDescription>
                      Customize the prompts for each agent
                    </CardDescription>
                  </CardHeader>
                  <CardContent>
                    <div className="space-y-2">
                      {Object.entries(AGENT_DEFINITIONS).map(([key, agent]) => {
                        const Icon = agent.icon;
                        const isExpanded = expandedAgents[key];
                        const agentConfig = editedConfig.agents?.[key] || {};
                        
                        return (
                          <div key={key} className="border rounded-lg overflow-hidden">
                            <button
                              onClick={() => toggleAgent(key)}
                              className="w-full px-4 py-3 flex items-center justify-between bg-gray-50 hover:bg-gray-100"
                            >
                              <div className="flex items-center gap-3">
                                <div className={`p-2 rounded-lg bg-${agent.color}-100`}>
                                  <Icon className={`w-4 h-4 text-${agent.color}-600`} />
                                </div>
                                <div className="text-left">
                                  <div className="font-medium text-gray-900">{agent.name}</div>
                                  <div className="text-xs text-gray-500">{agent.description}</div>
                                </div>
                              </div>
                              <div className="flex items-center gap-3">
                                <label className="flex items-center gap-2" onClick={(e) => e.stopPropagation()}>
                                  <input
                                    type="checkbox"
                                    checked={agentConfig.enabled !== false}
                                    onChange={(e) => updateConfig(`agents.${key}.enabled`, e.target.checked)}
                                    className="w-4 h-4 text-orange-500 rounded"
                                  />
                                  <span className="text-sm text-gray-600">Enabled</span>
                                </label>
                                {isExpanded ? (
                                  <ChevronDown className="w-5 h-5 text-gray-400" />
                                ) : (
                                  <ChevronRight className="w-5 h-5 text-gray-400" />
                                )}
                              </div>
                            </button>
                            
                            {isExpanded && (
                              <div className="p-4 border-t bg-white">
                                <div className="mb-4">
                                  <label className="block text-sm font-medium text-gray-700 mb-1">
                                    System Prompt
                                  </label>
                                  <textarea
                                    value={agentConfig.prompt || agent.defaultPrompt}
                                    onChange={(e) => updateConfig(`agents.${key}.prompt`, e.target.value)}
                                    className="w-full border border-gray-300 rounded-md px-3 py-2 font-mono text-sm h-48"
                                    placeholder={agent.defaultPrompt}
                                  />
                                  <p className="text-xs text-gray-500 mt-1">
                                    Use {'{variable}'} placeholders for dynamic content
                                  </p>
                                </div>
                                
                                <div className="flex items-center gap-4">
                                  <div className="flex-1">
                                    <label className="block text-sm font-medium text-gray-700 mb-1">
                                      Temperature ({agentConfig.temperature || 0.7})
                                    </label>
                                    <input
                                      type="range"
                                      min="0"
                                      max="1"
                                      step="0.1"
                                      value={agentConfig.temperature || 0.7}
                                      onChange={(e) => updateConfig(`agents.${key}.temperature`, parseFloat(e.target.value))}
                                      className="w-full"
                                    />
                                    <div className="flex justify-between text-xs text-gray-500">
                                      <span>Precise</span>
                                      <span>Creative</span>
                                    </div>
                                  </div>
                                  
                                  <Button
                                    variant="ghost"
                                    size="sm"
                                    onClick={() => updateConfig(`agents.${key}.prompt`, agent.defaultPrompt)}
                                  >
                                    <RotateCcw className="w-4 h-4 mr-1" />
                                    Reset
                                  </Button>
                                </div>
                              </div>
                            )}
                          </div>
                        );
                      })}
                    </div>
                  </CardContent>
                </Card>

                {/* Scoring Settings */}
                <Card className="mb-6">
                  <CardHeader>
                    <CardTitle>Scoring Settings</CardTitle>
                  </CardHeader>
                  <CardContent>
                    <div className="grid grid-cols-2 gap-4">
                      <div>
                        <label className="block text-sm font-medium text-gray-700 mb-1">
                          Minimum Score Threshold
                        </label>
                        <input
                          type="number"
                          min="0"
                          max="100"
                          value={editedConfig.scoring?.min_score_threshold || 50}
                          onChange={(e) => updateConfig('scoring.min_score_threshold', parseInt(e.target.value))}
                          className="w-full border border-gray-300 rounded-md px-3 py-2"
                        />
                        <p className="text-xs text-gray-500 mt-1">
                          Leads below this score will be marked as cold
                        </p>
                      </div>
                      <div>
                        <label className="flex items-center gap-2 mt-6">
                          <input
                            type="checkbox"
                            checked={editedConfig.scoring?.auto_classify !== false}
                            onChange={(e) => updateConfig('scoring.auto_classify', e.target.checked)}
                            className="w-4 h-4 text-orange-500 rounded"
                          />
                          <span className="text-sm text-gray-700">
                            Auto-classify leads (hot/warm/cold)
                          </span>
                        </label>
                      </div>
                    </div>
                  </CardContent>
                </Card>

                {/* Actions */}
                <div className="flex items-center justify-between">
                  <div className="flex gap-3">
                    {!editedConfig.is_default && selectedConfig?.config_id && (
                      <Button
                        variant="ghost"
                        onClick={handleDelete}
                        className="text-red-600 hover:text-red-700 hover:bg-red-50"
                      >
                        <Trash2 className="w-4 h-4 mr-2" />
                        Delete
                      </Button>
                    )}
                    <Button
                      variant="outline"
                      onClick={handleDuplicate}
                    >
                      <Copy className="w-4 h-4 mr-2" />
                      Duplicate
                    </Button>
                  </div>
                  
                  <div className="flex gap-3">
                    {hasChanges && (
                      <Button
                        variant="outline"
                        onClick={handleReset}
                      >
                        <RotateCcw className="w-4 h-4 mr-2" />
                        Discard Changes
                      </Button>
                    )}
                    <Button
                      variant="primary"
                      onClick={handleSave}
                      loading={isLoading}
                      disabled={!hasChanges}
                    >
                      <Save className="w-4 h-4 mr-2" />
                      Save Configuration
                    </Button>
                  </div>
                </div>
              </>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
