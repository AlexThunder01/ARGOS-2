"""
ToolSpec — Unica sorgente di verità per ogni tool di ARGOS.

Unifica: executor + Pydantic input schema + metadati (categoria, risk, icon, label).
Sostituisce TOOLS dict, TOOL_METADATA dict, _TOOL_INPUT_EXAMPLES hardcoded e il
testo AVAILABLE TOOLS nel system prompt.
"""

import json
import logging
from collections.abc import Callable
from dataclasses import dataclass

import numpy as np
from pydantic import BaseModel

logger = logging.getLogger("argos")


class ToolInput(BaseModel):
    """Base class per tutti gli input schema dei tool. Tollerante verso campi extra."""

    model_config = {"extra": "allow"}


@dataclass
class ToolSpec:
    """
    Specifica completa e serializzabile di un tool ARGOS.

    Attributes:
        name: Identificatore univoco usato nel JSON del planner.
        description: Descrizione breve (system prompt + dashboard).
        input_schema: Pydantic model che valida l'input del LLM.
        executor: Funzione (dict) -> str che implementa il tool.
        risk: "none" | "low" | "medium" | "high" | "critical"
        category: "filesystem" | "web" | "finance" | "code" | "system" | "gui" | "documents"
        icon: Emoji per il dashboard.
        label: Nome leggibile per il dashboard.
        dashboard_allowed: True → incluso nella whitelist del dashboard.
    """

    name: str
    description: str
    input_schema: type[ToolInput]
    executor: Callable[[dict], str]
    risk: str
    category: str
    icon: str
    label: str
    dashboard_allowed: bool = False
    group: str | None = None  # "coding" | "research" | "automation" | None (tutti)

    def prompt_example(self) -> str:
        """Genera il JSON di esempio per il system prompt dal Pydantic schema."""
        schema = self.input_schema.model_json_schema()
        props = schema.get("properties", {})
        if not props:
            return "(no input needed)"
        example: dict = {}
        for field_name, field_info in props.items():
            # Use explicit example if provided in Field(examples=[...])
            examples = field_info.get("examples")
            if examples:
                example[field_name] = examples[0]
                continue
            ftype = field_info.get("type", "string")
            if ftype == "string":
                example[field_name] = "..."
            elif ftype == "integer":
                example[field_name] = 0
            elif ftype == "number":
                example[field_name] = 0.0
            elif ftype == "boolean":
                example[field_name] = False
            else:
                example[field_name] = "..."
        return json.dumps(example, ensure_ascii=False)

    def to_metadata(self) -> dict[str, str]:
        """Formato TOOL_METADATA compatibile con il dashboard."""
        return {
            "category": self.category,
            "icon": self.icon,
            "label": self.label,
            "risk": self.risk,
            "description": self.description,
        }

    def requires_confirmation(self) -> bool:
        """True se il tool richiede conferma utente in modalità CLI."""
        return self.risk in ("medium", "high", "critical")

    def to_openai_schema(self) -> dict[str, object]:
        """Converts this ToolSpec to an OpenAI-format function calling schema."""
        schema = self.input_schema.model_json_schema()
        schema.pop("title", None)
        for prop in schema.get("properties", {}).values():
            prop.pop("title", None)
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": schema,
            },
        }

    def validate_input(self, raw: object) -> dict[str, object]:
        """
        Valida l'input grezzo del LLM tramite lo schema Pydantic.
        Fallback al dict raw in caso di errore, per retrocompatibilità.
        """
        if raw is None:
            raw = {}
        if isinstance(raw, str):
            try:
                raw = json.loads(raw)
            except Exception:
                raw = {}
        try:
            validated = self.input_schema.model_validate(raw)
            return validated.model_dump(exclude_none=True)
        except Exception:
            return raw if isinstance(raw, dict) else {}


