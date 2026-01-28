import React, { useState, useEffect } from 'react';
import {
  Container,
  Grid,
  Paper,
  Typography,
  Card,
  CardContent,
  CardHeader,
  Box,
  Button,
  TextField,
  Switch,
  FormControlLabel,
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Chip,
  IconButton,
  Tooltip,
  Alert,
  CircularProgress,
  Tabs,
  Tab,
  Divider,
  MenuItem,
  Select,
  FormControl,
  InputLabel,
} from '@mui/material';
import {
  Edit as EditIcon,
  Delete as DeleteIcon,
  Save as SaveIcon,
  Close as CloseIcon,
  Add as AddIcon,
  ContentCopy as CopyIcon,
  History as HistoryIcon,
  Refresh as RefreshIcon,
  Download as DownloadIcon,
  Email as EmailIcon,
  Person as PersonIcon,
  Summary as SummaryIcon,
  PlayArrow as PlayArrowIcon,
  Visibility as VisibilityIcon,
} from '@mui/icons-material';

const API_BASE_URL = process.env.REACT_APP_API_URL || 'http://localhost:8000';

function TabPanel(props) {
  const { children, value, index, ...other } = props;
  return (
    <div
      role="tabpanel"
      hidden={value !== index}
      id={`tabpanel-${index}`}
      aria-labelledby={`tab-${index}`}
      {...other}
    >
      {value === index && <Box sx={{ p: 3 }}>{children}</Box>}
    </div>
  );
}

