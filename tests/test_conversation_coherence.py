"""
Tests per coerenza conversazionale, memoria di sessione e policy del system prompt.

Coverage:
  - Policy nel system prompt : no "How can I help?", lingua, un tool per turno,
                               no split write actions, formato risposta JSON
  - Session memory           : storage long/short messages, maxlen, TF-IDF retrieval,
                               nessun falso positivo su query generiche
  - _maybe_extract_memories() : session mode + persistent mode (mocked)
  - _retrieve_session_memories: TF-IDF — documento rilevante score > irrilevante
  - _tfidf_similarity()       : funzione standalone (regression test)
  - Multi-turn               : la history cresce tra add_message, trim preserva recenti
  - run_task_stream()         : yielda chunk da think_stream
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from collections import deque
from unittest.mock import MagicMock, patch

import pytest

from src.agent import ArgosAgent, _count_tokens
from src.core.engine import CoreAgent, _tfidf_similarity
from src.core.memory import EXTRACT_MIN_LENGTH, should_extract_memory

# ==========================================================================
# Policy nel system prompt di ArgosAgent
# ==========================================================================


class TestSystemPromptPolicies:
    """
    Verifica che tutte le policy comportamentali siano presenti nel system prompt.
    Queste regole guidano la qualità e la coerenza delle risposte di Argos.
    """

    def setup_method(self):
        self.agent = ArgosAgent()
        self.prompt = self.agent.history[0]["content"]

    def test_language_policy_italian(self):
        """Argos deve rispondere in italiano di default."""
        assert "Italian" in self.prompt or "italian" in self.prompt.lower()

    def test_language_switch_rule(self):
        """Argos deve adattarsi alla lingua dell'utente."""
        assert "language" in self.prompt.lower() or "lingua" in self.prompt.lower()

    def test_no_how_can_i_help_rule(self):
        """Argos non deve aggiungere 'How can I help?' alla fine."""
        assert "How can I help" in self.prompt

    def test_single_tool_per_turn_rule(self):
        """Un solo tool per turno LLM — regola fondamentale."""
        # La regola è espressa con SINGLE, ONE, o ONLY nel prompt
        assert any(
            kw in self.prompt
            for kw in [
                "SINGLE",
                "single",
                "ONE",
                "ONLY",
                "one tool",
                "STRICTLY FORBIDDEN",
            ]
        )

    def test_no_split_write_actions_rule(self):
        """I write action non devono essere divisi in più tool call."""
        assert "split" in self.prompt.lower() or "SINGLE" in self.prompt

    def test_concise_response_rule(self):
        """Risposte devono essere concise e naturali."""
        assert "concise" in self.prompt.lower() or "EXTREMELY" in self.prompt

    def test_no_robotic_phrasing_rule(self):
        """Niente frasi robotiche nelle risposte."""
        assert "robotic" in self.prompt.lower() or "natural" in self.prompt.lower()

    def test_available_tools_present(self):
        """Il blocco AVAILABLE TOOLS deve essere nel prompt."""
        assert "AVAILABLE TOOLS" in self.prompt

    def test_done_false_action_json_format(self):
        """Il formato JSON per azioni deve essere documentato nel prompt."""
        assert '"done"' in self.prompt or "done" in self.prompt

    def test_response_format_with_done_true(self):
        """Il formato JSON per risposta finale deve essere nel prompt."""
        assert "done" in self.prompt and (
            "true" in self.prompt or "True" in self.prompt
        )

    def test_execute_only_what_requested(self):
        """Argos deve eseguire SOLO quello richiesto, senza azioni extra."""
        assert "ONLY" in self.prompt or "only" in self.prompt.lower()

    def test_no_hallucinate_tools(self):
        """Se non c'è il tool richiesto, Argos deve dirlo esplicitamente."""
        assert (
            "lack" in self.prompt.lower()
            or "DO NOT" in self.prompt
            or "HALLUCINATE" in self.prompt.upper()
        )


# ==========================================================================
# Session Memory — storage e retrieval
# ==========================================================================


