/**
 * Company Upload Wizard
 * 
 * Multi-step wizard for uploading company CSV and triggering agent pipeline.
 * 
 * Steps:
 * 1. Upload CSV file
 * 2. Map columns to required fields
 * 3. Select agent configuration
 * 4. Review and confirm
 */

import React, { useState, useRef, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import Papa from 'papaparse';
import { 
  Upload, FileSpreadsheet, Settings, CheckCircle, 
  ArrowLeft, ArrowRight, X, AlertCircle, Building2,
  Users, Zap
} from 'lucide-react';
import { useLeadAgent } from '../../contexts/LeadAgentContext';
import { Button } from '../../components/ui/Button';
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from '../../components/ui/Card';

// Required and optional columns
const REQUIRED_COLUMNS = ['company_name', 'domain'];
const OPTIONAL_COLUMNS = ['industry', 'size', 'location', 'description'];
const ALL_COLUMNS = [...REQUIRED_COLUMNS, ...OPTIONAL_COLUMNS];

// Column aliases for auto-matching
const COLUMN_ALIASES = {
  company_name: ['company_name', 'company', 'name', 'company name', 'companyname', 'organization'],
  domain: ['domain', 'website', 'url', 'company_domain', 'web'],
  industry: ['industry', 'sector', 'vertical', 'business_type'],
  size: ['size', 'employees', 'employee_count', 'company_size', 'headcount'],
  location: ['location', 'headquarters', 'hq', 'city', 'country', 'address'],
  description: ['description', 'about', 'summary', 'notes'],
};

export default function CompanyUpload() {
  const navigate = useNavigate();
  const { uploadCompanies, configs, defaultConfigs, quota, isLoading } = useLeadAgent();
  const fileInputRef = useRef(null);

  // Wizard state
  const [step, setStep] = useState(1);
  const [file, setFile] = useState(null);
  const [csvData, setCsvData] = useState([]);
  const [csvColumns, setCsvColumns] = useState([]);
  const [columnMapping, setColumnMapping] = useState({});
  const [selectedConfig, setSelectedConfig] = useState(null);
  const [runAgentsAfter, setRunAgentsAfter] = useState(true);
  const [error, setError] = useState(null);
  const [uploadResult, setUploadResult] = useState(null);

  // Auto-match columns based on aliases
  const autoMatchColumns = useCallback((columns) => {
    const mapping = {};
    
    for (const targetCol of ALL_COLUMNS) {
      const aliases = COLUMN_ALIASES[targetCol] || [targetCol];
      
      for (const csvCol of columns) {
        const normalizedCsvCol = csvCol.toLowerCase().trim().replace(/[_\s-]/g, '');
        
        for (const alias of aliases) {
          const normalizedAlias = alias.toLowerCase().replace(/[_\s-]/g, '');
          if (normalizedCsvCol === normalizedAlias || normalizedCsvCol.includes(normalizedAlias)) {
            mapping[targetCol] = csvCol;
            break;
          }
        }
        if (mapping[targetCol]) break;
      }
    }
    
    return mapping;
  }, []);

  // Handle file selection
  const handleFileSelect = useCallback((selectedFile) => {
    if (!selectedFile) return;
    
    if (!selectedFile.name.endsWith('.csv')) {
      setError('Please select a CSV file');
      return;
    }
    
    setError(null);
    setFile(selectedFile);
    
    Papa.parse(selectedFile, {
      header: true,
      skipEmptyLines: true,
      complete: (result) => {
        if (result.errors.length > 0) {
          setError(`CSV parsing error: ${result.errors[0].message}`);
          return;
        }
        
        if (result.data.length === 0) {
          setError('CSV file is empty');
          return;
        }
        
        const columns = Object.keys(result.data[0] || {});
        setCsvData(result.data);
        setCsvColumns(columns);
        
        // Auto-match columns
        const autoMapping = autoMatchColumns(columns);
        setColumnMapping(autoMapping);
        
        // Move to step 2
        setStep(2);
      },
      error: (err) => {
        setError(`Failed to parse CSV: ${err.message}`);
      }
    });
  }, [autoMatchColumns]);

  // Handle drag and drop
  const handleDrop = useCallback((e) => {
    e.preventDefault();
    const droppedFile = e.dataTransfer.files[0];
    handleFileSelect(droppedFile);
  }, [handleFileSelect]);

  const handleDragOver = useCallback((e) => {
    e.preventDefault();
  }, []);

  // Handle column mapping change
  const handleMappingChange = (targetCol, csvCol) => {
    setColumnMapping(prev => ({
      ...prev,
      [targetCol]: csvCol || undefined
    }));
  };

  // Validate mapping
  const isMappingValid = () => {
    return REQUIRED_COLUMNS.every(col => columnMapping[col]);
  };

  // Handle upload
  const handleUpload = async () => {
    if (!file) return;
    
    setError(null);
    
    try {
      const result = await uploadCompanies(file, {
        runContactFinder: runAgentsAfter,
        configId: selectedConfig?.config_id || null,
      });
      
      setUploadResult(result);
      setStep(4);
    } catch (err) {
      setError(err.message);
    }
  };

  // Render step indicators
  const renderStepIndicator = () => (
    <div className="flex items-center justify-center mb-8">
      {[1, 2, 3, 4].map((s) => (
        <React.Fragment key={s}>
          <div 
            className={`flex items-center justify-center w-10 h-10 rounded-full font-semibold transition-colors ${
              s === step 
                ? 'bg-orange-500 text-white' 
                : s < step 
                  ? 'bg-green-500 text-white' 
                  : 'bg-gray-200 text-gray-500'
            }`}
          >
            {s < step ? <CheckCircle className="w-5 h-5" /> : s}
          </div>
          {s < 4 && (
            <div className={`w-16 h-1 mx-2 ${s < step ? 'bg-green-500' : 'bg-gray-200'}`} />
          )}
        </React.Fragment>
      ))}
    </div>
  );

  // Step 1: Upload
  const renderStep1 = () => (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Upload className="w-5 h-5" />
          Upload Company List
        </CardTitle>
        <CardDescription>
          Upload a CSV file with company information to find contacts
        </CardDescription>
      </CardHeader>
      <CardContent>
        <div
          onClick={() => fileInputRef.current?.click()}
          onDrop={handleDrop}
          onDragOver={handleDragOver}
          className="border-2 border-dashed border-gray-300 rounded-lg p-12 text-center cursor-pointer hover:border-orange-500 hover:bg-orange-50 transition-colors"
        >
          <FileSpreadsheet className="w-16 h-16 mx-auto text-gray-400 mb-4" />
          <p className="text-lg font-medium text-gray-700">
            Drop your CSV file here or click to browse
          </p>
          <p className="text-sm text-gray-500 mt-2">
            Required columns: company_name, domain
          </p>
          <input
            ref={fileInputRef}
            type="file"
            accept=".csv"
            className="hidden"
            onChange={(e) => handleFileSelect(e.target.files[0])}
          />
        </div>

        <div className="mt-6 p-4 bg-blue-50 rounded-lg">
          <h4 className="font-medium text-blue-800 mb-2">CSV Format Example</h4>
          <code className="text-sm text-blue-700 block">
            company_name,domain,industry,size,location<br/>
            Acme Corp,acme.com,Technology,100-500,San Francisco<br/>
            Beta Inc,beta.io,SaaS,50-100,New York
          </code>
        </div>
      </CardContent>
    </Card>
  );

  // Step 2: Map Columns
  const renderStep2 = () => (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Settings className="w-5 h-5" />
          Map Columns
        </CardTitle>
        <CardDescription>
          Match your CSV columns to the required fields
        </CardDescription>
      </CardHeader>
      <CardContent>
        <div className="mb-4 p-3 bg-gray-50 rounded-lg">
          <p className="text-sm text-gray-600">
            <strong>{csvData.length}</strong> companies found in <strong>{file?.name}</strong>
          </p>
        </div>

        <div className="space-y-4">
          {ALL_COLUMNS.map((targetCol) => (
            <div key={targetCol} className="flex items-center gap-4">
              <div className="w-40">
                <span className={`font-medium ${REQUIRED_COLUMNS.includes(targetCol) ? 'text-gray-900' : 'text-gray-600'}`}>
                  {targetCol.replace('_', ' ')}
                </span>
                {REQUIRED_COLUMNS.includes(targetCol) && (
                  <span className="text-red-500 ml-1">*</span>
                )}
              </div>
              <ArrowRight className="w-4 h-4 text-gray-400" />
              <select
                value={columnMapping[targetCol] || ''}
                onChange={(e) => handleMappingChange(targetCol, e.target.value)}
                className="flex-1 border border-gray-300 rounded-md px-3 py-2 focus:ring-2 focus:ring-orange-500 focus:border-orange-500"
              >
                <option value="">-- Select column --</option>
                {csvColumns.map((col) => (
                  <option key={col} value={col}>{col}</option>
                ))}
              </select>
            </div>
          ))}
        </div>

        {/* Preview */}
        <div className="mt-6">
          <h4 className="font-medium text-gray-700 mb-2">Preview (first 3 rows)</h4>
          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-gray-200 text-sm">
              <thead className="bg-gray-50">
                <tr>
                  {ALL_COLUMNS.filter(c => columnMapping[c]).map((col) => (
                    <th key={col} className="px-3 py-2 text-left font-medium text-gray-500">
                      {col}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-200">
                {csvData.slice(0, 3).map((row, i) => (
                  <tr key={i}>
                    {ALL_COLUMNS.filter(c => columnMapping[c]).map((col) => (
                      <td key={col} className="px-3 py-2 text-gray-900">
                        {row[columnMapping[col]] || '-'}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </CardContent>
    </Card>
  );

  // Step 3: Select Config
  const renderStep3 = () => {
    const allConfigs = [...defaultConfigs, ...configs];
    
    return (
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Zap className="w-5 h-5" />
            Configure Agents
          </CardTitle>
          <CardDescription>
            Select an agent configuration or use defaults
          </CardDescription>
        </CardHeader>
        <CardContent>
          {/* Run agents toggle */}
          <div className="mb-6 p-4 bg-gray-50 rounded-lg">
            <label className="flex items-center gap-3 cursor-pointer">
              <input
                type="checkbox"
                checked={runAgentsAfter}
                onChange={(e) => setRunAgentsAfter(e.target.checked)}
                className="w-5 h-5 text-orange-500 rounded focus:ring-orange-500"
              />
              <div>
                <span className="font-medium text-gray-900">Run AI agents after upload</span>
                <p className="text-sm text-gray-500">
                  Automatically find contacts, enrich data, and generate outreach emails
                </p>
              </div>
            </label>
          </div>

          {runAgentsAfter && (
            <>
              {/* Quota info */}
              <div className="mb-6 p-4 bg-blue-50 rounded-lg flex items-center gap-4">
                <Users className="w-6 h-6 text-blue-600" />
                <div>
                  <p className="font-medium text-blue-800">
                    Daily Quota: {quota.leads_today} / {quota.limit}
                  </p>
                  <p className="text-sm text-blue-600">
                    {quota.remaining} leads remaining today
                  </p>
                </div>
              </div>

              {/* Config selection */}
              <div className="space-y-3">
                <h4 className="font-medium text-gray-700">Select Configuration</h4>
                
                {/* Default option */}
                <div
                  onClick={() => setSelectedConfig(null)}
                  className={`p-4 border rounded-lg cursor-pointer transition-colors ${
                    selectedConfig === null 
                      ? 'border-orange-500 bg-orange-50' 
                      : 'border-gray-200 hover:border-gray-300'
                  }`}
                >
                  <div className="flex items-center gap-3">
                    <input
                      type="radio"
                      checked={selectedConfig === null}
                      onChange={() => setSelectedConfig(null)}
                      className="w-4 h-4 text-orange-500"
                    />
                    <div>
                      <span className="font-medium">Default Configuration</span>
                      <p className="text-sm text-gray-500">Use standard settings for all agents</p>
                    </div>
                  </div>
                </div>

                {/* Preset configs */}
                {allConfigs.map((config) => (
                  <div
                    key={config.config_id}
                    onClick={() => setSelectedConfig(config)}
                    className={`p-4 border rounded-lg cursor-pointer transition-colors ${
                      selectedConfig?.config_id === config.config_id 
                        ? 'border-orange-500 bg-orange-50' 
                        : 'border-gray-200 hover:border-gray-300'
                    }`}
                  >
                    <div className="flex items-center gap-3">
                      <input
                        type="radio"
                        checked={selectedConfig?.config_id === config.config_id}
                        onChange={() => setSelectedConfig(config)}
                        className="w-4 h-4 text-orange-500"
                      />
                      <div>
                        <span className="font-medium">{config.name}</span>
                        {config.is_default && (
                          <span className="ml-2 text-xs bg-blue-100 text-blue-700 px-2 py-0.5 rounded">
                            Preset
                          </span>
                        )}
                        <p className="text-sm text-gray-500">{config.description}</p>
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            </>
          )}
        </CardContent>
      </Card>
    );
  };

  // Step 4: Complete
  const renderStep4 = () => (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-green-600">
          <CheckCircle className="w-5 h-5" />
          Upload Complete
        </CardTitle>
      </CardHeader>
      <CardContent>
        {uploadResult && (
          <div className="space-y-4">
            <div className="grid grid-cols-2 gap-4">
              <div className="p-4 bg-green-50 rounded-lg text-center">
                <Building2 className="w-8 h-8 mx-auto text-green-600 mb-2" />
                <div className="text-2xl font-bold text-green-700">
                  {uploadResult.companies_imported}
                </div>
                <div className="text-sm text-green-600">Companies Imported</div>
              </div>
              <div className="p-4 bg-yellow-50 rounded-lg text-center">
                <AlertCircle className="w-8 h-8 mx-auto text-yellow-600 mb-2" />
                <div className="text-2xl font-bold text-yellow-700">
                  {uploadResult.duplicates_skipped}
                </div>
                <div className="text-sm text-yellow-600">Duplicates Skipped</div>
              </div>
            </div>

            {runAgentsAfter && (
              <div className="p-4 bg-blue-50 rounded-lg">
                <p className="text-blue-800">
                  <strong>AI Agents are now running!</strong> Finding contacts and enriching data...
                </p>
                <p className="text-sm text-blue-600 mt-1">
                  Check the Agent Dashboard for real-time progress.
                </p>
              </div>
            )}

            <div className="flex gap-4 mt-6">
              <Button
                variant="primary"
                onClick={() => navigate('/sales/agent-dashboard')}
              >
                View Agent Dashboard
              </Button>
              <Button
                variant="outline"
                onClick={() => {
                  setStep(1);
                  setFile(null);
                  setCsvData([]);
                  setCsvColumns([]);
                  setColumnMapping({});
                  setUploadResult(null);
                }}
              >
                Upload Another
              </Button>
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );

  return (
    <div className="min-h-screen bg-gray-50 py-8">
      <div className="max-w-3xl mx-auto px-4">
        {/* Header */}
        <div className="mb-8">
          <button 
            onClick={() => navigate(-1)}
            className="flex items-center text-gray-600 hover:text-gray-900 mb-4"
          >
            <ArrowLeft className="w-4 h-4 mr-2" />
            Back
          </button>
          <h1 className="text-2xl font-bold text-gray-900">Upload Companies</h1>
          <p className="text-gray-600">
            Upload a list of companies to find decision-makers and generate outreach
          </p>
        </div>

        {/* Step Indicator */}
        {renderStepIndicator()}

        {/* Error display */}
        {error && (
          <div className="mb-6 p-4 bg-red-50 border border-red-200 rounded-lg flex items-center gap-3">
            <AlertCircle className="w-5 h-5 text-red-500" />
            <span className="text-red-700">{error}</span>
            <button onClick={() => setError(null)} className="ml-auto">
              <X className="w-4 h-4 text-red-500" />
            </button>
          </div>
        )}

        {/* Step Content */}
        {step === 1 && renderStep1()}
        {step === 2 && renderStep2()}
        {step === 3 && renderStep3()}
        {step === 4 && renderStep4()}

        {/* Navigation */}
        {step > 1 && step < 4 && (
          <div className="mt-6 flex justify-between">
            <Button
              variant="outline"
              onClick={() => setStep(step - 1)}
            >
              <ArrowLeft className="w-4 h-4 mr-2" />
              Back
            </Button>
            
            {step === 2 && (
              <Button
                variant="primary"
                disabled={!isMappingValid()}
                onClick={() => setStep(3)}
              >
                Continue
                <ArrowRight className="w-4 h-4 ml-2" />
              </Button>
            )}
            
            {step === 3 && (
              <Button
                variant="primary"
                loading={isLoading}
                onClick={handleUpload}
              >
                {runAgentsAfter ? 'Upload & Run Agents' : 'Upload Companies'}
              </Button>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
