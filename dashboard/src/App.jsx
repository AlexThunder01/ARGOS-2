import React from 'react';
import { useSSEChat } from './hooks/useSSEChat';
import ChatTerminal from './components/ChatTerminal/ChatTerminal';
import CommandMonitor from './components/CommandMonitor/CommandMonitor';
import RateLimitWidget from './components/RateLimitWidget/RateLimitWidget';
import './App.module.css'; // We'll create this or use index.css
import styles from './App.module.css';

function App() {
  const { messages, isTyping, error, sendMessage } = useSSEChat();

  return (
    <div className={styles.appContainer}>
      <header className={styles.header}>
        <div className={styles.logoGroup}>
          <span className={styles.logoLogo}>👁️</span>
          <h1>ARGOS-2 <span className={styles.tag}>Command Center</span></h1>
        </div>
        <div className={styles.statusGroup}>
          <div className={styles.pulseIndicator}></div>
          <span>System Online</span>
        </div>
      </header>
      
      <main className={styles.grid}>
        {/* Left column - Agent Interface */}
        <section className={styles.chatSection}>
          <ChatTerminal 
            messages={messages} 
            isTyping={isTyping} 
            onSendMessage={sendMessage}
            error={error}
          />
        </section>
        
        {/* Right column - Telemetry & Infrastructure */}
        <section className={styles.monitorSection}>
          <CommandMonitor />
          <RateLimitWidget />
        </section>
      </main>
    </div>
  );
}

export default App;
