/**
 * OutreachHistory Component
 * Timeline visualization of all outreach attempts
 */
import React, { useState } from 'react';
import { Mail, Linkedin, CheckCircle, Clock, AlertCircle, Eye, Click } from 'lucide-react';
import './OutreachHistory.css';

const CHANNEL_ICONS = {
  email: Mail,
  linkedin: Linkedin,
  sms: AlertCircle,
  call: Clock,
};

const STATUS_CONFIG = {
  sent: { label: 'Sent', color: '#3b82f6', icon: Clock },
  opened: { label: 'Opened', color: '#8b5cf6', icon: Eye },
  clicked: { label: 'Clicked', color: '#ec4899', icon: Click },
  replied: { label: 'Replied', color: '#22c55e', icon: CheckCircle },
  bounced: { label: 'Bounced', color: '#ef4444', icon: AlertCircle },
  failed: { label: 'Failed', color: '#f97316', icon: AlertCircle },
};

export default function OutreachHistory({ history = [] }) {
  const [expandedId, setExpandedId] = useState(null);

  const formatDate = (dateString) => {
    if (!dateString) return '-';
    const date = new Date(dateString);
    return date.toLocaleDateString('en-US', {
      month: 'short',
      day: 'numeric',
      year: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    });
  };

  const getChannelIcon = (channel) => {
    const IconComponent = CHANNEL_ICONS[channel] || Mail;
    return <IconComponent size={16} />;
  };

  const getStatusConfig = (status) => {
    return STATUS_CONFIG[status] || STATUS_CONFIG.sent;
  };

  if (!history || history.length === 0) {
    return (
      <div className="outreach-history">
        <div className="empty-state">
          <Mail size={24} />
          <p>No outreach history yet</p>
        </div>
      </div>
    );
  }

  return (
    <div className="outreach-history">
      <div className="timeline">
        {history.map((item, index) => {
          const isExpanded = expandedId === item.id;
          const statusConfig = getStatusConfig(item.status);
          const StatusIcon = statusConfig.icon;

          return (
            <div key={item.id || index} className="timeline-item">
              <div className="timeline-marker" style={{ color: statusConfig.color }}>
                <StatusIcon size={14} />
              </div>

              <div className="timeline-content">
                <div
                  className="timeline-header"
                  onClick={() => setExpandedId(isExpanded ? null : item.id || index)}
                >
                  <div className="timeline-title">
                    <span className="channel-badge">
                      {getChannelIcon(item.channel)}
                      <span className="channel-text">
                        {item.channel?.charAt(0).toUpperCase() + item.channel?.slice(1) || 'Email'}
                      </span>
                    </span>
                    <span
                      className="status-badge"
                      style={{ backgroundColor: `${statusConfig.color}20`, color: statusConfig.color }}
                    >
                      {statusConfig.label}
                    </span>
                  </div>

                  <div className="timeline-date">
                    {formatDate(item.date || item.timestamp || item.created_at)}
                  </div>
                </div>

                {item.subject && (
                  <div className="timeline-subject">
                    <strong>Subject:</strong> {item.subject}
                  </div>
                )}

                {item.preview && (
                  <div className="timeline-preview">
                    {item.preview.length > 150 ? (
                      <>
                        {isExpanded ? item.preview : `${item.preview.substring(0, 150)}...`}
                        {!isExpanded && (
                          <button className="expand-btn">Show more</button>
                        )}
                      </>
                    ) : (
                      item.preview
                    )}
                  </div>
                )}

                {isExpanded && item.content && (
                  <div className="timeline-full-content">
                    {item.content}
                  </div>
                )}

                {item.metrics && (
                  <div className="timeline-metrics">
                    {item.metrics.open_time && (
                      <div className="metric">
                        <Eye size={12} />
                        <span>Opened: {formatDate(item.metrics.open_time)}</span>
                      </div>
                    )}
                    {item.metrics.click_time && (
                      <div className="metric">
                        <Click size={12} />
                        <span>Clicked: {formatDate(item.metrics.click_time)}</span>
                      </div>
                    )}
                    {item.metrics.reply_time && (
                      <div className="metric">
                        <CheckCircle size={12} />
                        <span>Replied: {formatDate(item.metrics.reply_time)}</span>
                      </div>
                    )}
                  </div>
                )}

                {item.error && (
                  <div className="timeline-error">
                    <AlertCircle size={12} />
                    <span>{item.error}</span>
                  </div>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
