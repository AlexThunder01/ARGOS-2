import { useState, useCallback, useRef, useEffect } from 'react';
import { ArgosAPI } from '../api/argos';

export function useSSEChat() {
  const [messages, setMessages] = useState([]);
  const [isTyping, setIsTyping] = useState(false);
  const [error, setError] = useState(null);

  // Keep a ref in sync so the callback always reads current messages
  // without needing to re-create itself (avoids stale closure).
  const messagesRef = useRef([]);
  useEffect(() => { messagesRef.current = messages; }, [messages]);

  const sendMessage = useCallback(async (prompt, attachments = [], fileNames = []) => {
    if (!prompt.trim()) return;

    // Add user message to UI
    const userMsg = { id: Date.now(), role: 'user', content: prompt, fileNames };
    setMessages(prev => [...prev, userMsg]);
    setIsTyping(true);
    setError(null);

    // Create placeholder for assistant response
    const agentMsgId = Date.now() + 1;
    setMessages(prev => [...prev, { id: agentMsgId, role: 'agent', content: '' }]);

    // Build history from the ref (always up-to-date, no stale closure)
    const history = messagesRef.current.map(m => {
      let content = m.content;
      if (m.fileNames && m.fileNames.length > 0) {
        content = `[Allegati: ${m.fileNames.join(', ')}]\n${content}`;
      }
      return { role: m.role, content };
    });

    await ArgosAPI.startChatStream(
      prompt,
      history,
      attachments,
      (pkt) => {
        if (pkt.chunk) {
          setMessages(prev => prev.map(m =>
            m.id === agentMsgId ? { ...m, content: m.content + pkt.chunk } : m
          ));
        }
      },
      (err) => {
        console.error("Chat Stream Error:", err);
        setError(err.message || "Failed to communicate with CoreAgent");
        setIsTyping(false);
      },
      () => {
        setIsTyping(false);
      }
    );
  }, []);

  return { messages, isTyping, error, sendMessage };
}
