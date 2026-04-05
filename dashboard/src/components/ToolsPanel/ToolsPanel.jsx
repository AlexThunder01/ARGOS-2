import React, { useEffect, useState } from 'react';
import { ArgosAPI } from '../../api/argos';
import styles from './ToolsPanel.module.css';

const CATEGORY_ORDER = ['web', 'finance', 'documents', 'code', 'system', 'filesystem', 'gui'];
const CATEGORY_LABELS = {
  web: 'Web & Data',
  finance: 'Finance',
  documents: 'Documents',
  code: 'Code Exec',
  system: 'System',
  filesystem: 'File System',
  gui: 'GUI Automation',
};

export default function ToolsPanel() {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    const fetchTools = async () => {
      try {
        const result = await ArgosAPI.getToolsStats();
        setData(result);
        setError(null);
      } catch (e) {
        setError(e.message);
      }
    };

    fetchTools();
    // Refresh every 60s (tools don't change often)
    const interval = setInterval(fetchTools, 60000);
    return () => clearInterval(interval);
  }, []);

  if (error) {
    return (
      <div className={styles.panel}>
        <div className={styles.title}>Tools Arsenal</div>
        <div style={{ color: 'var(--danger)', fontSize: '9px' }}>{error}</div>
      </div>
    );
  }

  if (!data) {
    return (
      <div className={styles.panel}>
        <div className={styles.title}>Tools Arsenal</div>
        <div className={styles.loading}>
          <div className={styles.spinner}></div>
          Loading tools...
        </div>
      </div>
    );
  }

  // Group tools by category
  const grouped = {};
  data.tools.forEach(tool => {
    const cat = tool.category || 'other';
    if (!grouped[cat]) grouped[cat] = [];
    grouped[cat].push(tool);
  });

  // Sort categories in preferred order
  const sortedCategories = CATEGORY_ORDER.filter(c => grouped[c]);

  const enabledPercent = Math.round((data.dashboard_enabled / data.total) * 100);

  return (
    <div className={styles.panel}>
      {/* Header */}
      <div className={styles.header}>
        <div className={styles.title}>Tools Arsenal</div>
        <div className={styles.badge}>{data.total} tools</div>
      </div>

      {/* Summary */}
      <div className={styles.summary}>
        <div className={styles.summaryItem}>
          <span className={`${styles.summaryDot} ${styles.active}`}></span>
          <span className={styles.summaryCount}>{data.dashboard_enabled}</span>
          active
        </div>
        <div className={styles.summaryItem}>
          <span className={`${styles.summaryDot} ${styles.blocked}`}></span>
          <span className={styles.summaryCount}>{data.dashboard_blocked}</span>
          blocked
        </div>
      </div>

      {/* Progress bar */}
      <div className={styles.progressWrap}>
        <div
          className={styles.progressFill}
          style={{ width: `${enabledPercent}%` }}
        ></div>
      </div>

      {/* Tool grid by category */}
      {sortedCategories.map(cat => (
        <div key={cat} className={styles.categoryGroup}>
          <div className={styles.categoryLabel}>{CATEGORY_LABELS[cat] || cat}</div>
          <div className={styles.toolGrid}>
            {grouped[cat].map(tool => (
              <div
                key={tool.name}
                className={`${styles.toolChip} ${tool.dashboard_enabled ? styles.enabled : styles.blocked}`}
              >
                <span className={styles.toolIcon}>{tool.icon}</span>
                <span className={styles.toolName}>{tool.label}</span>
                <span className={`${styles.riskDot} ${styles[tool.risk]}`}></span>
                <div className={styles.tooltip}>
                  {tool.description}
                  {!tool.dashboard_enabled && ' • 🔒 Blocked on dashboard'}
                </div>
              </div>
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}