class TestSessionMemoryStorage:
    def test_long_message_stored_in_session(self):
        """Messaggi > EXTRACT_MIN_LENGTH devono essere salvati in session memory."""
        agent = CoreAgent(memory_mode="session", inject_git_context=False)
        long_message = "L'utente preferisce Python per lo sviluppo backend. " * 5
        assert len(long_message) > EXTRACT_MIN_LENGTH

        agent._maybe_extract_memories(long_message, [])

        assert len(agent._session_memories) == 1
        assert "Python" in agent._session_memories[0]["content"]

    def test_short_message_not_stored_in_session(self):
        """Messaggi corti non vengono salvati in session memory."""
        agent = CoreAgent(memory_mode="session", inject_git_context=False)
        short_message = "ciao"
        assert len(short_message) <= EXTRACT_MIN_LENGTH

        agent._maybe_extract_memories(short_message, [])

        assert len(agent._session_memories) == 0

    def test_session_memory_content_truncated_at_200(self):
        """Il contenuto salvato viene troncato a 200 caratteri."""
        agent = CoreAgent(memory_mode="session", inject_git_context=False)
        very_long = "x" * 500

        agent._maybe_extract_memories(very_long, [])

        assert len(agent._session_memories[0]["content"]) <= 200

    def test_session_memory_category_is_fact(self):
        """La categoria default in session mode è 'fact'."""
        agent = CoreAgent(memory_mode="session", inject_git_context=False)
        agent._maybe_extract_memories("a" * 150, [])

        assert agent._session_memories[0]["category"] == "fact"

    def test_session_memory_maxlen_evicts_oldest(self):
        """La deque ha maxlen=500: le memorie più vecchie vengono espulse."""
        agent = CoreAgent(memory_mode="session", inject_git_context=False)

        # Riempi oltre maxlen
        for i in range(510):
            agent._session_memories.append(
                {"content": f"fact_{i:04d}", "category": "fact"}
            )

        assert len(agent._session_memories) == 500
        # La più vecchia (fact_0000) deve essere sparita
        contents = [m["content"] for m in agent._session_memories]
        assert "fact_0000" not in contents
        assert "fact_0509" in contents

    def test_off_mode_does_not_store(self):
        """In memory_mode='off', _maybe_extract_memories non deve fare nulla."""
        agent = CoreAgent(memory_mode="off", inject_git_context=False)
        agent._maybe_extract_memories("L'utente si chiama Alice " * 10, [])

        # Non ha _session_memories in senso utile (rimane vuota)
        assert len(agent._session_memories) == 0

    def test_persistent_mode_calls_extract_for_long_message(self):
        """In persistent mode, extract_memories_from_text deve essere chiamato."""
        agent = CoreAgent(memory_mode="persistent", inject_git_context=False)
        long_msg = "L'utente preferisce Python " * 10

        # Le funzioni sono importate localmente dentro _maybe_extract_memories,
        # quindi si patchano nel modulo sorgente (src.core.memory).
        with (
            patch("src.core.memory.should_extract_memory", return_value=True),
            patch(
                "src.core.memory.extract_memories_from_text", return_value=[]
            ) as mock_extract,
        ):
            agent._maybe_extract_memories(long_msg, [])

        mock_extract.assert_called_once()

    def test_persistent_mode_skips_extract_for_short_message(self):
        """In persistent mode, extract non viene chiamato per messaggi corti."""
        agent = CoreAgent(memory_mode="persistent", inject_git_context=False)

        with (
            patch("src.core.memory.should_extract_memory", return_value=False),
            patch("src.core.memory.extract_memories_from_text") as mock_extract,
        ):
            agent._maybe_extract_memories("ciao", [])

        mock_extract.assert_not_called()


# ==========================================================================
# Session Memory — TF-IDF retrieval
# ==========================================================================


