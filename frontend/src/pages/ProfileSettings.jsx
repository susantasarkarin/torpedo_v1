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

  useEffect(() => {
    fetchPrompts();
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
          <Tab label="Profile Settings" id="tab-1" />
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

        {/* Profile Settings Tab */}
        <TabPanel value={tabValue} index={1}>
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
    </Container>
  );
}
