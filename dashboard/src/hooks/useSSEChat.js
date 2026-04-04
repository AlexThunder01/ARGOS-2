import { useState, useCallback } from 'react';
import { ArgosAPI } from '../api/argos';

export function useSSEChat() {
  const [messages, setMessages] = useState([]);
  const [isTyping, setIsTyping] = useState(false);
  const [error, setError] = useState(null);

  const sendMessage = useCallback(async (prompt) => {
    if (!prompt.trim()) return;

    // Add user message to UI
    const userMsg = { id: Date.now(), role: 'user', content: prompt };
    setMessages(prev => [...prev, userMsg]);
    setIsTyping(true);
    setError(null);

    // Create placeholder for assistant response
    const agentMsgId = Date.now() + 1;
    setMessages(prev => [...prev, { id: agentMsgId, role: 'agent', content: '' }]);

    await ArgosAPI.startChatStream(
      prompt,
      (pkt) => {
        // SSE Packet received
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
