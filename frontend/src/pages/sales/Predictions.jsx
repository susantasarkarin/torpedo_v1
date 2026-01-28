import React, { useState, useEffect } from 'react';
import {
  Box,
  Card,
  CardContent,
  Typography,
  Grid,
  Chip,
  LinearProgress,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Paper,
  Tabs,
  Tab,
  Alert,
  IconButton,
  Tooltip,
  CircularProgress,
  Badge
} from '@mui/material';
import {
  TrendingUp,
  TrendingDown,
  Event,
  Info,
  Refresh,
  Star,
  Person,
  Business,
  Email
} from '@mui/icons-material';
import axios from 'axios';

const Predictions = () => {
  const [loading, setLoading] = useState(true);
  const [activeTab, setActiveTab] = useState(0);
  const [replyPredictions, setReplyPredictions] = useState([]);
  const [meetingPredictions, setMeetingPredictions] = useState([]);
  const [hotLeads, setHotLeads] = useState([]);
  const [modelInfo, setModelInfo] = useState(null);

  useEffect(() => {
    fetchPredictions();
  }, []);

  const fetchPredictions = async () => {
    setLoading(true);
    try {
      // Fetch reply predictions
      const replyRes = await axios.get('/api/predictions/reply-probability');
      setReplyPredictions(replyRes.data.predictions || []);
      setModelInfo(replyRes.data.model_info || null);

      // Fetch meeting predictions
      const meetingRes = await axios.get('/api/predictions/meeting-probability');
      setMeetingPredictions(meetingRes.data.predictions || []);

      // Fetch hot leads
      const hotRes = await axios.get('/api/predictions/hot-leads');
      setHotLeads(hotRes.data.leads || []);
    } catch (error) {
      console.error('Error fetching predictions:', error);
    }
    setLoading(false);
  };

  const getProbabilityColor = (probability) => {
    if (probability >= 0.7) return 'success';
    if (probability >= 0.4) return 'warning';
    return 'error';
  };

  const getConfidenceColor = (confidence) => {
    if (confidence === 'high') return 'success';
    if (confidence === 'medium') return 'warning';
    return 'error';
  };

  const formatProbability = (prob) => {
    return `${(prob * 100).toFixed(1)}%`;
  };

  const renderReplyPredictions = () => (
    <Box>
      <Grid container spacing={3} sx={{ mb: 3 }}>
        <Grid item xs={12} md={4}>
          <Card>
            <CardContent>
              <Typography variant="h6" gutterBottom>
                High Probability
              </Typography>
              <Typography variant="h3" color="success.main">
                {replyPredictions.filter(p => p.reply_probability >= 0.7).length}
              </Typography>
              <Typography variant="body2" color="text.secondary">
                Leads likely to reply (≥70%)
              </Typography>
            </CardContent>
          </Card>
        </Grid>

        <Grid item xs={12} md={4}>
          <Card>
            <CardContent>
              <Typography variant="h6" gutterBottom>
                Medium Probability
              </Typography>
              <Typography variant="h3" color="warning.main">
                {replyPredictions.filter(p => p.reply_probability >= 0.4 && p.reply_probability < 0.7).length}
              </Typography>
              <Typography variant="body2" color="text.secondary">
                Moderate reply likelihood (40-70%)
              </Typography>
            </CardContent>
          </Card>
        </Grid>

        <Grid item xs={12} md={4}>
          <Card>
            <CardContent>
              <Typography variant="h6" gutterBottom>
                Low Probability
              </Typography>
              <Typography variant="h3" color="error.main">
                {replyPredictions.filter(p => p.reply_probability < 0.4).length}
              </Typography>
              <Typography variant="body2" color="text.secondary">
                Lower reply likelihood (&lt;40%)
              </Typography>
            </CardContent>
          </Card>
        </Grid>
      </Grid>

      <Card>
        <CardContent>
          <Box display="flex" justifyContent="space-between" alignItems="center" mb={2}>
            <Typography variant="h6">
              Reply Probability by Lead
            </Typography>
            <Tooltip title="Refresh predictions">
              <IconButton onClick={fetchPredictions} size="small">
                <Refresh />
              </IconButton>
            </Tooltip>
          </Box>

          <TableContainer>
            <Table>
              <TableHead>
                <TableRow>
                  <TableCell>Lead</TableCell>
                  <TableCell>Company</TableCell>
                  <TableCell>Probability</TableCell>
                  <TableCell>Confidence</TableCell>
                  <TableCell>Top Factors</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {replyPredictions.slice(0, 20).map((pred) => (
                  <TableRow key={pred.lead_id} hover>
                    <TableCell>
                      <Box display="flex" alignItems="center">
                        <Person sx={{ mr: 1, fontSize: 20 }} />
                        <Box>
                          <Typography variant="body2" fontWeight="bold">
                            {pred.name}
                          </Typography>
                          <Typography variant="caption" color="text.secondary">
                            {pred.email}
                          </Typography>
                        </Box>
                      </Box>
                    </TableCell>
                    <TableCell>
                      <Box display="flex" alignItems="center">
                        <Business sx={{ mr: 1, fontSize: 18 }} />
                        {pred.company}
                      </Box>
                    </TableCell>
                    <TableCell>
                      <Box>
                        <LinearProgress
                          variant="determinate"
                          value={pred.reply_probability * 100}
                          color={getProbabilityColor(pred.reply_probability)}
                          sx={{ mb: 0.5, height: 8, borderRadius: 4 }}
                        />
                        <Typography variant="body2">
                          {formatProbability(pred.reply_probability)}
                        </Typography>
                      </Box>
                    </TableCell>
                    <TableCell>
                      <Chip
                        label={pred.confidence}
                        size="small"
                        color={getConfidenceColor(pred.confidence)}
                      />
                    </TableCell>
                    <TableCell>
                      <Box display="flex" flexWrap="wrap" gap={0.5}>
                        {pred.top_factors && Object.entries(pred.top_factors).slice(0, 3).map(([factor, importance]) => (
                          <Tooltip key={factor} title={`${factor}: ${(importance * 100).toFixed(0)}%`}>
                            <Chip
                              label={factor.replace(/_/g, ' ')}
                              size="small"
                              variant="outlined"
                            />
                          </Tooltip>
                        ))}
                      </Box>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </TableContainer>
        </CardContent>
      </Card>
    </Box>
  );

  const renderMeetingPredictions = () => (
    <Box>
      <Grid container spacing={3} sx={{ mb: 3 }}>
        <Grid item xs={12} md={3}>
          <Card>
            <CardContent>
              <Typography variant="h6" gutterBottom>
                Ready Now
              </Typography>
              <Typography variant="h3" color="success.main">
                {meetingPredictions.filter(p => p.readiness === 'ready_now').length}
              </Typography>
              <Typography variant="body2" color="text.secondary">
                Ask for meeting immediately
              </Typography>
            </CardContent>
          </Card>
        </Grid>

        <Grid item xs={12} md={3}>
          <Card>
            <CardContent>
              <Typography variant="h6" gutterBottom>
                Almost Ready
              </Typography>
              <Typography variant="h3" color="info.main">
                {meetingPredictions.filter(p => p.readiness === 'almost_ready').length}
              </Typography>
              <Typography variant="body2" color="text.secondary">
                1-2 more exchanges
              </Typography>
            </CardContent>
          </Card>
        </Grid>

        <Grid item xs={12} md={3}>
          <Card>
            <CardContent>
              <Typography variant="h6" gutterBottom>
                Warming Up
              </Typography>
              <Typography variant="h3" color="warning.main">
                {meetingPredictions.filter(p => p.readiness === 'warming_up').length}
              </Typography>
              <Typography variant="body2" color="text.secondary">
                Continue nurturing
              </Typography>
            </CardContent>
          </Card>
        </Grid>

        <Grid item xs={12} md={3}>
          <Card>
            <CardContent>
              <Typography variant="h6" gutterBottom>
                Not Ready
              </Typography>
              <Typography variant="h3" color="text.secondary">
                {meetingPredictions.filter(p => p.readiness === 'not_ready').length}
              </Typography>
              <Typography variant="body2" color="text.secondary">
                Build more value
              </Typography>
            </CardContent>
          </Card>
        </Grid>
      </Grid>

      <Card>
        <CardContent>
          <Typography variant="h6" gutterBottom>
            Meeting Booking Probability
          </Typography>

          <TableContainer>
            <Table>
              <TableHead>
                <TableRow>
                  <TableCell>Lead</TableCell>
                  <TableCell>Company</TableCell>
                  <TableCell>Probability</TableCell>
                  <TableCell>Readiness</TableCell>
                  <TableCell>Recommendation</TableCell>
                  <TableCell>Status</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {meetingPredictions.map((pred) => (
                  <TableRow key={pred.lead_id} hover>
                    <TableCell>
                      <Typography variant="body2" fontWeight="bold">
                        {pred.name}
                      </Typography>
                      <Typography variant="caption" color="text.secondary">
                        {pred.title}
                      </Typography>
                    </TableCell>
                    <TableCell>{pred.company}</TableCell>
                    <TableCell>
                      <Box>
                        <CircularProgress
                          variant="determinate"
                          value={pred.meeting_probability * 100}
                          size={40}
                          thickness={5}
                          color={getProbabilityColor(pred.meeting_probability)}
                        />
                        <Typography variant="caption" display="block" textAlign="center" mt={0.5}>
                          {formatProbability(pred.meeting_probability)}
                        </Typography>
                      </Box>
                    </TableCell>
                    <TableCell>
                      <Chip
                        label={pred.readiness.replace(/_/g, ' ')}
                        size="small"
                        color={
                          pred.readiness === 'ready_now' ? 'success' :
                          pred.readiness === 'almost_ready' ? 'info' :
                          pred.readiness === 'warming_up' ? 'warning' : 'default'
                        }
                      />
                    </TableCell>
                    <TableCell>
                      <Typography variant="body2">
                        {pred.recommendation}
                      </Typography>
                    </TableCell>
                    <TableCell>
                      {pred.already_asked ? (
                        <Chip label="Asked" size="small" variant="outlined" />
                      ) : (
                        <Chip label="Not asked" size="small" />
                      )}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </TableContainer>
        </CardContent>
      </Card>
    </Box>
  );

  const renderHotLeads = () => (
    <Box>
      <Alert severity="info" sx={{ mb: 3 }}>
        <Typography variant="body2">
          These leads have the highest probability of replying today. Prioritize outreach to these contacts.
        </Typography>
      </Alert>

      <Grid container spacing={2}>
        {hotLeads.map((lead) => (
          <Grid item xs={12} md={6} key={lead.lead_id}>
            <Card sx={{ border: '2px solid', borderColor: 'success.main' }}>
              <CardContent>
                <Box display="flex" justifyContent="space-between" alignItems="flex-start" mb={2}>
                  <Box>
                    <Typography variant="h6">
                      {lead.name}
                    </Typography>
                    <Typography variant="body2" color="text.secondary">
                      {lead.title} at {lead.company}
                    </Typography>
                  </Box>
                  <Badge badgeContent={<Star sx={{ fontSize: 16 }} />} color="warning">
                    <Chip
                      label={`${formatProbability(lead.priority_score)}`}
                      color="success"
                      size="small"
                    />
                  </Badge>
                </Box>

                <Grid container spacing={2}>
                  <Grid item xs={4}>
                    <Box textAlign="center">
                      <Email color="action" />
                      <Typography variant="h6">{lead.email_opens || 0}</Typography>
                      <Typography variant="caption" color="text.secondary">Opens</Typography>
                    </Box>
                  </Grid>
                  <Grid item xs={4}>
                    <Box textAlign="center">
                      <TrendingUp color="action" />
                      <Typography variant="h6">{lead.email_clicks || 0}</Typography>
                      <Typography variant="caption" color="text.secondary">Clicks</Typography>
                    </Box>
                  </Grid>
                  <Grid item xs={4}>
                    <Box textAlign="center">
                      <Event color="action" />
                      <Typography variant="h6">{lead.previous_replies || 0}</Typography>
                      <Typography variant="caption" color="text.secondary">Replies</Typography>
                    </Box>
                  </Grid>
                </Grid>

                <Box mt={2}>
                  <Typography variant="body2" fontWeight="bold" gutterBottom>
                    Recommended Action:
                  </Typography>
                  <Typography variant="body2" color="text.secondary">
                    {lead.recommended_action}
                  </Typography>
                </Box>

                {lead.last_activity && (
                  <Typography variant="caption" color="text.secondary" display="block" mt={1}>
                    Last activity: {new Date(lead.last_activity).toLocaleDateString()}
                  </Typography>
                )}
              </CardContent>
            </Card>
          </Grid>
        ))}
      </Grid>

      {hotLeads.length === 0 && (
        <Box textAlign="center" py={5}>
          <Typography variant="body1" color="text.secondary">
            No hot leads at the moment. Keep engaging with your prospects!
          </Typography>
        </Box>
      )}
    </Box>
  );

  const renderModelInfo = () => (
    <Box>
      <Card>
        <CardContent>
          <Typography variant="h6" gutterBottom>
            Prediction Model Information
          </Typography>

          {modelInfo ? (
            <Grid container spacing={2}>
              <Grid item xs={12} md={6}>
                <Typography variant="body2" color="text.secondary" gutterBottom>
                  Model Status
                </Typography>
                <Chip
                  label={modelInfo.status === 'trained' ? 'Active' : 'Training'}
                  color={modelInfo.status === 'trained' ? 'success' : 'warning'}
                />
              </Grid>

              <Grid item xs={12} md={6}>
                <Typography variant="body2" color="text.secondary" gutterBottom>
                  Training Accuracy
                </Typography>
                <Typography variant="h6">
                  {modelInfo.train_accuracy ? `${(modelInfo.train_accuracy * 100).toFixed(1)}%` : 'N/A'}
                </Typography>
              </Grid>

              <Grid item xs={12} md={6}>
                <Typography variant="body2" color="text.secondary" gutterBottom>
                  Number of Features
                </Typography>
                <Typography variant="h6">{modelInfo.n_features || 'N/A'}</Typography>
              </Grid>

              <Grid item xs={12} md={6}>
                <Typography variant="body2" color="text.secondary" gutterBottom>
                  Training Samples
                </Typography>
                <Typography variant="h6">{modelInfo.n_samples || 'N/A'}</Typography>
              </Grid>

              {modelInfo.categorical_features && (
                <Grid item xs={12}>
                  <Typography variant="body2" color="text.secondary" gutterBottom>
                    Categorical Features
                  </Typography>
                  <Box display="flex" flexWrap="wrap" gap={1}>
                    {modelInfo.categorical_features.map((feature) => (
                      <Chip key={feature} label={feature} size="small" variant="outlined" />
                    ))}
                  </Box>
                </Grid>
              )}

              {modelInfo.numerical_features && (
                <Grid item xs={12}>
                  <Typography variant="body2" color="text.secondary" gutterBottom>
                    Numerical Features
                  </Typography>
                  <Box display="flex" flexWrap="wrap" gap={1}>
                    {modelInfo.numerical_features.map((feature) => (
                      <Chip key={feature} label={feature} size="small" variant="outlined" />
                    ))}
                  </Box>
                </Grid>
              )}
            </Grid>
          ) : (
            <Alert severity="info">
              Model information not available. The prediction model may be training or not yet initialized.
            </Alert>
          )}
        </CardContent>
      </Card>

      <Card sx={{ mt: 2 }}>
        <CardContent>
          <Typography variant="h6" gutterBottom>
            How Predictions Work
          </Typography>
          
          <Typography variant="body2" paragraph>
            Our AI-powered prediction system uses machine learning to analyze historical engagement data
            and predict the likelihood of leads replying to emails or booking meetings.
          </Typography>

          <Typography variant="body2" fontWeight="bold" gutterBottom>
            Key Factors Analyzed:
          </Typography>
          <ul>
            <li><Typography variant="body2">Email engagement (opens, clicks)</Typography></li>
            <li><Typography variant="body2">Previous reply history</Typography></li>
            <li><Typography variant="body2">Company profile and industry</Typography></li>
            <li><Typography variant="body2">Contact seniority and role</Typography></li>
            <li><Typography variant="body2">Timing and recency of interactions</Typography></li>
            <li><Typography variant="body2">Content personalization level</Typography></li>
          </ul>

          <Alert severity="success" sx={{ mt: 2 }}>
            <Typography variant="body2">
              The model continuously learns from your campaigns and improves its accuracy over time.
            </Typography>
          </Alert>
        </CardContent>
      </Card>
    </Box>
  );

  if (loading) {
    return (
      <Box display="flex" justifyContent="center" alignItems="center" minHeight="400px">
        <CircularProgress />
      </Box>
    );
  }

  return (
    <Box sx={{ p: 3 }}>
      <Box mb={3}>
        <Typography variant="h4" gutterBottom>
          AI Predictions
        </Typography>
        <Typography variant="body1" color="text.secondary">
          Machine learning-powered predictions for reply probability, meeting booking, and lead prioritization
        </Typography>
      </Box>

      <Tabs
        value={activeTab}
        onChange={(e, newValue) => setActiveTab(newValue)}
        sx={{ mb: 3 }}
      >
        <Tab label={`Hot Leads (${hotLeads.length})`} icon={<Star />} iconPosition="start" />
        <Tab label={`Reply Predictions (${replyPredictions.length})`} icon={<Email />} iconPosition="start" />
        <Tab label={`Meeting Predictions (${meetingPredictions.length})`} icon={<Event />} iconPosition="start" />
        <Tab label="Model Info" icon={<Info />} iconPosition="start" />
      </Tabs>

      {activeTab === 0 && renderHotLeads()}
      {activeTab === 1 && renderReplyPredictions()}
      {activeTab === 2 && renderMeetingPredictions()}
      {activeTab === 3 && renderModelInfo()}
    </Box>
  );
};

export default Predictions;
