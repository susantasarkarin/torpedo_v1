import React, { useState, useEffect } from 'react';
import {
  Container,
  Grid,
  Paper,
  Typography,
  Card,
  CardContent,
  Box,
  Select,
  MenuItem,
  FormControl,
  InputLabel,
  Button,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  LinearProgress,
  Chip,
  IconButton,
  Tooltip
} from '@mui/material';
import {
  TrendingUp,
  TrendingDown,
  Email,
  Visibility,
  Reply,
  EventAvailable,
  AttachMoney,
  Assessment,
  Refresh,
  Download,
  FilterList
} from '@mui/icons-material';
import {
  LineChart,
  Line,
  BarChart,
  Bar,
  PieChart,
  Pie,
  Cell,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip as RechartsTooltip,
  Legend,
  ResponsiveContainer
} from 'recharts';
import axios from 'axios';

const COLORS = ['#0088FE', '#00C49F', '#FFBB28', '#FF8042', '#8884D8', '#82CA9D'];

const ExecutiveDashboard = () => {
  const [timeRange, setTimeRange] = useState('30');
  const [loading, setLoading] = useState(true);
  const [dashboardData, setDashboardData] = useState(null);
  const [trendData, setTrendData] = useState([]);
  const [campaignLeaderboard, setCampaignLeaderboard] = useState([]);
  const [goalTracking, setGoalTracking] = useState({});

  useEffect(() => {
    loadDashboardData();
  }, [timeRange]);

  const loadDashboardData = async () => {
    setLoading(true);
    try {
      const response = await axios.get('/api/analytics/executive-dashboard', {
        params: { days: timeRange }
      });
      
      setDashboardData(response.data.kpis);
      setTrendData(response.data.trends);
      setCampaignLeaderboard(response.data.top_campaigns);
      setGoalTracking(response.data.goals);
    } catch (error) {
      console.error('Error loading dashboard:', error);
    } finally {
      setLoading(false);
    }
  };

  const handleExport = async (format) => {
    try {
      const response = await axios.get('/api/analytics/export-dashboard', {
        params: { format, days: timeRange },
        responseType: 'blob'
      });
      
      const url = window.URL.createObjectURL(new Blob([response.data]));
      const link = document.createElement('a');
      link.href = url;
      link.setAttribute('download', `executive-dashboard-${Date.now()}.${format}`);
      document.body.appendChild(link);
      link.click();
      link.remove();
    } catch (error) {
      console.error('Error exporting dashboard:', error);
    }
  };

  const KPICard = ({ title, value, change, icon, color, format = 'number' }) => {
    const isPositive = change >= 0;
    
    const formatValue = (val) => {
      if (format === 'currency') return `$${val.toLocaleString()}`;
      if (format === 'percent') return `${val.toFixed(2)}%`;
      return val.toLocaleString();
    };

    return (
      <Card elevation={3}>
        <CardContent>
          <Box display="flex" justifyContent="space-between" alignItems="flex-start">
            <Box>
              <Typography color="textSecondary" variant="body2" gutterBottom>
                {title}
              </Typography>
              <Typography variant="h4" component="div" style={{ color }}>
                {formatValue(value)}
              </Typography>
              <Box display="flex" alignItems="center" mt={1}>
                {isPositive ? (
                  <TrendingUp style={{ color: '#4CAF50', fontSize: 20 }} />
                ) : (
                  <TrendingDown style={{ color: '#F44336', fontSize: 20 }} />
                )}
                <Typography
                  variant="body2"
                  style={{ color: isPositive ? '#4CAF50' : '#F44336', marginLeft: 4 }}
                >
                  {Math.abs(change).toFixed(1)}% vs prev period
                </Typography>
              </Box>
            </Box>
            <Box
              style={{
                backgroundColor: `${color}20`,
                borderRadius: '50%',
                padding: 12,
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center'
              }}
            >
              {icon}
            </Box>
          </Box>
        </CardContent>
      </Card>
    );
  };

  const GoalTracker = ({ goal }) => {
    const progress = (goal.current / goal.target) * 100;
    const isOnTrack = progress >= (goal.expected_progress || 50);

    return (
      <Box mb={3}>
        <Box display="flex" justifyContent="space-between" mb={1}>
          <Typography variant="body1">{goal.name}</Typography>
          <Typography variant="body2" color="textSecondary">
            {goal.current.toLocaleString()} / {goal.target.toLocaleString()}
          </Typography>
        </Box>
        <LinearProgress
          variant="determinate"
          value={Math.min(progress, 100)}
          style={{
            height: 10,
            borderRadius: 5,
            backgroundColor: '#E0E0E0'
          }}
          sx={{
            '& .MuiLinearProgress-bar': {
              backgroundColor: isOnTrack ? '#4CAF50' : '#FF9800'
            }
          }}
        />
        <Box display="flex" justifyContent="space-between" mt={0.5}>
          <Typography variant="caption" color="textSecondary">
            {progress.toFixed(1)}% complete
          </Typography>
          <Chip
            label={isOnTrack ? 'On Track' : 'Behind'}
            size="small"
            color={isOnTrack ? 'success' : 'warning'}
            style={{ height: 20 }}
          />
        </Box>
      </Box>
    );
  };

  if (loading) {
    return (
      <Container maxWidth="xl" style={{ marginTop: 20 }}>
        <LinearProgress />
        <Typography align="center" style={{ marginTop: 20 }}>
          Loading dashboard...
        </Typography>
      </Container>
    );
  }

  return (
    <Container maxWidth="xl" style={{ marginTop: 20, marginBottom: 40 }}>
      {/* Header */}
      <Box display="flex" justifyContent="space-between" alignItems="center" mb={3}>
        <Box>
          <Typography variant="h4" gutterBottom>
            Executive Dashboard
          </Typography>
          <Typography variant="body2" color="textSecondary">
            Real-time performance metrics and insights
          </Typography>
        </Box>
        <Box display="flex" gap={2}>
          <FormControl variant="outlined" size="small" style={{ minWidth: 150 }}>
            <InputLabel>Time Range</InputLabel>
            <Select
              value={timeRange}
              onChange={(e) => setTimeRange(e.target.value)}
              label="Time Range"
            >
              <MenuItem value="7">Last 7 Days</MenuItem>
              <MenuItem value="30">Last 30 Days</MenuItem>
              <MenuItem value="90">Last 90 Days</MenuItem>
              <MenuItem value="365">Last Year</MenuItem>
            </Select>
          </FormControl>
          <IconButton onClick={loadDashboardData} color="primary">
            <Refresh />
          </IconButton>
          <Button
            variant="outlined"
            startIcon={<Download />}
            onClick={() => handleExport('pdf')}
          >
            Export PDF
          </Button>
          <Button
            variant="outlined"
            startIcon={<Download />}
            onClick={() => handleExport('excel')}
          >
            Export Excel
          </Button>
        </Box>
      </Box>

      {/* KPI Cards */}
      <Grid container spacing={3} mb={4}>
        <Grid item xs={12} sm={6} md={3}>
          <KPICard
            title="Total Leads"
            value={dashboardData?.total_leads || 0}
            change={dashboardData?.leads_change || 0}
            icon={<Email style={{ fontSize: 32, color: '#2196F3' }} />}
            color="#2196F3"
          />
        </Grid>
        <Grid item xs={12} sm={6} md={3}>
          <KPICard
            title="Open Rate"
            value={dashboardData?.open_rate || 0}
            change={dashboardData?.open_rate_change || 0}
            icon={<Visibility style={{ fontSize: 32, color: '#FF9800' }} />}
            color="#FF9800"
            format="percent"
          />
        </Grid>
        <Grid item xs={12} sm={6} md={3}>
          <KPICard
            title="Reply Rate"
            value={dashboardData?.reply_rate || 0}
            change={dashboardData?.reply_rate_change || 0}
            icon={<Reply style={{ fontSize: 32, color: '#4CAF50' }} />}
            color="#4CAF50"
            format="percent"
          />
        </Grid>
        <Grid item xs={12} sm={6} md={3}>
          <KPICard
            title="Meetings Booked"
            value={dashboardData?.meetings_booked || 0}
            change={dashboardData?.meetings_change || 0}
            icon={<EventAvailable style={{ fontSize: 32, color: '#9C27B0' }} />}
            color="#9C27B0"
          />
        </Grid>
      </Grid>

      <Grid container spacing={3} mb={4}>
        <Grid item xs={12} sm={6} md={3}>
          <KPICard
            title="Revenue Generated"
            value={dashboardData?.revenue || 0}
            change={dashboardData?.revenue_change || 0}
            icon={<AttachMoney style={{ fontSize: 32, color: '#00BCD4' }} />}
            color="#00BCD4"
            format="currency"
          />
        </Grid>
        <Grid item xs={12} sm={6} md={3}>
          <KPICard
            title="Conversion Rate"
            value={dashboardData?.conversion_rate || 0}
            change={dashboardData?.conversion_change || 0}
            icon={<Assessment style={{ fontSize: 32, color: '#E91E63' }} />}
            color="#E91E63"
            format="percent"
          />
        </Grid>
        <Grid item xs={12} sm={6} md={3}>
          <KPICard
            title="Pipeline Value"
            value={dashboardData?.pipeline_value || 0}
            change={dashboardData?.pipeline_change || 0}
            icon={<TrendingUp style={{ fontSize: 32, color: '#3F51B5' }} />}
            color="#3F51B5"
            format="currency"
          />
        </Grid>
        <Grid item xs={12} sm={6} md={3}>
          <KPICard
            title="Avg Deal Size"
            value={dashboardData?.avg_deal_size || 0}
            change={dashboardData?.deal_size_change || 0}
            icon={<AttachMoney style={{ fontSize: 32, color: '#009688' }} />}
            color="#009688"
            format="currency"
          />
        </Grid>
      </Grid>

      {/* Trend Charts */}
      <Grid container spacing={3} mb={4}>
        <Grid item xs={12} md={8}>
          <Paper elevation={3} style={{ padding: 20 }}>
            <Typography variant="h6" gutterBottom>
              Performance Trends
            </Typography>
            <ResponsiveContainer width="100%" height={300}>
              <LineChart data={trendData}>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis dataKey="date" />
                <YAxis yAxisId="left" />
                <YAxis yAxisId="right" orientation="right" />
                <RechartsTooltip />
                <Legend />
                <Line
                  yAxisId="left"
                  type="monotone"
                  dataKey="emails_sent"
                  stroke="#2196F3"
                  strokeWidth={2}
                  name="Emails Sent"
                />
                <Line
                  yAxisId="left"
                  type="monotone"
                  dataKey="opens"
                  stroke="#FF9800"
                  strokeWidth={2}
                  name="Opens"
                />
                <Line
                  yAxisId="left"
                  type="monotone"
                  dataKey="replies"
                  stroke="#4CAF50"
                  strokeWidth={2}
                  name="Replies"
                />
                <Line
                  yAxisId="right"
                  type="monotone"
                  dataKey="meetings"
                  stroke="#9C27B0"
                  strokeWidth={2}
                  name="Meetings"
                />
              </LineChart>
            </ResponsiveContainer>
          </Paper>
        </Grid>

        <Grid item xs={12} md={4}>
          <Paper elevation={3} style={{ padding: 20 }}>
            <Typography variant="h6" gutterBottom>
              Campaign Distribution
            </Typography>
            <ResponsiveContainer width="100%" height={300}>
              <PieChart>
                <Pie
                  data={dashboardData?.campaign_distribution || []}
                  cx="50%"
                  cy="50%"
                  labelLine={false}
                  label={(entry) => entry.name}
                  outerRadius={80}
                  fill="#8884d8"
                  dataKey="value"
                >
                  {(dashboardData?.campaign_distribution || []).map((entry, index) => (
                    <Cell key={`cell-${index}`} fill={COLORS[index % COLORS.length]} />
                  ))}
                </Pie>
                <RechartsTooltip />
              </PieChart>
            </ResponsiveContainer>
          </Paper>
        </Grid>
      </Grid>

      {/* Campaign Leaderboard and Goal Tracking */}
      <Grid container spacing={3}>
        <Grid item xs={12} md={7}>
          <Paper elevation={3} style={{ padding: 20 }}>
            <Typography variant="h6" gutterBottom>
              Top Performing Campaigns
            </Typography>
            <TableContainer>
              <Table>
                <TableHead>
                  <TableRow>
                    <TableCell>Campaign</TableCell>
                    <TableCell align="right">Leads</TableCell>
                    <TableCell align="right">Open Rate</TableCell>
                    <TableCell align="right">Reply Rate</TableCell>
                    <TableCell align="right">Meetings</TableCell>
                    <TableCell align="right">Revenue</TableCell>
                  </TableRow>
                </TableHead>
                <TableBody>
                  {campaignLeaderboard.map((campaign, index) => (
                    <TableRow key={index} hover>
                      <TableCell>
                        <Box display="flex" alignItems="center">
                          <Chip
                            label={index + 1}
                            size="small"
                            color={index === 0 ? 'primary' : 'default'}
                            style={{ marginRight: 8 }}
                          />
                          {campaign.name}
                        </Box>
                      </TableCell>
                      <TableCell align="right">{campaign.leads?.toLocaleString()}</TableCell>
                      <TableCell align="right">
                        <span style={{ color: campaign.open_rate > 30 ? '#4CAF50' : '#666' }}>
                          {campaign.open_rate?.toFixed(1)}%
                        </span>
                      </TableCell>
                      <TableCell align="right">
                        <span style={{ color: campaign.reply_rate > 3 ? '#4CAF50' : '#666' }}>
                          {campaign.reply_rate?.toFixed(1)}%
                        </span>
                      </TableCell>
                      <TableCell align="right">{campaign.meetings}</TableCell>
                      <TableCell align="right">${campaign.revenue?.toLocaleString()}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </TableContainer>
          </Paper>
        </Grid>

        <Grid item xs={12} md={5}>
          <Paper elevation={3} style={{ padding: 20 }}>
            <Typography variant="h6" gutterBottom>
              Goal Tracking
            </Typography>
            <Box mt={3}>
              {Object.values(goalTracking).map((goal, index) => (
                <GoalTracker key={index} goal={goal} />
              ))}
            </Box>
            <Button
              fullWidth
              variant="outlined"
              startIcon={<Assessment />}
              style={{ marginTop: 16 }}
              href="/analytics/reports"
            >
              View Detailed Reports
            </Button>
          </Paper>
        </Grid>
      </Grid>
    </Container>
  );
};

export default ExecutiveDashboard;