class TestSessionMemoryRetrieval:
    def test_relevant_document_retrieved(self):
        """Query su Python deve recuperare la memoria su Python."""
        agent = CoreAgent(memory_mode="session", inject_git_context=False)
        agent._session_memories = deque(
            [
                {
                    "content": "L'utente preferisce Python per il backend",
                    "category": "interest",
                },
                {
                    "content": "L'utente lavora come avvocato a Milano",
                    "category": "fact",
                },
                {"content": "L'utente ha un gatto di nome Micio", "category": "fact"},
            ]
        )

        results = agent._retrieve_session_memories("Python programming language")

        assert len(results) > 0
        assert any("Python" in m["content"] for m in results)

    def test_irrelevant_query_returns_empty(self):
        """Una query completamente irrilevante non deve restituire niente."""
        agent = CoreAgent(memory_mode="session", inject_git_context=False)
        agent._session_memories = deque(
            [
                {
                    "content": "L'utente preferisce Python per il backend",
                    "category": "interest",
                },
            ]
        )

        # Query su un argomento completamente diverso
        results = agent._retrieve_session_memories("quantum physics particles")

        # Nessuna memoria rilevante: lista vuota o score sotto soglia
        # (Il threshold è 0.05 in session mode)
        # Non possiamo garantire 0 risultati con TF-IDF su testi corti,
        # ma possiamo verificare che "Python" non sia nelle prime posizioni
        # per una query irrilevante o che i risultati siano 0
        assert results == [] or not any("Python" in m["content"] for m in results[:1])

    def test_top_k_limits_results(self):
        """Il parametro top_k deve limitare il numero di risultati."""
        agent = CoreAgent(memory_mode="session", inject_git_context=False)
        agent._session_memories = deque(
            [
                {"content": f"Python fatto numero {i}", "category": "fact"}
                for i in range(10)
            ]
        )

        results = agent._retrieve_session_memories("Python", top_k=2)
        assert len(results) <= 2

    def test_retrieve_memories_returns_empty_when_off(self):
        agent = CoreAgent(memory_mode="off", inject_git_context=False)
        results = agent._retrieve_memories("qualsiasi query")
        assert results == []

    def test_retrieve_session_returns_empty_when_no_memories(self):
        agent = CoreAgent(memory_mode="session", inject_git_context=False)
        results = agent._retrieve_memories("Python")
        assert results == []

    def test_session_memory_isolation_between_agents(self):
        """Agenti diversi non condividono la session memory."""
        agent1 = CoreAgent(memory_mode="session", inject_git_context=False)
        agent2 = CoreAgent(memory_mode="session", inject_git_context=False)

        agent1._session_memories.append(
            {"content": "fatto agente 1", "category": "fact"}
        )

        assert len(agent2._session_memories) == 0


# ==========================================================================
# _tfidf_similarity() — unit test funzione standalone
# ==========================================================================


class TestTfidfSimilarity:
    def test_identical_query_and_document_high_score(self):
        """Query identica al documento deve avere score vicino a 1."""
        text = "Python backend development"
        scores = _tfidf_similarity(text, [text])
        assert scores[0] > 0.9

    def test_similar_documents_score_higher_than_unrelated(self):
        """Documento rilevante deve avere score più alto di uno irrilevante."""
        query = "Python programming"
        docs = [
            "Python is great for programming",  # rilevante
            "la cucina italiana è buonissima",  # irrilevante
        ]
        scores = _tfidf_similarity(query, docs)
        assert scores[0] > scores[1]

    def test_empty_documents_returns_zeros(self):
        scores = _tfidf_similarity("test query", [])
        assert scores == []

    def test_scores_between_zero_and_one(self):
        scores = _tfidf_similarity("test", ["testo di prova", "altro testo"])
        for s in scores:
            assert 0.0 <= s <= 1.0

    def test_returns_one_score_per_document(self):
        docs = ["doc one", "doc two", "doc three"]
        scores = _tfidf_similarity("query", docs)
        assert len(scores) == len(docs)

    def test_completely_unrelated_query_low_score(self):
        """Query e documento senza parole in comune → score basso."""
        scores = _tfidf_similarity("zzz yyy xxx", ["aaa bbb ccc"])
        assert scores[0] < 0.1


# ==========================================================================
# Multi-turn history behavior
# ==========================================================================


