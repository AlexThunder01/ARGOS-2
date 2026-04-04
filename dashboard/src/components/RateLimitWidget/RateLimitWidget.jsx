import React, { useEffect, useState } from 'react';
import { ArgosAPI } from '../../api/argos';
import styles from './RateLimitWidget.module.css';

export default function RateLimitWidget() {
  const [rates, setRates] = useState(null);
  const [latency, setLatency] = useState({ ping: '-', db_query: '-', memory_recall: '-', n8n_trigger: '-' });
  const [security, setSecurity] = useState({ paranoid_judge: true, blocked_today: 0, risk_score_avg: 0.0 });
  const [error, setError] = useState(null);

  useEffect(() => {
    const fetchRates = async () => {
      try {
        const [data, latData, secData] = await Promise.all([
          ArgosAPI.getRateLimits(),
          ArgosAPI.getLatencyStats(),
          ArgosAPI.getSecurityStats()
        ]);
        setRates(data);
        setLatency(latData);
        setSecurity(secData);
        setError(null);
      } catch (e) {
        setError(e.message);
      }
    };
    
    fetchRates();
    const interval = setInterval(fetchRates, 15000);
    return () => clearInterval(interval);
  }, []);

  const hrUsed = rates?.hour?.used || 0;
  const hrMax = rates?.hour?.max || 50;
  const hrPercent = Math.min((hrUsed / hrMax) * 100, 100);
  
  const minUsed = rates?.minute?.used || 0;
  const minMax = rates?.minute?.max || 5;
  const minPercent = Math.min((minUsed / minMax) * 100, 100);

  // SVG dash configuration
  const circleRadius = 36;
  const circumference = 2 * Math.PI * circleRadius;
  const dashOffset = circumference - (hrPercent / 100) * circumference;

  return (
    <div className={styles.rightPanel}>
      <div>
        <div className={styles.sectionLabel}>Rate Limit</div>
        {error ? (
          <div style={{color: 'red', fontSize: '9px'}}>{error}</div>
        ) : !rates ? (
           <div style={{color: 'gray', fontSize: '10px'}}>Loading...</div>
        ) : (
          <div className={styles.donutWrap}>
            <svg width="90" height="90" viewBox="0 0 90 90">
              <circle cx="45" cy="45" r={circleRadius} fill="none" stroke="rgba(255,255,255,0.06)" strokeWidth="8"/>
              <circle 
                cx="45" 
                cy="45" 
                r={circleRadius} 
                fill="none" 
                stroke={hrPercent > 90 ? "var(--danger)" : hrPercent > 75 ? "var(--warning)" : "var(--cyan)"} 
                strokeWidth="8"
                strokeDasharray={circumference} 
                strokeDashoffset={dashOffset} 
                strokeLinecap="round"
                transform="rotate(-90 45 45)"
                style={{ transition: 'stroke-dashoffset 0.5s ease-in-out' }}
              />
              <text x="45" y="49" textAnchor="middle" fill="var(--cyan)" fontSize="16" fontFamily="var(--mono)" fontWeight="600">
                {Math.round(hrPercent)}%
              </text>
            </svg>
            <div className={styles.donutLabels}>
              <div className={styles.donutVal} style={{fontSize: '13px'}}>{hrUsed} / {hrMax}</div>
              <div className={styles.donutSub}>msg this hour</div>
            </div>
          </div>
        )}
      </div>
      
      <div>
        <div className={styles.sectionLabel}>Per-minute</div>
        <div className={styles.miniBarWrap}>
          <div className={styles.miniBarLabel}>
            {minUsed} / {minMax} 
            <span style={{color: minPercent > 80 ? 'var(--danger)' : minPercent > 50 ? 'var(--warning)' : 'var(--cyan)'}}>
              {Math.round(minPercent)}%
            </span>
          </div>
          <div className={styles.miniBarTrack}>
            <div 
              className={styles.miniBarFill} 
              style={{
                width: `${minPercent}%`, 
                background: minPercent > 80 ? 'var(--danger)' : minPercent > 50 ? 'var(--warning)' : 'var(--cyan)'
              }}
            ></div>
          </div>
        </div>
      </div>
      
      <div>
        <div className={styles.sectionLabel}>Last Tasks</div>
        <div className={styles.statRow}><div className={styles.statLabel}>ping /status</div><div className={`${styles.statVal} ${styles.ok}`}>{latency.ping}</div></div>
        <div className={styles.statRow}><div className={styles.statLabel}>db query #1</div><div className={`${styles.statVal} ${styles.ok}`}>{latency.db_query}</div></div>
        <div className={styles.statRow}><div className={styles.statLabel}>memory recall</div><div className={`${styles.statVal} ${styles.ok}`}>{latency.memory_recall}</div></div>
        <div className={styles.statRow}><div className={styles.statLabel}>n8n trigger</div><div className={`${styles.statVal} ${styles.warn}`}>{latency.n8n_trigger}</div></div>
      </div>
      
      <div>
        <div className={styles.sectionLabel}>Security</div>
        <div className={styles.statRow}><div className={styles.statLabel}>Paranoid Judge</div><div className={styles.statVal} style={{color: 'var(--purple)'}}>{security.paranoid_judge ? 'ON' : 'OFF'}</div></div>
        <div className={styles.statRow}><div className={styles.statLabel}>Blocked today</div><div className={`${styles.statVal} ${styles.err}`}>{security.blocked_today}</div></div>
        <div className={styles.statRow}><div className={styles.statLabel}>Risk score avg</div><div className={`${styles.statVal} ${styles.ok}`}>{security.risk_score_avg}</div></div>
      </div>
    </div>
  );
}
