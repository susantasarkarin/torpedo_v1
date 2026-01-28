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
  FormControl,
  InputLabel,
  Select,
  MenuItem,
  LinearProgress,
  Divider,
} from '@mui/material';
import {
  Download as DownloadIcon,
  Email as EmailIcon,
  Person as PersonIcon,
  Summary as SummaryIcon,
  PlayArrow as PlayArrowIcon,
  Refresh as RefreshIcon,
  Visibility as VisibilityIcon,
} from '@mui/icons-material';

const API_BASE_URL = process.env.REACT_APP_API_URL || 'http://localhost:8000';

function TabPanel(props) {
  const { children, value, index, ...other } = props;
  return (
    <div
      role="tabpanel"
      hidden={value !== index}
      id={`mail-tabpanel-${index}`}
      aria-labelledby={`mail-tab-${index}`}
      {...other}
    >
      {value === index && <Box sx={{ p: 3 }}>{children}</Box>}
    </div>
  );
}

export default function MailOperations() {
  const [tabValue, setTabValue] = useState(0);
  const [loading, setLoading] = useState(false);
  const [segregationStats, setSegregationStats] = useState(null);
  const [summaries, setSummaries] = useState([]);
  const [contacts, setContacts] = useState([]);
  const [message, setMessage] = useState({ type: '', text: '' });

  // Dialog states
  const [segregateDialogOpen, setSegregateDialogOpen] = useState(false);
  const [summaryDialogOpen, setSummaryDialogOpen] = useState(false);
  const [contactsDialogOpen, setContactsDialogOpen] = useState(false);
  const [summaryDetailsOpen, setSummaryDetailsOpen] = useState(false);
  const [selectedSummary, setSelectedSummary] = useState(null);

  // Form states
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

  const strategies = [
    { value: 'category', label: 'By Category (Sales, Support, etc.)' },
    { value: 'sender_domain', label: 'By Sender Domain' },
    { value: 'priority', label: 'By Priority Level' },
    { value: 'intent', label: 'By Business Intent' },
    { value: 'engagement', label: 'By Engagement Level' },
    { value: 'custom', label: 'Custom Segmentation' },
  ];

  // Fetch segregation stats
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

  // Segregate emails
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

  // Generate mail summary
  const handleGenerateSummary = async () => {
    try {
      setLoading(true);
      const response = await fetch(`${API_BASE_URL}/api/mail/summary`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': localStorage.getItem('sessionToken') || '',
        },
        body: JSON.stringify(summaryForm),
      });
      
      if (!response.ok) throw new Error('Failed to generate summary');
      
      const data = await response.json();
      setSelectedSummary(data);
      setSummaryDetailsOpen(true);
      setMessage({ type: 'success', text: 'Summary generated successfully' });
      setSummaryDialogOpen(false);
    } catch (error) {
      setMessage({ type: 'error', text: error.message });
    } finally {
      setLoading(false);
    }
  };

  // Extract contacts
  const handleExtractContacts = async () => {
    try {
      setLoading(true);
      const response = await fetch(`${API_BASE_URL}/api/mail/extracted-contacts`, {
        headers: {
          'Authorization': localStorage.getItem('sessionToken') || '',
        },
      });
      
      if (!response.ok) throw new Error('Failed to fetch contacts');
      
      const data = await response.json();
      setContacts(data.contacts || []);
      setContactsDialogOpen(true);
    } catch (error) {
      setMessage({ type: 'error', text: error.message });
    } finally {
      setLoading(false);
    }
  };

  // Download contacts as CSV
  const handleDownloadContacts = () => {
    const headers = ['Name', 'Email', 'Phone', 'Company', 'Title', 'LinkedIn', 'Website'];
    const rows = contacts.map(c => [
      c.name,
      c.email,
      c.phone,
      c.company,
      c.title,
      c.linkedin,
      c.website,
    ]);
    
    const csv = [
      headers.join(','),
      ...rows.map(r => r.map(v => `"${v || ''}"`).join(',')),
    ].join('\n');
    
    const blob = new Blob([csv], { type: 'text/csv' });
    const url = window.URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `contacts_${new Date().toISOString().split('T')[0]}.csv`;
    a.click();
    window.URL.revokeObjectURL(url);
  };

  useEffect(() => {
    fetchSegregationStats();
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
          Mail Operations
        </Typography>
        <Typography variant="body2" color="textSecondary">
          Segregate emails, generate summaries, and extract contact information
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
                    {segregationStats.segregation_percentage}%
                  </Typography>
                </Box>
                <LinearProgress 
                  variant="determinate" 
                  value={segregationStats.segregation_percentage} 
                  sx={{ mt: 1 }}
                />
              </CardContent>
            </Card>
          </Grid>
        </Grid>
      )}

      <Paper sx={{ mb: 3 }}>
        <Tabs 
          value={tabValue} 
          onChange={(e, newValue) => setTabValue(newValue)}
          sx={{ borderBottom: '1px solid #e0e0e0' }}
        >
          <Tab label="Segregation" id="mail-tab-0" />
          <Tab label="Summaries" id="mail-tab-1" />
          <Tab label="Contacts" id="mail-tab-2" />
        </Tabs>

        {/* Segregation Tab */}
        <TabPanel value={tabValue} index={0}>
          <Box sx={{ mb: 3 }}>
            <Typography variant="h6" sx={{ mb: 2 }}>Email Segregation</Typography>
            <Typography variant="body2" color="textSecondary" sx={{ mb: 3 }}>
              Automatically segregate all emails in your mail pool using AI-powered categorization.
              Choose a strategy that best fits your needs.
            </Typography>
            <Button 
              variant="contained" 
              color="primary"
              startIcon={<PlayArrowIcon />}
              onClick={() => setSegregateDialogOpen(true)}
            >
              Start Segregation
            </Button>
          </Box>

          {segregationStats?.segment_breakdown && (
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
                    {segregationStats.segment_breakdown.map((segment) => {
                      const percentage = ((segment.count / segregationStats.total_emails) * 100).toFixed(1);
                      return (
                        <TableRow key={segment._id}>
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
        </TabPanel>

        {/* Summaries Tab */}
        <TabPanel value={tabValue} index={1}>
          <Box sx={{ mb: 3 }}>
            <Typography variant="h6" sx={{ mb: 2 }}>Mail Summaries</Typography>
            <Typography variant="body2" color="textSecondary" sx={{ mb: 3 }}>
              Generate AI-powered summaries of email segments to quickly understand key themes and action items.
            </Typography>
            <Button 
              variant="contained" 
              color="primary"
              startIcon={<SummaryIcon />}
              onClick={() => setSummaryDialogOpen(true)}
            >
              Generate Summary
            </Button>
          </Box>

          {summaries.length > 0 && (
            <Box sx={{ mt: 3 }}>
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
                        <Box sx={{ mb: 2 }}>
                          <Typography variant="caption" color="textSecondary">
                            <strong>Key Topics:</strong>
                          </Typography>
                          <Box sx={{ display: 'flex', gap: 1, flexWrap: 'wrap', mt: 1 }}>
                            {summary.key_topics?.map((topic, i) => (
                              <Chip key={i} label={topic} size="small" />
                            ))}
                          </Box>
                        </Box>
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

          {summaries.length === 0 && (
            <Box sx={{ textAlign: 'center', py: 4 }}>
              <Typography color="textSecondary">
                No summaries generated yet. Click "Generate Summary" to create one.
              </Typography>
            </Box>
          )}
        </TabPanel>

        {/* Contacts Tab */}
        <TabPanel value={tabValue} index={2}>
          <Box sx={{ mb: 3 }}>
            <Typography variant="h6" sx={{ mb: 2 }}>Extracted Contacts</Typography>
            <Typography variant="body2" color="textSecondary" sx={{ mb: 3 }}>
              View and manage contact information extracted from emails using AI.
              Export contacts for further use.
            </Typography>
            <Box sx={{ display: 'flex', gap: 2 }}>
              <Button 
                variant="contained" 
                color="primary"
                startIcon={<PersonIcon />}
                onClick={handleExtractContacts}
              >
                Load Contacts
              </Button>
            </Box>
          </Box>
        </TabPanel>
      </Paper>

      {/* Segregation Dialog */}
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

            <Box>
              <Typography variant="body2" sx={{ mb: 1 }}>
                <input 
                  type="checkbox"
                  checked={segregateForm.force_rescan}
                  onChange={(e) => setSegregateForm({ ...segregateForm, force_rescan: e.target.checked })}
                  style={{ marginRight: 8 }}
                />
                Force rescan already segregated emails
              </Typography>
              <Typography variant="caption" color="textSecondary">
                This will re-process all emails. Useful for testing or updating segmentation logic.
              </Typography>
            </Box>
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

              <Box>
                <Typography variant="subtitle2" gutterBottom>Action Items</Typography>
                {selectedSummary.action_items?.map((item, i) => (
                  <Typography key={i} variant="body2" sx={{ ml: 2 }}>• {item}</Typography>
                ))}
              </Box>

              <Box>
                <Typography variant="subtitle2" gutterBottom>Top Senders</Typography>
                {selectedSummary.top_senders?.map(([sender, count], i) => (
                  <Typography key={i} variant="body2" sx={{ ml: 2 }}>
                    {sender} ({count} emails)
                  </Typography>
                ))}
              </Box>
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