class ToolRegistry:
    """
    Registry globale di tutti i ToolSpec di ARGOS.

    Alimenta:
    - TOOLS dict (backward compat)
    - TOOL_METADATA dict (backward compat)
    - DASHBOARD_TOOLS_WHITELIST
    - Sezione AVAILABLE TOOLS del system prompt
    """

    _CATEGORY_ORDER = [
        ("gui", "VISION"),
        ("system", "SYSTEM"),
        ("filesystem", "FILE SYSTEM"),
        ("web", "WEB & DATA"),
        ("finance", "FINANCE"),
        ("code", "CODE EXECUTION"),
        ("documents", "DOCUMENT PARSING"),
    ]

    def __init__(self, specs: list[ToolSpec]) -> None:
        self._specs: dict[str, ToolSpec] = {s.name: s for s in specs}
        self._corpus_vecs: np.ndarray | None = None  # cached tool embeddings
        self._corpus_names: list[str] = []

    def __getitem__(self, name: str) -> ToolSpec:
        return self._specs[name]

    def __contains__(self, name: str) -> bool:
        return name in self._specs

    def __len__(self) -> int:
        return len(self._specs)

    def get(self, name: str) -> ToolSpec | None:
        return self._specs.get(name)

    def names(self) -> list[str]:
        return list(self._specs.keys())

    def filter(self, allowed: set[str]) -> "ToolRegistry":
        """Restituisce un nuovo registry con solo i tool specificati."""
        return ToolRegistry([s for s in self._specs.values() if s.name in allowed])

    def filter_by_group(self, group: str) -> "ToolRegistry":
        """
        Restituisce un nuovo registry filtrato per gruppo.

        Gruppi predefiniti:
          - "coding"     → filesystem + code
          - "research"   → web + finance + documents
          - "automation" → gui + system

        I tool senza `group` assegnato sono inclusi SEMPRE (tool di base).
        """
        _GROUP_CATEGORIES: dict[str, set[str]] = {
            "coding": {"filesystem", "code"},
            "research": {"web", "finance", "documents"},
            "automation": {"gui", "system"},
        }
        allowed_categories = _GROUP_CATEGORIES.get(group, set())
        filtered = [
            s for s in self._specs.values() if s.group is None or s.category in allowed_categories
        ]
        return ToolRegistry(filtered)

    def as_tools_dict(self) -> dict[str, Callable[[dict], str]]:
        """Backward compat: {name: executor_fn}."""
        return {name: spec.executor for name, spec in self._specs.items()}

    def as_metadata_dict(self) -> dict[str, dict[str, str]]:
        """Backward compat: formato TOOL_METADATA."""
        return {name: spec.to_metadata() for name, spec in self._specs.items()}

    def dashboard_whitelist(self) -> set[str]:
        """Nomi dei tool con dashboard_allowed=True."""
        return {name for name, spec in self._specs.items() if spec.dashboard_allowed}

    def as_openai_tools(self) -> list[dict[str, object]]:
        """Returns all specs as OpenAI-format tool definitions for LiteLLM."""
        return [spec.to_openai_schema() for spec in self._specs.values()]

    # Tools that must always be co-selected together.
    # If any key in a pair is selected by RAG, its companions are added automatically.
    # This prevents the agent from having read_file without list_files (exploration gap).
    _COSELECT_PAIRS: dict[str, set[str]] = {
        "read_file": {"list_files"},
        "read_pdf": {"list_files"},
        "read_csv": {"list_files"},
        "read_json": {"list_files"},
        "modify_file": {"list_files", "read_file"},
        "delete_file": {"list_files"},
        "rename_file": {"list_files"},
    }

    def select_for_query(self, query: str, top_k: int = 12) -> "ToolRegistry":
        """
        Returns top_k tools most relevant to query using embedding cosine similarity.
        Falls back to full registry if embedding service is unavailable or top_k >= len.
        """
        if len(self._specs) <= top_k:
            return self

        try:
            import hashlib
            import pathlib

            import numpy as np

            from src.core.memory import get_embeddings_batch

            names = list(self._specs.keys())
            corpus = [f"{s.name} {s.description} {s.category}" for s in self._specs.values()]
            corpus_key = hashlib.md5("|".join(corpus).encode()).hexdigest()[:16]

            if self._corpus_vecs is None or self._corpus_names != names:
                # Try loading from disk cache first
                cache_path = pathlib.Path(f".cache/tool_embeddings_{corpus_key}.npz")
                if cache_path.exists():
                    loaded = np.load(cache_path)
                    self._corpus_vecs = loaded["vecs"]
                    self._corpus_names = names
                else:
                    all_vecs = get_embeddings_batch(corpus)
                    self._corpus_vecs = np.array(all_vecs, dtype=np.float32)
                    self._corpus_names = names
                    cache_path.parent.mkdir(exist_ok=True)
                    np.savez(cache_path, vecs=self._corpus_vecs)

            query_vec = get_embeddings_batch([query])[0]
            tool_vecs = self._corpus_vecs

            # Cosine similarity
            query_norm = query_vec / (np.linalg.norm(query_vec) + 1e-8)
            tool_norms = tool_vecs / (np.linalg.norm(tool_vecs, axis=1, keepdims=True) + 1e-8)
            scores = tool_norms @ query_norm

            top_indices = scores.argsort()[-top_k:][::-1]
            selected = {names[i] for i in top_indices}

            for tool_name, companions in self._COSELECT_PAIRS.items():
                if tool_name in selected:
                    for companion in companions:
                        if companion in self._specs:
                            selected.add(companion)

            return self.filter(selected)
        except Exception as e:
            # Fails open to the full registry (better an unfiltered tool list than
            # none), but this is silent otherwise — e.g. the embedding service being
            # unreachable looks identical to "every tool is relevant" in the logs
            # unless this is logged explicitly.
            # debug, not warning: this is the CLI's default steady state (Ollama
            # only auto-starts under --memory), so it fires on nearly every query
            # in plain CLI mode — warning level would print it to the interactive
            # console (tracer.py's console handler shows INFO+) on every message.
            logger.debug(f"[ToolRAG] select_for_query fell back to full registry: {e}")
            return self

    def build_prompt_block(self, group: str | None = None) -> str:
        """
        Genera il blocco AVAILABLE TOOLS per il system prompt, raggruppato per categoria.
        Questa è l'unica fonte di verità: nessun testo hardcoded altrove.

        Args:
            group: Se specificato, include solo i tool del gruppo dato
                   ("coding", "research", "automation"). None = tutti.
        """
        registry = self.filter_by_group(group) if group else self
        grouped: dict[str, list[str]] = {}
        for spec in registry._specs.values():
            example = spec.prompt_example()
            if example == "(no input needed)":
                line = f"        - {spec.name}"
            else:
                line = f"        - {spec.name}: {example}"
            grouped.setdefault(spec.category, []).append(line)

        lines = [
            '        AVAILABLE TOOLS (the names below must be used in "action" -> "tool" and "input"):'
        ]
        for cat_key, cat_label in self._CATEGORY_ORDER:
            if cat_key in grouped:
                lines.append(f"        --- {cat_label} ---")
                lines.extend(grouped[cat_key])
                lines.append("")

        return "\n".join(lines).rstrip()
