import { useState, useCallback, useEffect } from 'react';
import { ArgosAPI } from '../api/argos';

export function useSSEChat() {
  const [messages, setMessages] = useState([]);
  const [isTyping, setIsTyping] = useState(false);
  const [error, setError] = useState(null);
  const [chats, setChats] = useState([]);
  const [currentChatId, setCurrentChatId] = useState(null);

  const refreshChats = useCallback(async () => {
    const list = await ArgosAPI.listChats();
    setChats(list);
    return list;
  }, []);

  const loadChatMessages = useCallback(async (chatId) => {
    const history = await ArgosAPI.getChatMessages(chatId);
    setMessages(history.map((m, i) => ({ id: i, role: m.role, content: m.content })));
  }, []);

  // On mount: resume the most recently used chat, or create one if none exist
  // yet — unlike the CLI (where chat selection is always explicit), the
  // Dashboard must show a working chat on first load with no extra click.
  useEffect(() => {
    (async () => {
      try {
        const list = await refreshChats();
        if (list.length > 0) {
          setCurrentChatId(list[0].id);
          await loadChatMessages(list[0].id);
        } else {
          const created = await ArgosAPI.createChat();
          setChats([created]);
          setCurrentChatId(created.id);
        }
      } catch (e) {
        setError(e.message || "Failed to initialize chat");
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const switchChat = useCallback(async (chatId) => {
    setError(null);
    setCurrentChatId(chatId);
    try {
      await loadChatMessages(chatId);
    } catch (e) {
      setError(e.message || "Failed to load chat messages");
    }
  }, [loadChatMessages]);

  const startNewChat = useCallback(async () => {
    setError(null);
    try {
      const created = await ArgosAPI.createChat();
      setChats(prev => [created, ...prev]);
      setCurrentChatId(created.id);
      setMessages([]);
      return created;
    } catch (e) {
      setError(e.message || "Failed to create new chat");
    }
  }, []);

  const sendMessage = useCallback(async (prompt, attachments = [], fileNames = []) => {
    if (!prompt.trim() || !currentChatId) return;

    // Add user message to UI
    const userMsg = { id: Date.now(), role: 'user', content: prompt, fileNames };
    setMessages(prev => [...prev, userMsg]);
    setIsTyping(true);
    setError(null);

    // Create placeholder for assistant response
    const agentMsgId = Date.now() + 1;
    setMessages(prev => [...prev, { id: agentMsgId, role: 'agent', content: '' }]);

    await ArgosAPI.startChatStream(
      prompt,
      currentChatId,
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
        // Picks up the server-generated title (and reordering by last_used_at)
        // after the first turn of a new chat completes.
        refreshChats().catch((e) => {
          console.error("Failed to refresh chats after message:", e);
        });
      }
    );
  }, [currentChatId, refreshChats]);

  return { messages, isTyping, error, sendMessage, chats, currentChatId, switchChat, startNewChat };
}
