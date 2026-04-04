import React, { useState, useRef, useEffect } from 'react';
import styles from './ChatTerminal.module.css';

export default function ChatTerminal({ messages, isTyping, onSendMessage, error }) {
  const [input, setInput] = useState('');
  const messagesEndRef = useRef(null);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages, isTyping]);

  const handleSubmit = (e) => {
    e.preventDefault();
    if (!input.trim() || isTyping) return;
    onSendMessage(input);
    setInput('');
  };

  return (
    <div className={styles.chatArea}>
      <div className={styles.chatHeader}>
        <b>Terminal</b> — session #a3f9 — <span style={{color: 'var(--purple)'}}>--memory</span>
      </div>
      
      <div className={styles.messages}>
        {messages.length === 0 && (
          <div style={{margin: 'auto', color: 'var(--text2)', opacity: 0.5}}>No messages yet. Send a task.</div>
        )}
        
        {messages.map((msg, idx) => {
          const isUser = msg.role === 'user';
          return (
            <div key={idx} className={`${styles.msg} ${isUser ? styles.user : styles.agent}`}>
              <div className={styles.msgSender}>{isUser ? 'YOU' : 'ARGOS'}</div>
              
              {/* Tool Calls render slightly different */}
              {msg.tool_calls && msg.tool_calls.map((tc, tIdx) => (
                <div key={tIdx} className={styles.toolCall}>
                  ▶ tool: {tc.function?.name || 'unknown'}(...)
                </div>
              ))}
              
              {msg.content && (
                <div className={styles.bubble}>
                  {msg.content}
                </div>
              )}
            </div>
          );
        })}
        
        {isTyping && (
          <div className={`${styles.msg} ${styles.agent}`}>
            <div className={styles.msgSender}>ARGOS</div>
            <div className={styles.bubble}>
              Processing<span className={styles.cursor}></span>
            </div>
          </div>
        )}
        
        {error && (
          <div className={styles.error}>
            System Error: {error}
          </div>
        )}
        
        <div ref={messagesEndRef} />
      </div>
      
      <form className={styles.chatInputWrap} onSubmit={handleSubmit}>
        <input 
          className={styles.chatInput} 
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="Invia un task ad ARGOS..." 
          disabled={isTyping}
        />
        <button type="submit" className={styles.sendBtn} disabled={isTyping || !input.trim()}>
          SEND
        </button>
      </form>
    </div>
  );
}
