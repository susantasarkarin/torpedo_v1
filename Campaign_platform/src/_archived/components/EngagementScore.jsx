/**
 * EngagementScore Component
 * Circular progress indicator with color coding and trend indicator
 */
import React from 'react';
import { TrendingUp, TrendingDown, Minus } from 'lucide-react';
import './EngagementScore.css';

export default function EngagementScore({ score = 0, breakdown = {}, trend = 'stable' }) {
  const getColor = (score) => {
    if (score < 33) return '#ef4444'; // red
    if (score < 67) return '#eab308'; // yellow
    return '#22c55e'; // green
  };

  const getLabel = (score) => {
    if (score < 33) return 'Low';
    if (score < 67) return 'Medium';
    return 'High';
  };

  const circleRadius = 45;
  const circumference = 2 * Math.PI * circleRadius;
  const strokeDashoffset = circumference - (score / 100) * circumference;
  const color = getColor(score);

  const opens = breakdown.opens || 40;
  const clicks = breakdown.clicks || 20;
  const replies = breakdown.replies || 40;

  const getTrendIcon = () => {
    if (trend === 'up') return <TrendingUp size={16} className="trend-up" />;
    if (trend === 'down') return <TrendingDown size={16} className="trend-down" />;
    return <Minus size={16} className="trend-stable" />;
  };

  return (
    <div className="engagement-score">
      <div className="score-circle-container">
        <svg width="120" height="120" className="score-circle">
          <circle
            cx="60"
            cy="60"
            r={circleRadius}
            className="circle-background"
          />
          <circle
            cx="60"
            cy="60"
            r={circleRadius}
            className="circle-progress"
            style={{
              stroke: color,
              strokeDashoffset: strokeDashoffset,
              strokeDasharray: circumference,
            }}
          />
        </svg>
        <div className="score-text">
          <div className="score-number">{score}</div>
          <div className="score-label">{getLabel(score)}</div>
        </div>
      </div>

      <div className="score-details">
        <div className="score-metric">
          <span className="metric-label">Opens</span>
          <span className="metric-value">{opens}%</span>
        </div>
        <div className="score-metric">
          <span className="metric-label">Clicks</span>
          <span className="metric-value">{clicks}%</span>
        </div>
        <div className="score-metric">
          <span className="metric-label">Replies</span>
          <span className="metric-value">{replies}%</span>
        </div>
      </div>

      <div className="score-trend">
        {getTrendIcon()}
        <span className="trend-label">
          {trend === 'up' && 'Improving'}
          {trend === 'down' && 'Declining'}
          {trend === 'stable' && 'Stable'}
        </span>
      </div>
    </div>
  );
}
