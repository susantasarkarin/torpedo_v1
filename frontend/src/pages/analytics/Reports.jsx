import React, { useState, useEffect } from 'react';
import {
  Container,
  Grid,
  Paper,
  Typography,
  Box,
  Button,
  TextField,
  FormControl,
  InputLabel,
  Select,
  MenuItem,
  Chip,
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  IconButton,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Card,
  CardContent,
  CardActions,
  Checkbox,
  FormGroup,
  FormControlLabel,
  Divider,
  Alert,
  CircularProgress,
  Tabs,
  Tab
} from '@mui/material';
import {
  Add,
  Download,
  Schedule,
  Delete,
  Edit,
  Assessment,
  FilterList,
  CalendarToday,
  PictureAsPdf,
  TableChart,
  Email
} from '@mui/icons-material';
import { DatePicker } from '@mui/x-date-pickers/DatePicker';
import { LocalizationProvider } from '@mui/x-date-pickers/LocalizationProvider';
import { AdapterDateFns } from '@mui/x-date-pickers/AdapterDateFns';
import axios from 'axios';

const Reports = () => {
  const [tabValue, setTabValue] = useState(0);
  const [reports, setReports] = useState([]);
  const [scheduledReports, setScheduledReports] = useState([]);
  const [loading, setLoading] = useState(false);
  
  // Report Builder State
  const [builderOpen, setBuilderOpen] = useState(false);
  const [selectedMetrics, setSelectedMetrics] = useState([]);
  const [selectedFilters, setSelectedFilters] = useState({});
  const [dateRange, setDateRange] = useState({
    start: new Date(Date.now() - 30 * 24 * 60 * 60 * 1000),
    end: new Date()
  });
  const [groupBy, setGroupBy] = useState('day');

  // Schedule Dialog State
  const [scheduleOpen, setScheduleOpen] = useState(false);
  const [scheduleConfig, setScheduleConfig] = useState({
    frequency: 'weekly',
    recipients: '',
    format: 'pdf'
  });

  const availableMetrics = [
    { key: 'total_leads', label: 'Total Leads', category: 'Volume' },
    { key: 'total_campaigns', label: 'Total Campaigns', category: 'Volume' },
    { key: 'emails_sent', label: 'Emails Sent', category: 'Volume' },
    { key: 'opens', label: 'Opens', category: 'Engagement' },
    { key: 'clicks', label: 'Clicks', category: 'Engagement' },
    { key: 'replies', label: 'Replies', category: 'Engagement' },
    { key: 'meetings_booked', label: 'Meetings Booked', category: 'Conversion' },
    { key: 'open_rate', label: 'Open Rate', category: 'Rates' },
    { key: 'click_rate', label: 'Click Rate', category: 'Rates' },
    { key: 'reply_rate', label: 'Reply Rate', category: 'Rates' },
    { key: 'meeting_rate', label: 'Meeting Rate', category: 'Rates' },
    { key: 'conversion_rate', label: 'Conversion Rate', category: 'Rates' },
    { key: 'revenue_generated', label: 'Revenue Generated', category: 'Revenue' },
    { key: 'avg_deal_size', label: 'Avg Deal Size', category: 'Revenue' },
    { key: 'pipeline_value', label: 'Pipeline Value', category: 'Revenue' },
    { key: 'roi', label: 'ROI', category: 'Revenue' },
    { key: 'cost_per_lead', label: 'Cost Per Lead', category: 'Efficiency' },
    { key: 'cost_per_meeting', label: 'Cost Per Meeting', category: 'Efficiency' }
  ];

  const availableFilters = [
    { key: 'campaign_type', label: 'Campaign Type', type: 'select' },
    { key: 'industry', label: 'Industry', type: 'select' },
    { key: 'seniority', label: 'Seniority', type: 'select' },
    { key: 'lead_source', label: 'Lead Source', type: 'select' },
    { key: 'team_member', label: 'Team Member', type: 'select' }
  ];

  useEffect(() => {
    loadReports();
    loadScheduledReports();
  }, []);

  const loadReports = async () => {
    try {
      const response = await axios.get('/api/analytics/reports');
      setReports(response.data);
    } catch (error) {
      console.error('Error loading reports:', error);
    }
  };

  const loadScheduledReports = async () => {
    try {
      const response = await axios.get('/api/analytics/scheduled-reports');
      setScheduledReports(response.data);
    } catch (error) {
      console.error('Error loading scheduled reports:', error);
    }
  };

  const handleMetricToggle = (metricKey) => {
    setSelectedMetrics(prev =>
      prev.includes(metricKey)
        ? prev.filter(m => m !== metricKey)
        : [...prev, metricKey]
    );
  };

  const handleBuildReport = async () => {
    if (selectedMetrics.length === 0) {
      alert('Please select at least one metric');
      return;
    }

    setLoading(true);
    try {
      const response = await axios.post('/api/analytics/build-report', {
        metrics: selectedMetrics,
        filters: selectedFilters,
        date_range: [dateRange.start.toISOString(), dateRange.end.toISOString()],
        group_by: groupBy
      });

      alert('Report generated successfully!');
      setBuilderOpen(false);
      loadReports();
    } catch (error) {
      console.error('Error building report:', error);
      alert('Error building report');
    } finally {
      setLoading(false);
    }
  };

  const handleExportReport = async (reportId, format) => {
    try {
      const response = await axios.get(`/api/analytics/export-report/${reportId}`, {
        params: { format },
        responseType: 'blob'
      });

      const url = window.URL.createObjectURL(new Blob([response.data]));
      const link = document.createElement('a');
      link.href = url;
      link.setAttribute('download', `report-${reportId}.${format}`);
      document.body.appendChild(link);
      link.click();
      link.remove();
    } catch (error) {
      console.error('Error exporting report:', error);
    }
  };

  const handleScheduleReport = async () => {
    if (!scheduleConfig.recipients) {
      alert('Please enter recipient email addresses');
      return;
    }

    try {
      const recipients = scheduleConfig.recipients.split(',').map(e => e.trim());
      
      await axios.post('/api/analytics/schedule-report', {
        report_config: {
          metrics: selectedMetrics,
          filters: selectedFilters
        },
        frequency: scheduleConfig.frequency,
        recipients: recipients,
        format: scheduleConfig.format
      });

      alert('Report scheduled successfully!');
      setScheduleOpen(false);
      loadScheduledReports();
    } catch (error) {
      console.error('Error scheduling report:', error);
      alert('Error scheduling report');
    }
  };

  const handleCancelScheduledReport = async (jobId) => {
    try {
      await axios.delete(`/api/analytics/scheduled-reports/${jobId}`);
      alert('Scheduled report cancelled');
      loadScheduledReports();
    } catch (error) {
      console.error('Error cancelling report:', error);
    }
  };

  const MetricSelector = () => {
    const categories = [...new Set(availableMetrics.map(m => m.category))];

    return (
      <Box>
        <Typography variant="h6" gutterBottom>
          Select Metrics
        </Typography>
        {categories.map(category => (
          <Box key={category} mb={2}>
            <Typography variant="subtitle2" color="textSecondary" gutterBottom>
              {category}
            </Typography>
            <FormGroup row>
              {availableMetrics
                .filter(m => m.category === category)
                .map(metric => (
                  <FormControlLabel
                    key={metric.key}
                    control={
                      <Checkbox
                        checked={selectedMetrics.includes(metric.key)}
                        onChange={() => handleMetricToggle(metric.key)}
                      />
                    }
                    label={metric.label}
                  />
                ))}
            </FormGroup>
          </Box>
        ))}
      </Box>
    );
  };

  const FilterSelector = () => (
    <Box>
      <Typography variant="h6" gutterBottom>
        Filters
      </Typography>
      <Grid container spacing={2}>
        {availableFilters.map(filter => (
          <Grid item xs={12} sm={6} key={filter.key}>
            <TextField
              fullWidth
              label={filter.label}
              variant="outlined"
              size="small"
              value={selectedFilters[filter.key] || ''}
              onChange={(e) => setSelectedFilters(prev => ({
                ...prev,
                [filter.key]: e.target.value
              }))}
            />
          </Grid>
        ))}
      </Grid>
    </Box>
  );

  const DateRangeSelector = () => (
    <LocalizationProvider dateAdapter={AdapterDateFns}>
      <Box>
        <Typography variant="h6" gutterBottom>
          Date Range
        </Typography>
        <Grid container spacing={2}>
          <Grid item xs={12} sm={6}>
            <DatePicker
              label="Start Date"
              value={dateRange.start}
              onChange={(date) => setDateRange(prev => ({ ...prev, start: date }))}
              renderInput={(params) => <TextField {...params} fullWidth />}
            />
          </Grid>
          <Grid item xs={12} sm={6}>
            <DatePicker
              label="End Date"
              value={dateRange.end}
              onChange={(date) => setDateRange(prev => ({ ...prev, end: date }))}
              renderInput={(params) => <TextField {...params} fullWidth />}
            />
          </Grid>
        </Grid>
        <Box mt={2}>
          <FormControl fullWidth variant="outlined" size="small">
            <InputLabel>Group By</InputLabel>
            <Select
              value={groupBy}
              onChange={(e) => setGroupBy(e.target.value)}
              label="Group By"
            >
              <MenuItem value="day">Day</MenuItem>
              <MenuItem value="week">Week</MenuItem>
              <MenuItem value="month">Month</MenuItem>
            </Select>
          </FormControl>
        </Box>
      </Box>
    </LocalizationProvider>
  );

  const ReportBuilderDialog = () => (
    <Dialog open={builderOpen} onClose={() => setBuilderOpen(false)} maxWidth="md" fullWidth>
      <DialogTitle>
        <Box display="flex" alignItems="center">
          <Assessment style={{ marginRight: 8 }} />
          Custom Report Builder
        </Box>
      </DialogTitle>
      <DialogContent dividers>
        <Box mb={3}>
          <MetricSelector />
        </Box>
        <Divider style={{ margin: '24px 0' }} />
        <Box mb={3}>
          <FilterSelector />
        </Box>
        <Divider style={{ margin: '24px 0' }} />
        <Box mb={3}>
          <DateRangeSelector />
        </Box>
        {selectedMetrics.length > 0 && (
          <Alert severity="info" style={{ marginTop: 16 }}>
            Selected {selectedMetrics.length} metric{selectedMetrics.length !== 1 ? 's' : ''}
          </Alert>
        )}
      </DialogContent>
      <DialogActions>
        <Button onClick={() => setBuilderOpen(false)}>Cancel</Button>
        <Button
          onClick={() => setScheduleOpen(true)}
          startIcon={<Schedule />}
          disabled={selectedMetrics.length === 0}
        >
          Schedule
        </Button>
        <Button
          onClick={handleBuildReport}
          variant="contained"
          color="primary"
          disabled={loading || selectedMetrics.length === 0}
          startIcon={loading ? <CircularProgress size={20} /> : <Assessment />}
        >
          Build Report
        </Button>
      </DialogActions>
    </Dialog>
  );

  const ScheduleDialog = () => (
    <Dialog open={scheduleOpen} onClose={() => setScheduleOpen(false)} maxWidth="sm" fullWidth>
      <DialogTitle>Schedule Report</DialogTitle>
      <DialogContent>
        <Box display="flex" flexDirection="column" gap={2} mt={2}>
          <FormControl fullWidth>
            <InputLabel>Frequency</InputLabel>
            <Select
              value={scheduleConfig.frequency}
              onChange={(e) => setScheduleConfig(prev => ({ ...prev, frequency: e.target.value }))}
              label="Frequency"
            >
              <MenuItem value="daily">Daily</MenuItem>
              <MenuItem value="weekly">Weekly</MenuItem>
              <MenuItem value="monthly">Monthly</MenuItem>
              <MenuItem value="quarterly">Quarterly</MenuItem>
            </Select>
          </FormControl>

          <TextField
            fullWidth
            label="Recipients (comma-separated emails)"
            placeholder="john@example.com, jane@example.com"
            value={scheduleConfig.recipients}
            onChange={(e) => setScheduleConfig(prev => ({ ...prev, recipients: e.target.value }))}
          />

          <FormControl fullWidth>
            <InputLabel>Format</InputLabel>
            <Select
              value={scheduleConfig.format}
              onChange={(e) => setScheduleConfig(prev => ({ ...prev, format: e.target.value }))}
              label="Format"
            >
              <MenuItem value="pdf">PDF</MenuItem>
              <MenuItem value="excel">Excel</MenuItem>
              <MenuItem value="csv">CSV</MenuItem>
            </Select>
          </FormControl>
        </Box>
      </DialogContent>
      <DialogActions>
        <Button onClick={() => setScheduleOpen(false)}>Cancel</Button>
        <Button onClick={handleScheduleReport} variant="contained" color="primary">
          Schedule Report
        </Button>
      </DialogActions>
    </Dialog>
  );

  return (
    <Container maxWidth="xl" style={{ marginTop: 20, marginBottom: 40 }}>
      <Box display="flex" justifyContent="space-between" alignItems="center" mb={3}>
        <Box>
          <Typography variant="h4" gutterBottom>
            Analytics Reports
          </Typography>
          <Typography variant="body2" color="textSecondary">
            Build custom reports, schedule delivery, and export data
          </Typography>
        </Box>
        <Button
          variant="contained"
          color="primary"
          startIcon={<Add />}
          onClick={() => setBuilderOpen(false)}
        >
          New Report
        </Button>
      </Box>

      <Tabs value={tabValue} onChange={(e, v) => setTabValue(v)} style={{ marginBottom: 24 }}>
        <Tab label="All Reports" />
        <Tab label="Scheduled Reports" />
        <Tab label="Report Builder" />
      </Tabs>

      {/* All Reports Tab */}
      {tabValue === 0 && (
        <Grid container spacing={3}>
          {reports.map((report) => (
            <Grid item xs={12} md={6} lg={4} key={report.report_id}>
              <Card elevation={3}>
                <CardContent>
                  <Typography variant="h6" gutterBottom>
                    {report.title}
                  </Typography>
                  <Typography variant="body2" color="textSecondary" gutterBottom>
                    Generated: {new Date(report.generated_at).toLocaleDateString()}
                  </Typography>
                  <Box mt={2}>
                    <Typography variant="caption" color="textSecondary">
                      Metrics: {report.metrics.length}
                    </Typography>
                  </Box>
                  <Box mt={1} display="flex" flexWrap="wrap" gap={0.5}>
                    {report.metrics.slice(0, 3).map(metric => (
                      <Chip key={metric} label={metric} size="small" />
                    ))}
                    {report.metrics.length > 3 && (
                      <Chip label={`+${report.metrics.length - 3}`} size="small" />
                    )}
                  </Box>
                </CardContent>
                <CardActions>
                  <IconButton
                    size="small"
                    onClick={() => handleExportReport(report.report_id, 'pdf')}
                    title="Export PDF"
                  >
                    <PictureAsPdf />
                  </IconButton>
                  <IconButton
                    size="small"
                    onClick={() => handleExportReport(report.report_id, 'excel')}
                    title="Export Excel"
                  >
                    <TableChart />
                  </IconButton>
                  <IconButton
                    size="small"
                    onClick={() => handleExportReport(report.report_id, 'csv')}
                    title="Export CSV"
                  >
                    <Download />
                  </IconButton>
                </CardActions>
              </Card>
            </Grid>
          ))}
        </Grid>
      )}

      {/* Scheduled Reports Tab */}
      {tabValue === 1 && (
        <TableContainer component={Paper} elevation={3}>
          <Table>
            <TableHead>
              <TableRow>
                <TableCell>Report Name</TableCell>
                <TableCell>Frequency</TableCell>
                <TableCell>Recipients</TableCell>
                <TableCell>Format</TableCell>
                <TableCell>Next Run</TableCell>
                <TableCell>Actions</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {scheduledReports.map((scheduled) => (
                <TableRow key={scheduled.job_id}>
                  <TableCell>{scheduled.report_config.title || 'Custom Report'}</TableCell>
                  <TableCell>
                    <Chip label={scheduled.frequency} size="small" color="primary" />
                  </TableCell>
                  <TableCell>{scheduled.recipients.join(', ')}</TableCell>
                  <TableCell>{scheduled.format.toUpperCase()}</TableCell>
                  <TableCell>
                    {new Date(scheduled.next_run_time).toLocaleString()}
                  </TableCell>
                  <TableCell>
                    <IconButton
                      size="small"
                      onClick={() => handleCancelScheduledReport(scheduled.job_id)}
                      color="error"
                    >
                      <Delete />
                    </IconButton>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </TableContainer>
      )}

      {/* Report Builder Tab */}
      {tabValue === 2 && (
        <Paper elevation={3} style={{ padding: 30 }}>
          <Box textAlign="center" py={5}>
            <Assessment style={{ fontSize: 80, color: '#ccc', marginBottom: 16 }} />
            <Typography variant="h5" gutterBottom>
              Custom Report Builder
            </Typography>
            <Typography variant="body1" color="textSecondary" paragraph>
              Create custom reports with drag-and-drop metrics, flexible filters, and scheduling
            </Typography>
            <Button
              variant="contained"
              color="primary"
              size="large"
              startIcon={<Add />}
              onClick={() => setBuilderOpen(true)}
            >
              Build New Report
            </Button>
          </Box>
        </Paper>
      )}

      {/* Dialogs */}
      <ReportBuilderDialog />
      <ScheduleDialog />
    </Container>
  );
};

export default Reports;
