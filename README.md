# JARVIS - Local Multimodal AI Agent 🤖

![Python Version](https://img.shields.io/badge/python-3.10%2B-blue)
![License](https://img.shields.io/badge/license-MIT-green)
![Status](https://img.shields.io/badge/status-active-success)

**A fully autonomous, multimodal AI agent capable of interacting with the OS, seeing the screen, and speaking.**

> **Author's Note:** This project was built to demonstrate proficiency in LLM Agentic Workflows, Tool Use (Function Calling), and System Automation using Python.

---

## 📸 Demo

*(Inserisci qui una GIF o uno screenshot del terminale mentre Jarvis esegue un comando, es. crea un file o analizza lo schermo)*
`![Jarvis Demo](assets/demo_placeholder.gif)`

---

## ✨ Key Features

*   **🧠 Chain of Reaction:** Implements a recursive reasoning loop. Jarvis executes tools, reads the output, and decides the next step autonomously.
*   **👁️ Visual Grounding:** Can "see" the screen to answer questions or **click** specific UI elements using Vision Models (Llama 3.2 Vision / LLaVA).
*   **🔌 Hybrid Backend:**
    *   **Cloud Mode (Groq):** Ultra-fast inference (Llama 3 70B) for complex reasoning.
    *   **Local Mode (Ollama):** 100% private, offline capability using local models.
*   **🗣️ Voice Interface:** Integrated Speech-to-Text and Text-to-Speech for hands-free interaction.
*   **🛡️ Human-in-the-Loop:** Safety gates prevent critical actions (file deletion, typing) without explicit user confirmation.
*   **📂 OS Automation:** Full control over file system (Read/Write/Modify), application launching, and keyboard automation.

---

## 🛠️ Architecture

The agent follows a **ReAct (Reasoning + Acting)** pattern:

1.  **Perception:** Captures User Input (Voice/Text) + Environment State (Screen/Files).
2.  **Reasoning:** The LLM (Llama 3) analyzes the context and decides if a tool is needed, returning a structured **JSON**.
3.  **Execution:** The `Tool Manager` parses the JSON and executes the Python function (e.g., `subprocess`, `pyautogui`, `os`).
4.  **Feedback:** The tool output (stdout or error) is fed back into the conversation history.
5.  **Iteration:** The LLM decides the next move based on the new observation.

---

## 🚀 Installation

### 1. Clone the Repository
```bash
git clone https://github.com/YOUR_USERNAME/jarvis-agent.git
cd jarvis-agent
```

### 2. Set up Virtual Environment
```bash
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

### 3. Install Dependencies
```bash
pip install -r requirements.txt
```
*Linux Users:* You may need system libraries for audio and screenshots:
```bash
sudo apt-get install mpg123 scrot python3-tk
```

### 4. Configuration (.env)
Create a `.env` file based on the example:
```bash
cp .env.example .env
```
Open `.env` and configure your preferences:
```ini
LLM_BACKEND=groq             # 'groq' or 'ollama'
GROQ_API_KEY=gsk_...         # Your key here (free tier available)
ENABLE_VOICE=False           # Set to True to enable Mic/Speaker
```

---

## 💻 Usage

Run the main entry point:

```bash
python main.py
```

### Example Commands:
*   *"Create a python script named 'calc.py' on my Desktop that adds two numbers."*
*   *"Open Firefox and search for 'Python developer jobs in Italy'."*
*   *"Look at the screen and tell me where the 'Submit' button is, then click it."*
*   *"Read the file 'notes.txt' and summarize it."*

---

## 📁 Project Structure

```text
jarvis-agent/
├── src/
│   ├── agent.py       # Main Logic (LLM Context Management)
│   ├── tools.py       # Function Calling Implementation (OS, Web, App)
│   ├── vision.py      # Screenshot & Visual Analysis Logic
│   └── voice.py       # STT and TTS Modules
├── main.py            # Entry Point & Orchestrator
├── requirements.txt   # Python Dependencies
└── .env.example       # Config Template
```

---

## ⚠️ Disclaimer & Safety

This agent has permissions to execute commands and modify files.
*   **Safety Gate:** Dangerous tools (File Deletion, Keyboard Typing) will ask for `[y/N]` confirmation in the terminal.
*   **Sandboxing:** Do not run this on a production server with root privileges.

---

## 🤝 Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

1. Fork the Project
2. Create your Feature Branch (`git checkout -b feature/AmazingFeature`)
3. Commit your Changes (`git commit -m 'Add some AmazingFeature'`)
4. Push to the Branch (`git push origin feature/AmazingFeature`)
5. Open a Pull Request

---

## 📄 License

Distributed under the MIT License. See `LICENSE` for more information.
```
