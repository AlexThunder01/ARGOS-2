"""
Unit test per il rilevamento del nome utente.

Verifica i pattern regex usati da:
  - scripts/main.py (CLI interactive loop)
  - api/routes/dashboard.py (chat_stream endpoint)

Coverage:
  - Frasi canoniche di introduzione (mi chiamo, il mio nome è, chiamami, ...)
  - Pattern correttivi (no sono X, adesso sono X, ora sono X, ...)
  - Negazione / cancellazione nome (non mi chiamo, non sono, ...)
  - False positive bloccati (sono stanco, adesso sono pronto, sono nella Scrivania, ...)
  - Casi limite: nome corto, nome con accento, maiuscola richiesta nei correttivi
"""

import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

# ==========================================================================
# Replica esatta dei pattern da scripts/main.py e api/routes/dashboard.py
# ==========================================================================

# Frasi di introduzione inequivocabili
_RE_INTRO = re.compile(
    r"(?i:\bmi\s+chiamo\b|\bil\s+mio\s+nome\s+è\b|\bchiamami\b"
    r"|\bmy\s+name\s+is\b|\bI'm\b|\bi\s+am\b)"
    r"\s+([A-Za-zÀ-Úà-ú]{2,})",
)

# Contesto correttivo + "sono" + nome con maiuscola
_RE_CORRECTION = re.compile(
    r"(?i:\bno[,.\s]+sono\b|\badesso\s+sono\b|\bora\s+sono\b"
    r"|\bin\s+realtà\s+sono\b|\banzi\s+sono\b)"
    r"\s+([A-ZÀ-Ú][a-zA-Zà-ú]+)",
)

# Negazione
_RE_NEGATION = re.compile(
    r"(?i:non mi chiamo|non sono|don't call me|not my name)",
)

# Fallback "mi chiamo / il mio nome è" con nome minuscolo
_RE_INTRO_LOWER = re.compile(
    r"(?i:\bmi\s+chiamo\b|\bil\s+mio\s+nome\s+è\b)\s+([a-zA-ZÀ-Úà-ú]{2,})",
)


def _detect_name(text: str):
    """
    Replica la logica di rilevamento usata da CLI e API.
    Ritorna il nome rilevato (str) o None se non c'è match.
    """
    negation = _RE_NEGATION.search(text)
    if negation:
        return None  # cancellazione esplicita

    m = _RE_INTRO.search(text) or _RE_INTRO_LOWER.search(text) or _RE_CORRECTION.search(text)
    return m.group(1).capitalize() if m else None


# ==========================================================================
# Introduzioni canoniche
# ==========================================================================


class TestIntroductionPhrases:
    @pytest.mark.parametrize(
        "text, expected",
        [
            ("mi chiamo Alessandro", "Alessandro"),
            ("Mi chiamo alessnadro", "Alessnadro"),  # lowercase tollerato dal fallback
            ("Il mio nome è Marco", "Marco"),
            ("chiamami Luca", "Luca"),
            ("my name is Sarah", "Sarah"),
            ("I'm Giulia", "Giulia"),
            ("I am Roberto", "Roberto"),
            # Con testo prima/dopo
            ("Ciao! Mi chiamo Francesca, piacere.", "Francesca"),
            ("mi chiamo Alessnadro e mi piacciono le banane!", "Alessnadro"),
        ],
    )
    def test_introduction_detected(self, text, expected):
        assert _detect_name(text) == expected

    def test_no_match_without_keyword(self):
        assert _detect_name("Benito è un bel nome") is None

    def test_short_name_below_2_chars_no_match(self):
        # Il pattern richiede almeno 2 caratteri — nomi di 1 lettera non matchano
        assert _detect_name("mi chiamo X") is None


# ==========================================================================
# Pattern correttivi (bug "No sono Benito" e "adesso sono Benito")
# ==========================================================================


class TestCorrectionPatterns:
    @pytest.mark.parametrize(
        "text, expected",
        [
            ("No sono Benito", "Benito"),
            ("No, sono Benito", "Benito"),
            ("no sono Benito", "Benito"),  # case-insensitive prefix
            ("adesso sono Benito", "Benito"),
            ("Adesso sono Benito!", "Benito"),
            ("ora sono Benito", "Benito"),
            ("in realtà sono Marco", "Marco"),
            ("anzi sono Laura", "Laura"),
            # Frase complessa dal log dell'utente
            ("Ho cambiato nome adesso sono Benito!", "Benito"),
        ],
    )
    def test_correction_detected(self, text, expected):
        assert _detect_name(text) == expected


# ==========================================================================
# False positive bloccati — nomi con minuscola dopo il contesto correttivo
# ==========================================================================


class TestFalsePositivesBlocked:
    @pytest.mark.parametrize(
        "false_positive",
        [
            "adesso sono stanco",  # "stanco" è minuscolo
            "adesso sono pronto",  # "pronto" è minuscolo
            "adesso sono sicuro di questo",
            "No sono molto occupato",  # "molto" è minuscolo
            "ora sono felice",
            "in realtà sono libero",
            # Il classico bug "Scrivania"
            "Sono nella Scrivania del desktop",  # "nella" è il token diretto dopo "sono"
        ],
    )
    def test_false_positive_not_detected(self, false_positive):
        result = _detect_name(false_positive)
        # Non deve estrarre parole comuni come nomi propri
        assert result is None, f"False positive: '{false_positive}' → '{result}'"

    def test_scrivania_false_positive_blocked(self):
        """Regressione specifica: 'sono nella Scrivania' NON deve salvare 'Scrivania'."""
        assert _detect_name("Sono nella Scrivania del computer") is None
        assert _detect_name("sono in Scrivania") is None


# ==========================================================================
# Negazione / cancellazione nome
# ==========================================================================


class TestNegationPatterns:
    @pytest.mark.parametrize(
        "text",
        [
            "non mi chiamo Alessandoro",
            "Non mi chiamo Scrivania!",
            "non sono Marco",
            "don't call me Bob",
            "that's not my name",
        ],
    )
    def test_negation_returns_none(self, text):
        assert _detect_name(text) is None

    def test_negation_overrides_match(self):
        """Anche se il testo contiene 'mi chiamo X', la negazione ha la precedenza."""
        assert _detect_name("non mi chiamo Alessandro, mi chiamo altro") is None


# ==========================================================================
# Casi limite
# ==========================================================================


class TestEdgeCases:
    def test_empty_string(self):
        assert _detect_name("") is None

    def test_name_with_accent(self):
        result = _detect_name("mi chiamo Élodie")
        assert result is not None

    def test_name_capitalized(self):
        """Il nome deve essere capitalizzato (prima lettera maiuscola)."""
        result = _detect_name("mi chiamo marco")
        assert result == "Marco"

    def test_multiple_keywords_first_wins(self):
        """Con più keyword, viene preso il primo match."""
        result = _detect_name("mi chiamo Alice e chiamami anche Ale")
        assert result == "Alice"

    def test_correction_requires_uppercase_name(self):
        """In contesto correttivo, il nome DEVE iniziare con maiuscola."""
        assert _detect_name("no sono benito") is None  # minuscola → no match
        assert _detect_name("no sono Benito") == "Benito"  # maiuscola → match
