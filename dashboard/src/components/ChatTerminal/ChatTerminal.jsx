import React, { useState, useRef, useEffect } from 'react';
import styles from './ChatTerminal.module.css';

export default function ChatTerminal({ messages, isTyping, onSendMessage, error }) {
  const [input, setInput] = useState('');
  const endRef = useRef(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, isTyping]);

  const handleSubmit = (e) => {
    e.preventDefault();
    if (input.trim() && !isTyping) {
      onSendMessage(input);
      setInput('');
    }
  };

  return (
    <div className={`glass-panel ${styles.terminal}`}>
      <div className={styles.header}>
        <h3>// PRIMARY INTERFACE</h3>
        <span className={styles.tag}>secure_bridge</span>
      </div>
      
      <div className={styles.messageLog}>
        {messages.length === 0 && (
          <div className={styles.emptyState}>
            Awaiting instructions, Operator.
          </div>
        )}
        
        {messages.map((msg, idx) => (
          <div key={msg.id || idx} className={`${styles.message} ${styles[msg.role]}`}>
            <div className={styles.avatar}>
              {msg.role === 'user' ? 'U' : 'A'}
            </div>
            <div className={styles.content}>
              {msg.content || (msg.role === 'agent' && isTyping && idx === messages.length -1 ? <span className={styles.cursor}></span> : '')}
            </div>
          </div>
        ))}
        {error && (
          <div className={`${styles.message} ${styles.error}`}>
            <div className={styles.avatar}>!</div>
            <div className={styles.content}>{error}</div>
          </div>
        )}
        <div ref={endRef} />
      </div>

      <form className={styles.inputArea} onSubmit={handleSubmit}>
        <div className={styles.inputWrapper}>
          <span className={styles.prompt}>$</span>
          <input 
            type="text" 
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="Initialize command sequence..."
            disabled={isTyping}
            autoFocus
          />
        </div>
        <button type="submit" disabled={isTyping || !input.trim()} className={styles.submitBtn}>
          EXECUTE
        </button>
      </form>
    </div>
  );
}
