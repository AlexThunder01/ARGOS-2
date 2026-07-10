"""
Behavioral runtime configuration — loaded from config.yaml, hot-reloaded on change.

BOUNDARY: this module owns anything an operator might tune while the server is running:
assistant personas, tone, conversation window, memory thresholds, auto-approve flags,
sender blacklists, priority filters.
Infrastructure settings (API keys, DB URLs, model names, rate limits) live in
src/config.py (.env, requires restart).
"""

import atexit
import logging
import os
import threading

import yaml
from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

logger = logging.getLogger(__name__)


class WorkflowsConfig:
    """Read-only data wrapper for the parsed configuration dictionary."""

    def __init__(self, data: dict):
        self._data = data

    @property
    def is_enabled(self) -> bool:
        return self._data.get("gmail_assistant", {}).get("enabled", False)

    @property
    def ignore_senders(self) -> list[str]:
        return self._data.get("gmail_assistant", {}).get("filters", {}).get("ignore_senders", [])

    @property
    def allowed_languages(self) -> list[str]:
        return self._data.get("gmail_assistant", {}).get("filters", {}).get("allowed_languages", [])

    @property
    def min_priority(self) -> str:
        return (
            self._data.get("gmail_assistant", {})
            .get("filters", {})
            .get("min_priority", "MEDIUM")
            .upper()
        )

    @property
    def tone_of_voice(self) -> str:
        return (
            self._data.get("gmail_assistant", {})
            .get("behavior", {})
            .get("tone_of_voice", "professional")
        )

    @property
    def custom_signature(self) -> str:
        return self._data.get("gmail_assistant", {}).get("behavior", {}).get("custom_signature", "")

    # --- Telegram Chat Module Properties ---

    @property
    def is_telegram_enabled(self) -> bool:
        return self._data.get("telegram_assistant", {}).get("enabled", False)

    @property
    def telegram_config(self) -> dict:
        return self._data.get("telegram_assistant", {})

    @property
    def telegram_bot_name(self) -> str:
        return (
            self._data.get("telegram_assistant", {})
            .get("identity", {})
            .get("bot_name", "AI Assistant")
        )

    @property
    def telegram_persona(self) -> str:
        return self._data.get("telegram_assistant", {}).get("identity", {}).get("persona", "")

    @property
    def telegram_welcome_message(self) -> str:
        return (
            self._data.get("telegram_assistant", {})
            .get("identity", {})
            .get("welcome_message", "Hello!")
        )

    @property
    def telegram_unauthorized_message(self) -> str:
        return (
            self._data.get("telegram_assistant", {})
            .get("identity", {})
            .get("unauthorized_message", "Access denied.")
        )

    @property
    def telegram_conversation_window(self) -> int:
        return (
            self._data.get("telegram_assistant", {})
            .get("behavior", {})
            .get("conversation_window", 20)
        )

    @property
    def telegram_max_memories(self) -> int:
        return (
            self._data.get("telegram_assistant", {})
            .get("behavior", {})
            .get("max_memories_retrieved", 3)
        )

    @property
    def telegram_rag_threshold(self) -> float:
        return (
            self._data.get("telegram_assistant", {})
            .get("behavior", {})
            .get("rag_similarity_threshold", 0.70)
        )

    @property
    def telegram_max_input_length(self) -> int:
        return (
            self._data.get("telegram_assistant", {})
            .get("behavior", {})
            .get("max_input_length", 4000)
        )

    @property
    def telegram_auto_approve(self) -> bool:
        return self._data.get("telegram_assistant", {}).get("admin", {}).get("auto_approve", False)

    @property
    def telegram_notify_on_new_user(self) -> bool:
        return (
            self._data.get("telegram_assistant", {})
            .get("admin", {})
            .get("notify_on_new_user", True)
        )


# Thread-Safe Global Cache
_config_lock = threading.Lock()
_config_cache = {}
_config_file_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "config.yaml")


def _reload_config():
    """Reads the YAML file from disk and updates the in-memory cache safely."""
    try:
        if os.path.exists(_config_file_path):
            with open(_config_file_path, encoding="utf-8") as f:
                new_config = yaml.safe_load(f) or {}
                with _config_lock:
                    _config_cache.clear()
                    _config_cache.update(new_config)
            logger.info(f"[Config] Successfully reloaded {_config_file_path}")
    except Exception as e:
        logger.error(f"[Config] Error parsing {_config_file_path}: {e}")


class ConfigFileHandler(FileSystemEventHandler):
    """Event handler that triggers a cache reload when config.yaml is modified."""

    def on_modified(self, event):
        if event.src_path == _config_file_path:
            _reload_config()


# Initialization logic (Runs exactly once when the module is imported by FastAPI)
_reload_config()

_observer = Observer()
# We watch the parent directory because editors (vim/nano) often do atomic saves
# (creating a new file and renaming), which breaks single-file watches.
_observer.schedule(ConfigFileHandler(), path=os.path.dirname(_config_file_path), recursive=False)
_observer.start()
atexit.register(_observer.stop)


def get_workflows_config() -> WorkflowsConfig:
    """Returns a thread-safe snapshot of the current configuration logic."""
    with _config_lock:
        # We pass a defensive copy of the dict to prevent accidental mutation downstream
        return WorkflowsConfig(dict(_config_cache))
