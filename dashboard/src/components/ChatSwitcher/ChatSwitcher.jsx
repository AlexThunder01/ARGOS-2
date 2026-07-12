import React, { useState, useRef, useEffect } from 'react';
import styles from './ChatSwitcher.module.css';

export default function ChatSwitcher({ chats, currentChatId, onSwitchChat, onNewChat }) {
  const [open, setOpen] = useState(false);
  const wrapRef = useRef(null);

  useEffect(() => {
    function handleClickOutside(e) {
      if (wrapRef.current && !wrapRef.current.contains(e.target)) {
        setOpen(false);
      }
    }
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  const current = chats.find(c => c.id === currentChatId);
  const label = current ? (current.title || `Chat #${current.id}`) : '...';

  return (
    <div className={styles.wrap} ref={wrapRef}>
      <button className={styles.pill} onClick={() => setOpen(o => !o)}>
        💬 {label} ▾
      </button>
      {open && (
        <div className={styles.menu}>
          {chats.map(c => (
            <div
              key={c.id}
              className={`${styles.item} ${c.id === currentChatId ? styles.active : ''}`}
              onClick={() => { onSwitchChat(c.id); setOpen(false); }}
            >
              {c.title || `Chat #${c.id}`}
            </div>
          ))}
          <div className={styles.newChat} onClick={() => { onNewChat(); setOpen(false); }}>
            + Nuova chat
          </div>
        </div>
      )}
    </div>
  );
}
