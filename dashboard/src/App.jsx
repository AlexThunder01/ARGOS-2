import React, { useEffect, useState } from 'react';
import { useSSEChat } from './hooks/useSSEChat';
import ChatTerminal from './components/ChatTerminal/ChatTerminal';
import CommandMonitor from './components/CommandMonitor/CommandMonitor';
import RateLimitWidget from './components/RateLimitWidget/RateLimitWidget';
import { ArgosAPI } from './api/argos';
import styles from './App.module.css';

function App() {
  const { messages, isTyping, error, sendMessage } = useSSEChat();
  const [config, setConfig] = useState({ version: 'v2.2.0', model: 'Loading...' });

  useEffect(() => {
    ArgosAPI.getConfigStats().then(setConfig).catch(console.error);
  }, []);

  return (
    <div className={styles.shell}>
      <div className={styles.topbar}>
        <div className={styles.logo}>ARGOS</div>
        <div className={`${styles.dot} ${styles.live}`}></div>
        <div className={styles.statusPill}>ONLINE</div>
        <div className={styles.spacer}></div>
        <div className={styles.topbarMetric}>CoreAgent <span>{config.version}</span></div>
        <div className={styles.divider}></div>
        <div className={styles.topbarMetric}>Model <span>{config.model}</span></div>
      </div>
      
      {/* Sidebar - Docker/Infrastructure */}
      <CommandMonitor />
      
      {/* Center - Terminal/Chat */}
      <ChatTerminal 
        messages={messages} 
        isTyping={isTyping} 
        onSendMessage={sendMessage}
        error={error}
      />
      
      {/* Right - Telemetry/Rates */}
      <RateLimitWidget />
    </div>
  );
}

export default App;
