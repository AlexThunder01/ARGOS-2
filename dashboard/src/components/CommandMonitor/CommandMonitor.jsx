import React, { useEffect, useState } from 'react';
import { ArgosAPI } from '../../api/argos';
import styles from './CommandMonitor.module.css';

export default function CommandMonitor() {
  const [stats, setStats] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    // Polling docker status explicitly from FastAPI backend every 5 seconds
    const fetchStats = async () => {
      try {
        const data = await ArgosAPI.getDockerStats();
        setStats(data);
        setError(null);
      } catch (e) {
        setError(e.message);
      }
    };
    
    fetchStats();
    const interval = setInterval(fetchStats, 5000);
    return () => clearInterval(interval);
  }, []);

  return (
    <div className={`glass-panel ${styles.monitor}`}>
      <div className={styles.header}>
        <h3>// DOCKER / SANDBOX</h3>
        <span className={styles.tag}>Live</span>
      </div>
      
      <div className={styles.content}>
        {error ? (
          <div className={styles.errorBox}>
             Fail: {error}<br/>
             (Verifica che argos-docker-proxy sia in esecuzione e che la route esista)
          </div>
        ) : !stats ? (
          <div className={styles.loading}>Scanning socket...</div>
        ) : (
           <div className={styles.grid}>
             {Object.entries(stats.containers || {}).map(([name, info]) => (
               <div key={name} className={styles.card}>
                 <div className={styles.cardHeader}>
                    <span className={info.state === 'running' ? styles.statusUp : styles.statusDown}></span>
                    {name}
                 </div>
                 <div className={styles.metrics}>
                   <div>CPU: {info.cpu_usage || "0%"}</div>
                   <div>MEM: {info.mem_usage || "0MB"}</div>
                 </div>
               </div>
             ))}
           </div>
        )}
      </div>
    </div>
  );
}
