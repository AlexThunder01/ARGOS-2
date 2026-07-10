const API_KEY = import.meta.env.VITE_ARGOS_API_KEY || "test_key";

const baseHeaders = {
  "Content-Type": "application/json",
  "X-ARGOS-API-KEY": API_KEY,
};

export const ArgosAPI = {
  /**
   * Controlla lo stato base del sistema (System Check)
   */
  async getStatus() {
    const res = await fetch("/status");
    if (!res.ok) throw new Error("Failed to fetch system status");
    return res.json();
  },

  /**
   * Avvia una connessione Server-Sent Events per lo streaming della Chat.
   * L'endpoint /chat/stream non accetta headers Custom tramite EventSource standard nel browser,
   * quindi passiamo la key in query params o cambiamo approccio (es. fetch streaming).
   * Useremo fetch nativa asincrona così possiamo passare l'API Key negl header.
   */
  /**
   * Upload a single file and return { upload_id, filename }.
   * Throws on HTTP error or if the server rejects the file (422).
   */
  async uploadFile(file) {
    const formData = new FormData();
    formData.append("file", file);
    const res = await fetch("/api/upload", {
      method: "POST",
      // Do NOT set Content-Type — browser sets multipart boundary automatically
      headers: { "X-ARGOS-API-KEY": API_KEY },
      body: formData,
    });
    if (!res.ok) {
      const detail = await res.json().catch(() => ({ detail: res.statusText }));
      throw new Error(detail.detail || `Upload failed: ${res.status}`);
    }
    return res.json(); // { upload_id, filename }
  },

  async startChatStream(task, history, attachments, onPkt, onError, onComplete) {
    try {
        const response = await fetch("/api/chat/stream", {
            method: "POST",
            headers: baseHeaders,
            body: JSON.stringify({
                task: task,
                history: history,
                attachments: attachments || [],
                require_confirmation: false,
                max_steps: 10
            })
        });

        if (!response.ok) {
            throw new Error(`HTTP Error: ${response.status}`);
        }

        const reader = response.body.getReader();
        const decoder = new TextDecoder("utf-8");
        let buffer = "";

        while (true) {
            const { value, done } = await reader.read();
            if (done) break;
            
            buffer += decoder.decode(value, { stream: true });
            
            // Server-Sent events are separated by double newline
            const packets = buffer.split("\n\n");
            buffer = packets.pop(); // keep the last incomplete chunk
            
            for (const packet of packets) {
                if (packet.startsWith("data: ")) {
                    const dataStr = packet.substring(6);
                    if (dataStr === "[DONE]") {
                        onComplete();
                        return;
                    }
                    try {
                        const parsed = JSON.parse(dataStr);
                        onPkt(parsed);
                    } catch(e) {
                        console.error("SSE JSON Parse error:", e);
                    }
                }
            }
        }
        onComplete();
    } catch(e) {
        onError(e);
    }
  },

  /**
   * Statistiche Docker e Rate Limit protette
   */
  async getDockerStats() {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 15000);
    try {
      const res = await fetch("/api/stats/docker", { headers: baseHeaders, signal: controller.signal });
      if (!res.ok) throw new Error(`HTTP Error ${res.status}`);
      const data = await res.json();
      if (data.status === "error") throw new Error(data.message || "Unknown docker error");
      return data;
    } finally {
      clearTimeout(timeout);
    }
  },

  async getRateLimits() {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 15000);
    try {
      const res = await fetch("/api/stats/rate_limits", { headers: baseHeaders, signal: controller.signal });
      if (!res.ok) throw new Error(`HTTP Error ${res.status}`);
      const data = await res.json();
      if (data.error) throw new Error(data.error);
      return data;
    } finally {
      clearTimeout(timeout);
    }
  },

  async getSystemStats() {
    const res = await fetch("/api/stats/system", { headers: baseHeaders });
    if (!res.ok) throw new Error("Failed to fetch system stats");
    return res.json();
  },

  async getSecurityStats() {
    const res = await fetch("/api/stats/security", { headers: baseHeaders });
    if (!res.ok) throw new Error("Failed to fetch security stats");
    return res.json();
  },

  async getLatencyStats() {
    const res = await fetch("/api/stats/latency", { headers: baseHeaders });
    if (!res.ok) throw new Error("Failed to fetch latency stats");
    return res.json();
  },

  async getConfigStats() {
    const res = await fetch("/api/stats/config", { headers: baseHeaders });
    if (!res.ok) throw new Error("Failed to fetch config stats");
    return res.json();
  },

  async getToolsStats() {
    const res = await fetch("/api/stats/tools", { headers: baseHeaders });
    if (!res.ok) throw new Error("Failed to fetch tools stats");
    return res.json();
  }
};