export default function ProfileSettings() {
  const [tabValue, setTabValue] = useState(0);
  const [loading, setLoading] = useState(false);
  const [prompts, setPrompts] = useState([]);
  const [selectedPrompt, setSelectedPrompt] = useState(null);
  const [editDialogOpen, setEditDialogOpen] = useState(false);
  const [createDialogOpen, setCreateDialogOpen] = useState(false);
  const [testDialogOpen, setTestDialogOpen] = useState(false);
  const [versionsDialogOpen, setVersionsDialogOpen] = useState(false);
  const [versions, setVersions] = useState([]);
  const [message, setMessage] = useState({ type: '', text: '' });
  const [testResult, setTestResult] = useState(null);

  // Mail Operations states
  const [segregationStats, setSegregationStats] = useState(null);
  const [summaries, setSummaries] = useState([]);
  const [contacts, setContacts] = useState([]);
  const [segregateDialogOpen, setSegregateDialogOpen] = useState(false);
  const [summaryDialogOpen, setSummaryDialogOpen] = useState(false);
  const [contactsDialogOpen, setContactsDialogOpen] = useState(false);
  const [summaryDetailsOpen, setSummaryDetailsOpen] = useState(false);
  const [selectedSummary, setSelectedSummary] = useState(null);
  const [segregateForm, setSegregateForm] = useState({
    strategy: 'category',
    batch_size: 100,
    force_rescan: false,
  });
  const [summaryForm, setSummaryForm] = useState({
    segment_name: '',
    date_from: '',
    date_to: '',
  });

  // Form states
  const [formData, setFormData] = useState({
    name: '',
    description: '',
    content: '',
    agent_type: 'mail_segregation',
    tags: [],
    parameters: {},
    is_active: true,
  });

  const [testData, setTestData] = useState({
    content: '',
    test_input: '',
    agent_type: 'mail_segregation',
  });

  // Gemini API Keys state
  const [geminiKeys, setGeminiKeys] = useState({
    gemini_api_key_1: '',
    gemini_api_key_2: '',
    gemini_api_key_3: '',
    gemini_api_key_4: '',
    gemini_api_key_5: '',
    gemini_api_key_6: '',
    gemini_api_key_7: '',
  });
  const [showKeys, setShowKeys] = useState(false);

  const agentTypes = [
    { value: 'mail_segregation', label: 'Mail Segregation' },
    { value: 'contact_extraction', label: 'Contact Extraction' },
    { value: 'mail_summary', label: 'Mail Summary' },
    { value: 'custom', label: 'Custom Agent' },
  ];

  // Fetch prompts
  const fetchPrompts = async (filter = {}) => {
    try {
      setLoading(true);
      const params = new URLSearchParams(filter);
      const response = await fetch(`${API_BASE_URL}/api/prompts?${params}`, {
        headers: {
          'Authorization': localStorage.getItem('sessionToken') || '',
        },
      });
      
      if (!response.ok) throw new Error('Failed to fetch prompts');
      
      const data = await response.json();
      setPrompts(data.prompts || []);
    } catch (error) {
      setMessage({ type: 'error', text: error.message });
    } finally {
      setLoading(false);
    }
  };

  // Fetch prompt versions
  const fetchVersions = async (promptId) => {
    try {
      const response = await fetch(`${API_BASE_URL}/api/prompts/${promptId}/versions`, {
        headers: {
          'Authorization': localStorage.getItem('sessionToken') || '',
        },
      });
      
      if (!response.ok) throw new Error('Failed to fetch versions');
      
      const data = await response.json();
      setVersions(data.versions || []);
      setVersionsDialogOpen(true);
    } catch (error) {
      setMessage({ type: 'error', text: error.message });
    }
  };

  // Create new prompt
  const handleCreatePrompt = async () => {
    try {
      setLoading(true);
      const response = await fetch(`${API_BASE_URL}/api/prompts/create`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': localStorage.getItem('sessionToken') || '',
        },
        body: JSON.stringify(formData),
      });
      
      if (!response.ok) throw new Error('Failed to create prompt');
      
      const data = await response.json();
      setMessage({ type: 'success', text: 'Prompt created successfully' });
      setCreateDialogOpen(false);
      resetForm();
      await fetchPrompts();
    } catch (error) {
      setMessage({ type: 'error', text: error.message });
    } finally {
      setLoading(false);
    }
  };

  // Update prompt
  const handleUpdatePrompt = async () => {
    if (!selectedPrompt) return;
    
    try {
      setLoading(true);
      const response = await fetch(`${API_BASE_URL}/api/prompts/${selectedPrompt.id}`, {
        method: 'PUT',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': localStorage.getItem('sessionToken') || '',
        },
        body: JSON.stringify(formData),
      });
      
      if (!response.ok) throw new Error('Failed to update prompt');
      
      const data = await response.json();
      setMessage({ 
        type: 'success', 
        text: data.version_created ? 'Prompt updated and new version created' : 'Prompt updated successfully' 
      });
      setEditDialogOpen(false);
      resetForm();
      await fetchPrompts();
    } catch (error) {
      setMessage({ type: 'error', text: error.message });
    } finally {
      setLoading(false);
    }
  };

  // Delete prompt
  const handleDeletePrompt = async (promptId) => {
    if (!window.confirm('Are you sure you want to delete this prompt?')) return;
    
    try {
      setLoading(true);
      const response = await fetch(`${API_BASE_URL}/api/prompts/${promptId}`, {
        method: 'DELETE',
        headers: {
          'Authorization': localStorage.getItem('sessionToken') || '',
        },
      });
      
      if (!response.ok) throw new Error('Failed to delete prompt');
      
      setMessage({ type: 'success', text: 'Prompt deleted successfully' });
      await fetchPrompts();
    } catch (error) {
      setMessage({ type: 'error', text: error.message });
    } finally {
      setLoading(false);
    }
  };

  // Test prompt
  const handleTestPrompt = async () => {
    try {
      setLoading(true);
      const response = await fetch(`${API_BASE_URL}/api/prompts/test`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': localStorage.getItem('sessionToken') || '',
        },
        body: JSON.stringify(testData),
      });
      
      if (!response.ok) throw new Error('Failed to test prompt');
      
      const data = await response.json();
      setTestResult(data);
      setMessage({ type: 'success', text: 'Prompt tested successfully' });
    } catch (error) {
      setMessage({ type: 'error', text: error.message });
    } finally {
      setLoading(false);
    }
  };

  // Rollback version
  const handleRollbackVersion = async (promptId, version) => {
    if (!window.confirm(`Are you sure you want to rollback to version ${version}?`)) return;
    
    try {
      setLoading(true);
      const response = await fetch(`${API_BASE_URL}/api/prompts/${promptId}/rollback/${version}`, {
        method: 'POST',
        headers: {
          'Authorization': localStorage.getItem('sessionToken') || '',
        },
      });
      
      if (!response.ok) throw new Error('Failed to rollback');
      
      const data = await response.json();
      setMessage({ type: 'success', text: data.message });
      setVersionsDialogOpen(false);
      await fetchPrompts();
    } catch (error) {
      setMessage({ type: 'error', text: error.message });
    } finally {
      setLoading(false);
    }
  };

  // Open edit dialog
  const handleOpenEdit = (prompt) => {
    setSelectedPrompt(prompt);
    setFormData({
      name: prompt.name,
      description: prompt.description,
      content: prompt.content,
      agent_type: prompt.agent_type,
      tags: prompt.tags,
      parameters: prompt.parameters,
      is_active: prompt.is_active,
    });
    setEditDialogOpen(true);
  };

  // Open create dialog
  const handleOpenCreate = () => {
    resetForm();
    setSelectedPrompt(null);
    setCreateDialogOpen(true);
  };

  // Reset form
  const resetForm = () => {
    setFormData({
      name: '',
      description: '',
      content: '',
      agent_type: 'mail_segregation',
      tags: [],
      parameters: {},
      is_active: true,
    });
  };

  // Copy to clipboard
  const handleCopyContent = (text) => {
    navigator.clipboard.writeText(text);
    setMessage({ type: 'success', text: 'Copied to clipboard' });
  };

  // Fetch Gemini API Keys
  const fetchGeminiKeys = async () => {
    try {
      setLoading(true);
      const response = await fetch(`${API_BASE_URL}/api/settings`, {
        headers: {
          'Authorization': localStorage.getItem('sessionToken') || '',
        },
      });
      
      if (!response.ok) throw new Error('Failed to fetch settings');
      
      const data = await response.json();
      setGeminiKeys({
        gemini_api_key_1: data.gemini_api_key_1 || '',
        gemini_api_key_2: data.gemini_api_key_2 || '',
        gemini_api_key_3: data.gemini_api_key_3 || '',
        gemini_api_key_4: data.gemini_api_key_4 || '',
        gemini_api_key_5: data.gemini_api_key_5 || '',
        gemini_api_key_6: data.gemini_api_key_6 || '',
        gemini_api_key_7: data.gemini_api_key_7 || '',
      });
    } catch (error) {
      setMessage({ type: 'error', text: error.message });
    } finally {
      setLoading(false);
    }
  };

  // Mail Operations Functions
  const strategies = [
    { value: 'category', label: 'By Category (Sales, Support, etc.)' },
    { value: 'sender_domain', label: 'By Sender Domain' },
    { value: 'priority', label: 'By Priority Level' },
    { value: 'intent', label: 'By Business Intent' },
    { value: 'engagement', label: 'By Engagement Level' },
    { value: 'custom', label: 'Custom Segmentation' },
  ];

  const fetchSegregationStats = async () => {
    try {
      setLoading(true);
      const response = await fetch(`${API_BASE_URL}/api/mail/segregation-stats`, {
        headers: {
          'Authorization': localStorage.getItem('sessionToken') || '',
        },
      });
      
      if (!response.ok) throw new Error('Failed to fetch stats');
      
      const data = await response.json();
      setSegregationStats(data);
    } catch (error) {
      setMessage({ type: 'error', text: error.message });
    } finally {
      setLoading(false);
    }
  };

  const handleSegregateEmails = async () => {
    try {
      setLoading(true);
      const response = await fetch(`${API_BASE_URL}/api/mail/segregate`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': localStorage.getItem('sessionToken') || '',
        },
        body: JSON.stringify(segregateForm),
      });
      
      if (!response.ok) throw new Error('Failed to segregate emails');
      
      const data = await response.json();
      setMessage({ 
        type: 'success', 
        text: `Successfully segregated ${data.processed} emails` 
      });
      setSummaries(data.segment_summaries || []);
      setSegregateDialogOpen(false);
      await fetchSegregationStats();
    } catch (error) {
      setMessage({ type: 'error', text: error.message });
    } finally {
      setLoading(false);
    }
  };

  const handleGenerateSummary = async () => {
    try {
      setLoading(true);
      const response = await fetch(`${API_BASE_URL}/api/mail/generate-summary`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': localStorage.getItem('sessionToken') || '',
        },
        body: JSON.stringify(summaryForm),
      });
      
      if (!response.ok) throw new Error('Failed to generate summary');
      
      const data = await response.json();
      setMessage({ type: 'success', text: 'Summary generated successfully' });
      setSummaries([data, ...summaries]);
      setSummaryDialogOpen(false);
    } catch (error) {
      setMessage({ type: 'error', text: error.message });
    } finally {
      setLoading(false);
    }
  };

  const handleExtractContacts = async () => {
    try {
      setLoading(true);
      const response = await fetch(`${API_BASE_URL}/api/mail/extract-contacts`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': localStorage.getItem('sessionToken') || '',
        },
      });
      
      if (!response.ok) throw new Error('Failed to extract contacts');
      
      const data = await response.json();
      setContacts(data.contacts || []);
      setContactsDialogOpen(true);
      setMessage({ type: 'success', text: `Extracted ${data.contacts?.length || 0} contacts` });
    } catch (error) {
      setMessage({ type: 'error', text: error.message });
    } finally {
      setLoading(false);
    }
  };

  const handleDownloadContacts = () => {
    if (contacts.length === 0) return;

    const csv = [
      ['Name', 'Email', 'Company', 'Title'],
      ...contacts.map(c => [c.name, c.email, c.company, c.title])
    ].map(row => row.join(',')).join('\\n');

    const blob = new Blob([csv], { type: 'text/csv' });
    const url = window.URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `contacts_${new Date().toISOString().split('T')[0]}.csv`;
    a.click();
    window.URL.revokeObjectURL(url);
  };

  // Save Gemini API Keys
  const handleSaveGeminiKeys = async () => {
    try {
      setLoading(true);
      const response = await fetch(`${API_BASE_URL}/api/settings`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': localStorage.getItem('sessionToken') || '',
        },
        body: JSON.stringify(geminiKeys),
      });
      
      if (!response.ok) throw new Error('Failed to save Gemini API keys');
      
      setMessage({ type: 'success', text: 'Gemini API keys saved successfully' });
    } catch (error) {
      setMessage({ type: 'error', text: error.message });
    } finally {
      setLoading(false);
    }
  };

  // Handle Gemini key input change
  const handleGeminiKeyChange = (keyName, value) => {
    setGeminiKeys(prev => ({
      ...prev,
      [keyName]: value
    }));
  };

  useEffect(() => {
    fetchPrompts();
    fetchGeminiKeys();
  }, []);

  // Clear message after 5 seconds
  useEffect(() => {
    if (message.text) {
      const timer = setTimeout(() => setMessage({ type: '', text: '' }), 5000);
      return () => clearTimeout(timer);
    }
  }, [message]);

  return (
    <Container maxWidth="lg" sx={{ py: 4 }}>
      <Box sx={{ mb: 4 }}>
        <Typography variant="h4" component="h1" gutterBottom sx={{ fontWeight: 'bold' }}>
          Profile & Settings
        </Typography>
        <Typography variant="body2" color="textSecondary">
          Manage your profile and configure AI agent prompts
        </Typography>
      </Box>

      {message.text && (
        <Alert 
          severity={message.type} 
          onClose={() => setMessage({ type: '', text: '' })}
          sx={{ mb: 3 }}
        >
          {message.text}
        </Alert>
      )}

      <Paper sx={{ mb: 3 }}>
        <Tabs 
          value={tabValue} 
          onChange={(e, newValue) => setTabValue(newValue)}
          sx={{ borderBottom: '1px solid #e0e0e0' }}
        >
          <Tab label="Prompt Management" id="tab-0" />
          <Tab label="Gemini API Keys" id="tab-1" />
          <Tab label="Mail Operations" id="tab-2" />
          <Tab label="Profile Settings" id="tab-3" />
        </Tabs>

        {/* Prompt Management Tab */}
        <TabPanel value={tabValue} index={0}>
          <Box sx={{ mb: 3, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <Typography variant="h6">Manage AI Agent Prompts</Typography>
            <Box>
              <Button 
                variant="contained" 
                color="primary" 
                startIcon={<AddIcon />}
                onClick={handleOpenCreate}
                sx={{ mr: 1 }}
              >
                New Prompt
              </Button>
              <Button 
                variant="outlined" 
                startIcon={<RefreshIcon />}
                onClick={() => fetchPrompts()}
              >
                Refresh
              </Button>
            </Box>
          </Box>

          {loading && <CircularProgress sx={{ my: 2 }} />}

          <TableContainer component={Paper} variant="outlined">
            <Table>
              <TableHead>
                <TableRow sx={{ backgroundColor: '#f5f5f5' }}>
                  <TableCell><strong>Name</strong></TableCell>
                  <TableCell><strong>Agent Type</strong></TableCell>
                  <TableCell><strong>Version</strong></TableCell>
                  <TableCell><strong>Status</strong></TableCell>
                  <TableCell align="center"><strong>Actions</strong></TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {prompts.map((prompt) => (
                  <TableRow key={prompt.id} hover>
                    <TableCell>
                      <Box>
                        <Typography variant="body2" sx={{ fontWeight: 500 }}>
                          {prompt.name}
                        </Typography>
                        <Typography variant="caption" color="textSecondary">
                          {prompt.description}
                        </Typography>
                      </Box>
                    </TableCell>
                    <TableCell>
                      <Chip 
                        label={prompt.agent_type} 
                        size="small" 
                        variant="outlined"
                      />
                    </TableCell>
                    <TableCell>v{prompt.version}</TableCell>
                    <TableCell>
                      <Chip 
                        label={prompt.is_active ? 'Active' : 'Inactive'}
                        color={prompt.is_active ? 'success' : 'default'}
                        size="small"
                      />
                    </TableCell>
                    <TableCell align="center">
                      <Tooltip title="Edit">
                        <IconButton 
                          size="small" 
                          onClick={() => handleOpenEdit(prompt)}
                        >
                          <EditIcon fontSize="small" />
                        </IconButton>
                      </Tooltip>
                      <Tooltip title="View Versions">
                        <IconButton 
                          size="small"
                          onClick={() => fetchVersions(prompt.id)}
                        >
                          <HistoryIcon fontSize="small" />
                        </IconButton>
                      </Tooltip>
                      <Tooltip title="Delete">
                        <IconButton 
                          size="small"
                          onClick={() => handleDeletePrompt(prompt.id)}
                          color="error"
                        >
                          <DeleteIcon fontSize="small" />
                        </IconButton>
                      </Tooltip>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </TableContainer>

          {prompts.length === 0 && !loading && (
            <Box sx={{ textAlign: 'center', py: 4 }}>
              <Typography color="textSecondary">No prompts found. Create your first prompt to get started.</Typography>
            </Box>
          )}
        </TabPanel>

        {/* Gemini API Keys Tab */}
        <TabPanel value={tabValue} index={1}>
          <Box sx={{ mb: 3, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <Typography variant="h6">Gemini API Keys Configuration</Typography>
            <Box>
              <Button
                variant="outlined"
                onClick={() => setShowKeys(!showKeys)}
                sx={{ mr: 1 }}
              >
                {showKeys ? 'Hide Keys' : 'Show Keys'}
              </Button>
              <Button
                variant="contained"
                color="primary"
                startIcon={<SaveIcon />}
                onClick={handleSaveGeminiKeys}
                disabled={loading}
              >
                Save Keys
              </Button>
            </Box>
          </Box>

          <Alert severity="info" sx={{ mb: 3 }}>
            Configure up to 7 Gemini API keys for automatic rotation. Each free-tier account has 15 RPM and 1,000 requests/day limits. 
            The system will automatically rotate between keys to maximize throughput (105 RPM, 7,000 requests/day total).
          </Alert>

          <Grid container spacing={3}>
            {[1, 2, 3, 4, 5, 6, 7].map((num) => (
              <Grid item xs={12} md={6} key={num}>
                <Card variant="outlined">
                  <CardContent>
                    <Typography variant="subtitle1" gutterBottom sx={{ fontWeight: 'bold' }}>
                      Gemini API Key {num}
                    </Typography>
                    <TextField
                      fullWidth
                      type={showKeys ? 'text' : 'password'}
                      label={`API Key ${num}`}
                      value={geminiKeys[`gemini_api_key_${num}`]}
                      onChange={(e) => handleGeminiKeyChange(`gemini_api_key_${num}`, e.target.value)}
                      placeholder="AIzaSy..."
                      variant="outlined"
                      helperText={geminiKeys[`gemini_api_key_${num}`] ? '✓ Key configured' : 'Empty - optional'}
                      InputProps={{
                        endAdornment: geminiKeys[`gemini_api_key_${num}`] && (
                          <IconButton
                            size="small"
                            onClick={() => handleCopyContent(geminiKeys[`gemini_api_key_${num}`])}
                          >
                            <CopyIcon fontSize="small" />
                          </IconButton>
                        ),
                      }}
                    />
                  </CardContent>
                </Card>
              </Grid>
            ))}
          </Grid>

          <Box sx={{ mt: 3 }}>
            <Card variant="outlined">
              <CardContent>
                <Typography variant="h6" gutterBottom>
                  How to Get Gemini API Keys
                </Typography>
                <Typography variant="body2" paragraph>
                  1. Go to <a href="https://makersuite.google.com/app/apikey" target="_blank" rel="noopener noreferrer">Google AI Studio</a>
                </Typography>
                <Typography variant="body2" paragraph>
                  2. Sign in with your Google account
                </Typography>
                <Typography variant="body2" paragraph>
                  3. Click "Get API Key" and create a new key
                </Typography>
                <Typography variant="body2" paragraph>
                  4. Copy the key and paste it in one of the fields above
                </Typography>
                <Typography variant="body2" paragraph>
                  5. Repeat with different Google accounts to get up to 7 keys for maximum throughput
                </Typography>
                <Divider sx={{ my: 2 }} />
                <Typography variant="subtitle2" gutterBottom>
                  Free Tier Limits (per key):
                </Typography>
                <Typography variant="body2">
                  • 15 requests per minute (RPM)
                </Typography>
                <Typography variant="body2">
                  • 1,000 requests per day
                </Typography>
                <Typography variant="body2" sx={{ mt: 1, fontWeight: 'bold' }}>
                  Total Capacity with 7 keys: 105 RPM, 7,000 requests/day
                </Typography>
              </CardContent>
            </Card>
          </Box>
        </TabPanel>

        {/* Mail Operations Tab */}
        <TabPanel value={tabValue} index={2}>
          <Box sx={{ mb: 4 }}>
            <Typography variant="h6" gutterBottom>Email Segregation & Management</Typography>
            <Typography variant="body2" color="textSecondary">
              Segregate emails, generate summaries, and extract contact information using AI
            </Typography>
          </Box>

          {/* Fetch stats when tab opens */}
          {tabValue === 2 && !segregationStats && fetchSegregationStats()}

          {/* Stats Overview */}
          {segregationStats && (
            <Grid container spacing={3} sx={{ mb: 4 }}>
              <Grid item xs={12} sm={6} md={3}>
                <Card>
                  <CardContent>
                    <Typography color="textSecondary" gutterBottom>
                      Total Emails
                    </Typography>
                    <Typography variant="h5">
                      {segregationStats.total_emails?.toLocaleString() || 0}
                    </Typography>
                  </CardContent>
                </Card>
              </Grid>
              <Grid item xs={12} sm={6} md={3}>
                <Card>
                  <CardContent>
                    <Typography color="textSecondary" gutterBottom>
                      Segregated
                    </Typography>
                    <Typography variant="h5">
                      {segregationStats.segregated_emails?.toLocaleString() || 0}
                    </Typography>
                  </CardContent>
                </Card>
              </Grid>
              <Grid item xs={12} sm={6} md={3}>
                <Card>
                  <CardContent>
                    <Typography color="textSecondary" gutterBottom>
                      Pending
                    </Typography>
                    <Typography variant="h5">
                      {segregationStats.pending_emails?.toLocaleString() || 0}
                    </Typography>
                  </CardContent>
                </Card>
              </Grid>
              <Grid item xs={12} sm={6} md={3}>
                <Card>
                  <CardContent>
                    <Typography color="textSecondary" gutterBottom>
                      Progress
                    </Typography>
                    <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                      <Typography variant="h5">
                        {segregationStats.segregation_percentage || 0}%
                      </Typography>
                    </Box>
                  </CardContent>
                </Card>
              </Grid>
            </Grid>
          )}

          {/* Action Buttons */}
          <Box sx={{ mb: 3, display: 'flex', gap: 2, flexWrap: 'wrap' }}>
            <Button 
              variant="contained" 
              color="primary"
              startIcon={<PlayArrowIcon />}
              onClick={() => setSegregateDialogOpen(true)}
            >
              Start Segregation
            </Button>
            <Button 
              variant="outlined" 
              color="primary"
              startIcon={<RefreshIcon />}
              onClick={fetchSegregationStats}
            >
              Refresh Stats
            </Button>
            <Button 
              variant="outlined" 
              color="primary"
              startIcon={<SummaryIcon />}
              onClick={() => setSummaryDialogOpen(true)}
            >
              Generate Summary
            </Button>
            <Button 
              variant="outlined" 
              color="primary"
              startIcon={<PersonIcon />}
              onClick={handleExtractContacts}
            >
              Extract Contacts
            </Button>
          </Box>

          {/* Segment Breakdown */}
          {segregationStats?.segment_breakdown && segregationStats.segment_breakdown.length > 0 && (
            <Box sx={{ mt: 3 }}>
              <Typography variant="h6" sx={{ mb: 2 }}>Segment Breakdown</Typography>
              <TableContainer component={Paper} variant="outlined">
                <Table>
                  <TableHead>
                    <TableRow sx={{ backgroundColor: '#f5f5f5' }}>
                      <TableCell><strong>Segment</strong></TableCell>
                      <TableCell align="right"><strong>Count</strong></TableCell>
                      <TableCell align="right"><strong>Percentage</strong></TableCell>
                    </TableRow>
                  </TableHead>
                  <TableBody>
                    {segregationStats.segment_breakdown.map((segment, idx) => {
                      const percentage = ((segment.count / segregationStats.total_emails) * 100).toFixed(1);
                      return (
                        <TableRow key={idx}>
                          <TableCell>{segment._id || 'Unclassified'}</TableCell>
                          <TableCell align="right">{segment.count.toLocaleString()}</TableCell>
                          <TableCell align="right">{percentage}%</TableCell>
                        </TableRow>
                      );
                    })}
                  </TableBody>
                </Table>
              </TableContainer>
            </Box>
          )}

          {/* Summaries Section */}
          {summaries.length > 0 && (
            <Box sx={{ mt: 4 }}>
              <Typography variant="h6" sx={{ mb: 2 }}>Recent Summaries</Typography>
              <Grid container spacing={2}>
                {summaries.map((summary, index) => (
                  <Grid item xs={12} md={6} key={index}>
                    <Card>
                      <CardHeader 
                        title={summary.segment_name}
                        subheader={`${summary.total_emails} emails`}
                      />
                      <CardContent>
                        <Typography variant="body2" sx={{ mb: 2 }}>
                          {summary.summary_text}
                        </Typography>
                        {summary.key_topics && summary.key_topics.length > 0 && (
                          <Box sx={{ mb: 2 }}>
                            <Typography variant="caption" color="textSecondary">
                              <strong>Key Topics:</strong>
                            </Typography>
                            <Box sx={{ display: 'flex', gap: 1, flexWrap: 'wrap', mt: 1 }}>
                              {summary.key_topics.map((topic, i) => (
                                <Chip key={i} label={topic} size="small" />
                              ))}
                            </Box>
                          </Box>
                        )}
                        <Typography variant="caption" color="textSecondary">
                          Created: {new Date(summary.created_at).toLocaleDateString()}
                        </Typography>
                      </CardContent>
                    </Card>
                  </Grid>
                ))}
              </Grid>
            </Box>
          )}
        </TabPanel>

        {/* Profile Settings Tab */}
        <TabPanel value={tabValue} index={3}>
          <Grid container spacing={3}>
            <Grid item xs={12} md={6}>
              <Card>
                <CardHeader title="Basic Information" />
                <CardContent>
                  <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
                    <TextField
                      label="Full Name"
                      fullWidth
                      defaultValue="Your Name"
                      variant="outlined"
                    />
                    <TextField
                      label="Email"
                      fullWidth
                      type="email"
                      defaultValue="your.email@example.com"
                      variant="outlined"
                    />
                    <TextField
                      label="Organization"
                      fullWidth
                      defaultValue="Your Organization"
                      variant="outlined"
                    />
                  </Box>
                </CardContent>
              </Card>
            </Grid>

            <Grid item xs={12} md={6}>
              <Card>
                <CardHeader title="Preferences" />
                <CardContent>
                  <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
                    <FormControlLabel
                      control={<Switch defaultChecked />}
                      label="Enable Email Notifications"
                    />
                    <FormControlLabel
                      control={<Switch defaultChecked />}
                      label="Enable Auto-Segregation"
                    />
                    <FormControlLabel
                      control={<Switch />}
                      label="Weekly Summary Report"
                    />
                    <FormControl fullWidth>
                      <InputLabel>Theme</InputLabel>
                      <Select defaultValue="light">
                        <MenuItem value="light">Light</MenuItem>
                        <MenuItem value="dark">Dark</MenuItem>
                        <MenuItem value="auto">Auto</MenuItem>
                      </Select>
                    </FormControl>
                  </Box>
                </CardContent>
              </Card>
            </Grid>

            <Grid item xs={12}>
              <Box sx={{ display: 'flex', gap: 2, justifyContent: 'flex-end' }}>
                <Button variant="outlined">Cancel</Button>
                <Button variant="contained" color="primary">Save Changes</Button>
              </Box>
            </Grid>
          </Grid>
        </TabPanel>
      </Paper>

      {/* Create Prompt Dialog */}
      <Dialog open={createDialogOpen} onClose={() => setCreateDialogOpen(false)} maxWidth="md" fullWidth>
        <DialogTitle>Create New Prompt</DialogTitle>
        <DialogContent sx={{ pt: 3 }}>
          <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
            <TextField
              label="Prompt Name"
              fullWidth
              value={formData.name}
              onChange={(e) => setFormData({ ...formData, name: e.target.value })}
              placeholder="e.g., Email Categorization Prompt"
            />
            <TextField
              label="Description"
              fullWidth
              multiline
              rows={2}
              value={formData.description}
              onChange={(e) => setFormData({ ...formData, description: e.target.value })}
              placeholder="Describe what this prompt does"
            />
            <FormControl fullWidth>
              <InputLabel>Agent Type</InputLabel>
              <Select
                value={formData.agent_type}
                onChange={(e) => setFormData({ ...formData, agent_type: e.target.value })}
                label="Agent Type"
              >
                {agentTypes.map((type) => (
                  <MenuItem key={type.value} value={type.value}>
                    {type.label}
                  </MenuItem>
                ))}
              </Select>
            </FormControl>
            <TextField
              label="Prompt Content"
              fullWidth
              multiline
              rows={8}
              value={formData.content}
              onChange={(e) => setFormData({ ...formData, content: e.target.value })}
              placeholder="Enter your prompt template here..."
              variant="outlined"
            />
            <FormControlLabel
              control={
                <Switch
                  checked={formData.is_active}
                  onChange={(e) => setFormData({ ...formData, is_active: e.target.checked })}
                />
              }
              label="Active"
            />
          </Box>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setCreateDialogOpen(false)}>Cancel</Button>
          <Button 
            onClick={handleCreatePrompt} 
            variant="contained" 
            color="primary"
            disabled={loading || !formData.name || !formData.content}
          >
            Create Prompt
          </Button>
        </DialogActions>
      </Dialog>

      {/* Edit Prompt Dialog */}
      <Dialog open={editDialogOpen} onClose={() => setEditDialogOpen(false)} maxWidth="md" fullWidth>
        <DialogTitle>Edit Prompt</DialogTitle>
        <DialogContent sx={{ pt: 3 }}>
          <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
            <TextField
              label="Prompt Name"
              fullWidth
              value={formData.name}
              onChange={(e) => setFormData({ ...formData, name: e.target.value })}
            />
            <TextField
              label="Description"
              fullWidth
              multiline
              rows={2}
              value={formData.description}
              onChange={(e) => setFormData({ ...formData, description: e.target.value })}
            />
            <FormControl fullWidth>
              <InputLabel>Agent Type</InputLabel>
              <Select
                value={formData.agent_type}
                onChange={(e) => setFormData({ ...formData, agent_type: e.target.value })}
                label="Agent Type"
              >
                {agentTypes.map((type) => (
                  <MenuItem key={type.value} value={type.value}>
                    {type.label}
                  </MenuItem>
                ))}
              </Select>
            </FormControl>
            <TextField
              label="Prompt Content"
              fullWidth
              multiline
              rows={8}
              value={formData.content}
              onChange={(e) => setFormData({ ...formData, content: e.target.value })}
              variant="outlined"
            />
            <FormControlLabel
              control={
                <Switch
                  checked={formData.is_active}
                  onChange={(e) => setFormData({ ...formData, is_active: e.target.checked })}
                />
              }
              label="Active"
            />
            <Typography variant="caption" color="info">
              Editing prompt will create a new version
            </Typography>
          </Box>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setEditDialogOpen(false)}>Cancel</Button>
          <Button 
            onClick={handleUpdatePrompt} 
            variant="contained" 
            color="primary"
            disabled={loading}
          >
            Update Prompt
          </Button>
        </DialogActions>
      </Dialog>

      {/* Versions Dialog */}
      <Dialog open={versionsDialogOpen} onClose={() => setVersionsDialogOpen(false)} maxWidth="md" fullWidth>
        <DialogTitle>Prompt Versions</DialogTitle>
        <DialogContent sx={{ pt: 3 }}>
          <TableContainer component={Paper} variant="outlined">
            <Table>
              <TableHead>
                <TableRow sx={{ backgroundColor: '#f5f5f5' }}>
                  <TableCell><strong>Version</strong></TableCell>
                  <TableCell><strong>Created</strong></TableCell>
                  <TableCell><strong>Notes</strong></TableCell>
                  <TableCell align="center"><strong>Actions</strong></TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {versions.map((version) => (
                  <TableRow key={version.version}>
                    <TableCell>v{version.version}</TableCell>
                    <TableCell>{new Date(version.created_at).toLocaleDateString()}</TableCell>
                    <TableCell>{version.notes}</TableCell>
                    <TableCell align="center">
                      <Tooltip title="Rollback to this version">
                        <IconButton 
                          size="small"
                          onClick={() => handleRollbackVersion(selectedPrompt?.id, version.version)}
                        >
                          <RefreshIcon fontSize="small" />
                        </IconButton>
                      </Tooltip>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </TableContainer>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setVersionsDialogOpen(false)}>Close</Button>
        </DialogActions>
      </Dialog>

      {/* Mail Segregation Dialog */}
      <Dialog open={segregateDialogOpen} onClose={() => setSegregateDialogOpen(false)} maxWidth="sm" fullWidth>
        <DialogTitle>Configure Email Segregation</DialogTitle>
        <DialogContent sx={{ pt: 3 }}>
          <Box sx={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
            <FormControl fullWidth>
              <InputLabel>Segregation Strategy</InputLabel>
              <Select
                value={segregateForm.strategy}
                onChange={(e) => setSegregateForm({ ...segregateForm, strategy: e.target.value })}
                label="Segregation Strategy"
              >
                {strategies.map((s) => (
                  <MenuItem key={s.value} value={s.value}>
                    {s.label}
                  </MenuItem>
                ))}
              </Select>
            </FormControl>

            <TextField
              label="Batch Size"
              type="number"
              fullWidth
              value={segregateForm.batch_size}
              onChange={(e) => setSegregateForm({ ...segregateForm, batch_size: parseInt(e.target.value) })}
              inputProps={{ min: 10, max: 1000 }}
            />

            <FormControlLabel
              control={
                <Switch
                  checked={segregateForm.force_rescan}
                  onChange={(e) => setSegregateForm({ ...segregateForm, force_rescan: e.target.checked })}
                />
              }
              label="Force rescan already segregated emails"
            />
            <Typography variant="caption" color="textSecondary">
              This will re-process all emails. Useful for testing or updating segmentation logic.
            </Typography>
          </Box>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setSegregateDialogOpen(false)}>Cancel</Button>
          <Button 
            onClick={handleSegregateEmails} 
            variant="contained" 
            color="primary"
            disabled={loading}
          >
            {loading ? <CircularProgress size={24} /> : 'Start Segregation'}
          </Button>
        </DialogActions>
      </Dialog>

      {/* Summary Dialog */}
      <Dialog open={summaryDialogOpen} onClose={() => setSummaryDialogOpen(false)} maxWidth="sm" fullWidth>
        <DialogTitle>Generate Mail Summary</DialogTitle>
        <DialogContent sx={{ pt: 3 }}>
          <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
            <TextField
              label="Segment Name (optional)"
              fullWidth
              placeholder="e.g., Sales, Support"
              value={summaryForm.segment_name}
              onChange={(e) => setSummaryForm({ ...summaryForm, segment_name: e.target.value })}
            />
            <TextField
              label="Date From"
              type="date"
              fullWidth
              InputLabelProps={{ shrink: true }}
              value={summaryForm.date_from}
              onChange={(e) => setSummaryForm({ ...summaryForm, date_from: e.target.value })}
            />
            <TextField
              label="Date To"
              type="date"
              fullWidth
              InputLabelProps={{ shrink: true }}
              value={summaryForm.date_to}
              onChange={(e) => setSummaryForm({ ...summaryForm, date_to: e.target.value })}
            />
          </Box>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setSummaryDialogOpen(false)}>Cancel</Button>
          <Button 
            onClick={handleGenerateSummary} 
            variant="contained" 
            color="primary"
            disabled={loading}
          >
            {loading ? <CircularProgress size={24} /> : 'Generate'}
          </Button>
        </DialogActions>
      </Dialog>

      {/* Summary Details Dialog */}
      <Dialog open={summaryDetailsOpen} onClose={() => setSummaryDetailsOpen(false)} maxWidth="md" fullWidth>
        <DialogTitle>{selectedSummary?.segment_name} Summary</DialogTitle>
        <DialogContent sx={{ pt: 3 }}>
          {selectedSummary && (
            <Box sx={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
              <Box>
                <Typography variant="subtitle2" gutterBottom>Summary</Typography>
                <Typography variant="body2">{selectedSummary.summary_text}</Typography>
              </Box>

              <Divider />

              <Box>
                <Typography variant="subtitle2" gutterBottom>Key Topics</Typography>
                <Box sx={{ display: 'flex', gap: 1, flexWrap: 'wrap' }}>
                  {selectedSummary.key_topics?.map((topic, i) => (
                    <Chip key={i} label={topic} />
                  ))}
                </Box>
              </Box>

              {selectedSummary.action_items && (
                <Box>
                  <Typography variant="subtitle2" gutterBottom>Action Items</Typography>
                  {selectedSummary.action_items.map((item, i) => (
                    <Typography key={i} variant="body2" sx={{ ml: 2 }}>• {item}</Typography>
                  ))}
                </Box>
              )}

              {selectedSummary.top_senders && (
                <Box>
                  <Typography variant="subtitle2" gutterBottom>Top Senders</Typography>
                  {selectedSummary.top_senders.map(([sender, count], i) => (
                    <Typography key={i} variant="body2" sx={{ ml: 2 }}>
                      {sender} ({count} emails)
                    </Typography>
                  ))}
                </Box>
              )}
            </Box>
          )}
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setSummaryDetailsOpen(false)}>Close</Button>
        </DialogActions>
      </Dialog>

      {/* Contacts Dialog */}
      <Dialog open={contactsDialogOpen} onClose={() => setContactsDialogOpen(false)} maxWidth="md" fullWidth>
        <DialogTitle>Extracted Contacts</DialogTitle>
        <DialogContent sx={{ pt: 3 }}>
          <Box sx={{ mb: 2 }}>
            <Button 
              variant="outlined"
              startIcon={<DownloadIcon />}
              onClick={handleDownloadContacts}
              disabled={contacts.length === 0}
            >
              Download as CSV
            </Button>
          </Box>

          {contacts.length > 0 ? (
            <TableContainer component={Paper} variant="outlined">
              <Table size="small">
                <TableHead>
                  <TableRow sx={{ backgroundColor: '#f5f5f5' }}>
                    <TableCell><strong>Name</strong></TableCell>
                    <TableCell><strong>Email</strong></TableCell>
                    <TableCell><strong>Company</strong></TableCell>
                    <TableCell><strong>Title</strong></TableCell>
                  </TableRow>
                </TableHead>
                <TableBody>
                  {contacts.map((contact, i) => (
                    <TableRow key={i}>
                      <TableCell>{contact.name}</TableCell>
                      <TableCell>{contact.email}</TableCell>
                      <TableCell>{contact.company}</TableCell>
                      <TableCell>{contact.title}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </TableContainer>
          ) : (
            <Typography color="textSecondary">No contacts found</Typography>
          )}
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setContactsDialogOpen(false)}>Close</Button>
        </DialogActions>
      </Dialog>
    </Container>
  );
}
