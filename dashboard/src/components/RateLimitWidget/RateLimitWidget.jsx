import React, { useEffect, useState } from 'react';
import { ArgosAPI } from '../../api/argos';
import styles from './RateLimitWidget.module.css';

export default function RateLimitWidget() {
  const [limits, setLimits] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    const fetchLimits = async () => {
      try {
        const data = await ArgosAPI.getRateLimits();
        setLimits(data);
        setError(null);
      } catch (e) {
        setError(e.message);
      }
    };
    
    fetchLimits();
    const interval = setInterval(fetchLimits, 15000); // Polling every 15s is fine for windows
    return () => clearInterval(interval);
  }, []);

  const calculatePercentage = (used, max) => {
    if (!max) return 0;
    return Math.min((used / max) * 100, 100);
  };

  return (
    <div className={`glass-panel ${styles.widget}`}>
      <div className={styles.header}>
        <h3>// RATE LIMITS</h3>
      </div>
      
      <div className={styles.content}>
        {error ? (
          <div className={styles.errorBox}>Fail: {error}</div>
        ) : !limits ? (
          <div className={styles.loading}>Tracking...</div>
        ) : (
           <div className={styles.stats}>
             <div className={styles.statBlock}>
               <div className={styles.statLabel}>MINUTE QUOTA</div>
               <div className={styles.barBg}>
                 <div 
                   className={styles.barFill} 
                   style={{ 
                     width: `${calculatePercentage(limits.minute.used, limits.minute.max)}%`,
                     background: limits.minute.used >= limits.minute.max ? '#ff4a4a' : 'var(--cyan-glow)'
                   }}
                 ></div>
               </div>
               <div className={styles.statValues}>
                 {limits.minute.used} / {limits.minute.max}
               </div>
             </div>

             <div className={styles.statBlock}>
               <div className={styles.statLabel}>HOUR QUOTA</div>
               <div className={styles.barBg}>
                 <div 
                   className={styles.barFill} 
                   style={{ 
                     width: `${calculatePercentage(limits.hour.used, limits.hour.max)}%`,
                     background: limits.hour.used >= limits.hour.max ? '#ff4a4a' : 'var(--purple-glow)'
                   }}
                 ></div>
               </div>
               <div className={styles.statValues}>
                 {limits.hour.used} / {limits.hour.max}
               </div>
             </div>
           </div>
        )}
      </div>
    </div>
  );
}
