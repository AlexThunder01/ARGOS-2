import React, { useEffect, useState } from 'react';
import { ArgosAPI } from '../../api/argos';
import styles from './CommandMonitor.module.css';

export default function CommandMonitor() {
  const [stats, setStats] = useState({});
  const [sysStats, setSysStats] = useState({ cpu: 0, ram: 0, db_pool: '-', isolation: '-', exec_last_run: '-' });
  const [error, setError] = useState(null);

  useEffect(() => {
    const fetchStats = async () => {
      try {
        const data = await ArgosAPI.getDockerStats();
        setStats(data.containers || {});
        
        const sys = await ArgosAPI.getSystemStats();
        setSysStats(sys);
        setError(null);
      } catch (e) {
        setError(e.message);
      }
    };
    
    fetchStats();
    const interval = setInterval(fetchStats, 10000);
    return () => clearInterval(interval);
  }, []);

  const getContainerStatusClass = (health, state) => {
    if (state !== 'running') return styles.down;
    if (health === 'healthy') return styles.up;
    if (health === 'unhealthy') return styles.down;
    if (health === 'starting') return styles.warn;
    return styles.up; // default to UP if running and health is n/a
  };

  const getContainerStatusText = (health, state) => {
    if (state !== 'running') return 'DOWN';
    if (health === 'healthy') return 'UP';
    if (health === 'unhealthy') return 'ERR';
    if (health === 'starting') return 'INIT';
    return 'UP';
  };

  const getDotClass = (health, state) => {
    if (state !== 'running') return styles.svcDotDown;
    if (health === 'healthy') return styles.svcDotUp;
    if (health === 'unhealthy') return styles.svcDotDown;
    if (health === 'starting') return styles.svcDotWarn;
    return styles.svcDotUp;
  };

  return (
    <div className={styles.sidebar}>
      <div>
        <div className={styles.sectionLabel}>Services</div>
        {error && <div style={{color: 'red', fontSize: '9px'}}>{error}</div>}
        {Object.entries(stats).map(([name, info]) => {
           // Simplify names for display
           const shortName = name.replace('argos-', '');
           return (
            <div key={name} className={styles.serviceRow}>
              <div className={`${styles.svcDot} ${getDotClass(info.health, info.state)}`}></div>
              <div className={styles.svcName}>{shortName}</div>
              <div className={`${styles.svcBadge} ${getContainerStatusClass(info.health, info.state)}`}>
                {getContainerStatusText(info.health, info.state)}
              </div>
            </div>
           );
        })}
        {Object.keys(stats).length === 0 && !error && (
          <div style={{color: 'gray', fontSize: '10px'}}>Scanning...</div>
        )}
      </div>

      <div>
        <div className={styles.sectionLabel}>Resources</div>
        <div className={styles.miniBarWrap}>
          <div className={styles.miniBarLabel}>CPU <span>{sysStats.cpu.toFixed(1)}%</span></div>
          <div className={styles.miniBarTrack}>
            <div className={styles.miniBarFill} style={{width: `${sysStats.cpu}%`, background: 'var(--cyan)'}}></div>
          </div>
        </div>
        <div className={styles.miniBarWrap}>
          <div className={styles.miniBarLabel}>RAM <span>{sysStats.ram.toFixed(1)}%</span></div>
          <div className={styles.miniBarTrack}>
            <div className={styles.miniBarFill} style={{width: `${sysStats.ram}%`, background: 'var(--purple)'}}></div>
          </div>
        </div>
        <div className={styles.miniBarWrap}>
          <div className={styles.miniBarLabel}>DB Pool <span>{sysStats.db_pool}</span></div>
          <div className={styles.miniBarTrack}>
            <div className={styles.miniBarFill} style={{width: '100%', background: sysStats.db_pool.includes('local') ? 'var(--cyan)' : 'var(--warning)'}}></div>
          </div>
        </div>
      </div>

      <div>
        <div className={styles.sectionLabel}>Sandbox</div>
        <div>
          <div className={styles.sandboxRow}>
            <span>Active containers</span><span>{Object.keys(stats).length}</span>
          </div>
          <div className={styles.sandboxRow}>
            <span>Exec last run</span><span className={styles.sandboxOk}>{sysStats.exec_last_run}</span>
          </div>
          <div className={styles.sandboxRow}>
            <span>Isolation</span><span className={styles.sandboxPurple}>{sysStats.isolation}</span>
          </div>
        </div>
      </div>
    </div>
  );
}