class TestMultiTurnHistory:
    def test_history_grows_with_messages(self):
        """add_message accumula messaggi nella history."""
        agent = ArgosAgent()
        initial_len = len(agent.history)

        agent.add_message("user", "turno 1")
        agent.add_message("assistant", "risposta 1")
        agent.add_message("user", "turno 2")

        assert len(agent.history) == initial_len + 3

    def test_trim_preserves_recent_in_multi_turn(self):
        """Dopo molti turni con budget stretto, i recenti sopravvivono."""
        agent = ArgosAgent()

        # Simula 15 turni di conversazione
        for i in range(15):
            agent.add_message("user", f"domanda turno {i:02d} " + "x" * 30)
            agent.add_message("assistant", f"risposta turno {i:02d} " + "y" * 30)

        system_tokens = _count_tokens(agent.history[0]["content"])
        # Budget per system + ~6 messaggi (circa 60 token)
        agent.token_budget = system_tokens + 60

        agent.trim_history()

        contents = " ".join(m["content"] for m in agent.history)

        # I turni più recenti devono essere presenti
        assert "turno 14" in contents
        # I turni vecchi devono essere spariti
        assert "turno 00" not in contents

    def test_build_llm_context_does_not_accumulate_between_tasks(self):
        """
        Chiamare _build_llm_context due volte non deve far crescere
        indefinitamente la history (ogni task reinizia il contesto).
        """
        agent = CoreAgent(memory_mode="off", inject_git_context=False)

        agent._build_llm_context("task 1", [])
        len1 = len(agent._llm.history)

        agent._build_llm_context("task 2", [])
        len2 = len(agent._llm.history)

        # Le due history devono avere la stessa lunghezza
        assert len1 == len2

    def test_injected_history_appears_before_current_task(self):
        """I messaggi iniettati precedono sempre il task corrente."""
        agent = CoreAgent(memory_mode="off", inject_git_context=False)
        agent._injected_history = [
            {"role": "user", "content": "primo messaggio"},
            {"role": "assistant", "content": "prima risposta"},
        ]

        agent._build_llm_context("task corrente", [])

        msgs = [m for m in agent._llm.history if m["role"] in ("user", "assistant")]
        # I messaggi iniettati devono venire prima del task corrente
        user_msgs = [m for m in msgs if m["role"] == "user"]
        assert user_msgs[-1]["content"] == "task corrente"
        assert user_msgs[-2]["content"] == "primo messaggio"

    def test_injected_history_cleared_after_run_task(self):
        """
        REGRESSIONE CLI — "Ti chiami Scrivania":
        _injected_history deve essere azzerata dopo run_task_async() in modo
        che il task successivo non erediti il contesto del precedente.
        Se il chiamante deve mantenere il contesto, deve re-impostare
        _injected_history prima di ogni chiamata (come fa il CLI loop).
        """
        import asyncio
        from unittest.mock import AsyncMock, patch

        agent = CoreAgent(memory_mode="off", inject_git_context=False)
        agent._injected_history = [
            {"role": "user", "content": "Mi chiamo Alessandro"},
            {"role": "assistant", "content": "Ciao Alessandro!"},
        ]

        async def run():
            with patch.object(
                agent._llm, "think_async", new_callable=AsyncMock
            ) as mock_think:
                mock_think.return_value = '{"thought":"ok","response":"OK","done":true}'
                await agent.run_task_async("task che consuma la history iniettata")

        asyncio.run(run())

        assert agent._injected_history == [], (
            "_injected_history deve essere [] dopo run_task_async, "
            "altrimenti il task successivo eredita contesto stantio"
        )

    def test_multiple_memories_all_injected(self):
        """Tutte le memorie rilevanti devono apparire nel contesto."""
        agent = CoreAgent(memory_mode="off", inject_git_context=False)
        memories = [
            {"category": "fact", "content": "Si chiama Alice"},
            {"category": "interest", "content": "Ama il jazz"},
            {"category": "preference", "content": "Preferisce Linux"},
        ]

        agent._build_llm_context("dimmi chi sono", memories)

        contents = " ".join(m["content"] for m in agent._llm.history)
        assert "Alice" in contents
        assert "jazz" in contents
        assert "Linux" in contents


# ==========================================================================
# run_task_stream() — streaming entry point
# ==========================================================================


class TestRunTaskStream:
    @patch("src.agent.requests.post")
    def test_run_task_stream_yields_chunks(self, mock_post):
        """run_task_stream deve yieldare almeno un chunk."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.iter_lines.return_value = iter(
            [
                b'data: {"choices": [{"delta": {"content": "chunk1"}}]}',
                b'data: {"choices": [{"delta": {"content": " chunk2"}}]}',
                b"data: [DONE]",
            ]
        )
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_post.return_value = mock_resp

        agent = CoreAgent(memory_mode="off", inject_git_context=False)
        agent._llm.backend = "openai-compatible"

        chunks = list(agent.run_task_stream("test streaming"))

        assert len(chunks) >= 1
        assert "chunk1" in "".join(chunks)

    @patch("src.agent.requests.post")
    def test_run_task_stream_reinitializes_history(self, mock_post):
        """run_task_stream deve reinizializzare la history prima di streammare."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.iter_lines.return_value = iter([b"data: [DONE]"])
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_post.return_value = mock_resp

        agent = CoreAgent(memory_mode="off", inject_git_context=False)
        agent._llm.backend = "openai-compatible"

        # Inquina la history
        agent._llm.add_message("user", "vecchio messaggio")
        agent._llm.add_message("assistant", "vecchia risposta")

        list(agent.run_task_stream("nuovo task"))

        # Dopo run_task_stream, la history deve contenere il nuovo task
        user_msgs = [m for m in agent._llm.history if m["role"] == "user"]
        assert any("nuovo task" in m["content"] for m in user_msgs)
        # Il vecchio messaggio non deve essere nel contesto
        assert not any("vecchio messaggio" in m["content"] for m in agent._llm.history)
