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
  async startChatStream(task, onPkt, onError, onComplete) {
    try {
        const response = await fetch("/api/chat/stream", {
            method: "POST",
            headers: baseHeaders,
            body: JSON.stringify({
                task: task,
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
    const res = await fetch("/api/stats/docker", { headers: baseHeaders });
    if (!res.ok) throw new Error("Failed to fetch Docker stats");
    return res.json();
  },

  async getRateLimits() {
    const res = await fetch("/api/stats/rate_limits", { headers: baseHeaders });
    if (!res.ok) throw new Error("Failed to fetch Rate Limits");
    return res.json();
  }
};
