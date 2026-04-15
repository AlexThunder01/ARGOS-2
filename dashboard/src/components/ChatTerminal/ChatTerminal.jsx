import React, { useState, useRef, useEffect, useCallback } from 'react';
import styles from './ChatTerminal.module.css';
import { ArgosAPI } from '../../api/argos';

const MAX_FILES = 5;

export default function ChatTerminal({ messages, isTyping, onSendMessage, error }) {
  const [input, setInput] = useState('');
  const [pendingFiles, setPendingFiles] = useState([]); // { file, upload_id, error }
  const [isDragOver, setIsDragOver] = useState(false);
  const messagesEndRef = useRef(null);
  const fileInputRef = useRef(null);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages, isTyping]);

  const addFiles = useCallback(async (files) => {
    const newFiles = Array.from(files).slice(0, MAX_FILES - pendingFiles.length);
    if (newFiles.length === 0) return;

    // Add as uploading placeholders
    const placeholders = newFiles.map(f => ({ file: f, upload_id: null, error: null }));
    setPendingFiles(prev => [...prev, ...placeholders]);

    // Upload each file in parallel
    const results = await Promise.all(
      newFiles.map(async (file) => {
        try {
          const data = await ArgosAPI.uploadFile(file);
          return { file, upload_id: data.upload_id, error: null };
        } catch (err) {
          return { file, upload_id: null, error: err.message };
        }
      })
    );

    setPendingFiles(prev => {
      // Replace placeholders with resolved results
      const updated = [...prev];
      results.forEach((res) => {
        const idx = updated.findIndex(p => p.file === res.file && p.upload_id === null && p.error === null);
        if (idx !== -1) updated[idx] = res;
      });
      return updated;
    });
  }, [pendingFiles.length]);

  const removeFile = (idx) => {
    setPendingFiles(prev => prev.filter((_, i) => i !== idx));
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!input.trim() || isTyping) return;

    const ready = pendingFiles.filter(f => f.upload_id);
    const uploadIds = ready.map(f => f.upload_id);
    const fileNames = ready.map(f => f.file.name);

    onSendMessage(input, uploadIds, fileNames);
    setInput('');
    setPendingFiles([]);
  };

  // Drag & drop
  const handleDragOver = (e) => { e.preventDefault(); setIsDragOver(true); };
  const handleDragLeave = () => setIsDragOver(false);
  const handleDrop = (e) => {
    e.preventDefault();
    setIsDragOver(false);
    addFiles(e.dataTransfer.files);
  };

  return (
    <div
      className={`${styles.chatArea} ${isDragOver ? styles.dropZoneActive : ''}`}
      onDragOver={handleDragOver}
      onDragLeave={handleDragLeave}
      onDrop={handleDrop}
    >
      {isDragOver && (
        <div className={styles.dropZone}>Drop files here</div>
      )}

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

              {msg.tool_calls && msg.tool_calls.map((tc, tIdx) => (
                <div key={tIdx} className={styles.toolCall}>
                  ▶ tool: {tc.function?.name || 'unknown'}(...)
                </div>
              ))}

              {msg.fileNames && msg.fileNames.length > 0 && (
                <div className={styles.attachPreview}>
                  {msg.fileNames.map((name, i) => (
                    <span key={i} className={styles.attachChip}>📎 {name}</span>
                  ))}
                </div>
              )}

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

      {/* Attachment chips */}
      {pendingFiles.length > 0 && (
        <div className={styles.attachPreview}>
          {pendingFiles.map((pf, idx) => (
            <span
              key={idx}
              className={`${styles.attachChip} ${pf.error ? styles.attachChipError : ''}`}
              title={pf.error || pf.file.name}
            >
              {pf.error ? '❌' : pf.upload_id ? '📎' : '⏳'} {pf.file.name}
              <button
                type="button"
                className={styles.attachChipRemove}
                onClick={() => removeFile(idx)}
              >×</button>
            </span>
          ))}
        </div>
      )}

      <form className={styles.chatInputWrap} onSubmit={handleSubmit}>
        <input
          type="file"
          hidden
          multiple
          ref={fileInputRef}
          onChange={(e) => { addFiles(e.target.files); e.target.value = ''; }}
        />
        <button
          type="button"
          className={styles.attachBtn}
          onClick={() => fileInputRef.current?.click()}
          disabled={isTyping || pendingFiles.length >= MAX_FILES}
          title="Attach files"
        >
          📎
        </button>
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
