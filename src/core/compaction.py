"""
Structured conversation compaction for Argos.

When micro-compaction is insufficient (token budget > 90%), this module calls
the LLM to produce a structured 9-section summary of the full conversation.
The summary replaces the history so the agent continues with full context.

The <analysis> scratchpad block lets the LLM reason before writing the summary;
it is stripped from the output before the result enters history.

Inspired by Claude Code's compact.ts / prompt.ts.
"""

import logging
import re
from typing import Callable

logger = logging.getLogger("argos")

# Strips the <analysis>...</analysis> reasoning scratchpad from the LLM output.
_ANALYSIS_RE = re.compile(r"<analysis>.*?</analysis>", re.DOTALL)

# Minimum number of messages in history (including system) to bother compacting.
# Below this threshold compaction is not worth the LLM call.
COMPACT_MIN_MESSAGES = 5

COMPACT_PROMPT = """\
Your task is to create a detailed summary of the conversation so far.
This summary will replace the conversation history — the agent continues from it.
Capture technical details, file paths, code snippets, tool results, and decisions.

CRITICAL: Respond with TEXT ONLY. Do NOT call any tools.

Before writing the final summary, use <analysis> tags as a private scratchpad \
(these tags will be stripped and never appear in context):

<analysis>
[Think through each section. Check all files/tools/errors are covered. Verify nothing critical is missing.]
</analysis>

Then write the summary in exactly this format:

<summary>
1. Primary Request and Intent:
   [The user's explicit requests and goals in full detail]

2. Key Technical Concepts:
   - [Concept / technology / framework]

3. Files and Code Sections:
   - [path/to/file]: [what was read/modified + key snippet if applicable]

4. Tool Results and Actions:
   - [tool_name]: [key result or outcome]

5. Errors and Fixes:
   - [Error description]: [how it was fixed]

6. User Messages (verbatim):
   - "[Exact user message text]"

7. Pending Tasks:
   - [Task not yet completed]

8. Current Work:
   [Precise description of what was being worked on immediately before compaction — \
include file names and code context]

9. Next Step:
   [The single most important next action, directly aligned with the user's last request]
</summary>
"""


def compact_conversation(
    history: list[dict],
    llm_call_fn: Callable[[list[dict]], str],
) -> list[dict]:
    """
    Summarises `history` into a structured compact summary using the LLM.

    Returns a new history of 3 messages: [system_msg, summary_user_msg, ack_assistant_msg].
    Falls back to the original history unchanged if compaction fails for any reason.

    Args:
        history:      Full conversation history (history[0] must be the system message).
        llm_call_fn:  Callable accepting messages list, returning the LLM response string.
    """
    if len(history) < COMPACT_MIN_MESSAGES:
        return history

    system_msg = history[0]

    try:
        messages_to_summarize = history + [
            {"role": "user", "content": COMPACT_PROMPT}
        ]
        raw = llm_call_fn(messages_to_summarize)

        if not raw or raw.startswith(
            ("API Error", "Connection Error", "LLM Error", "Error:")
        ):
            logger.warning(
                f"[Compact] LLM returned an error — keeping original history. Response: {raw[:80]}"
            )
            return history

        # Strip the <analysis> scratchpad block
        summary = _ANALYSIS_RE.sub("", raw).strip()

        # Also strip the outer <summary> tags if the model included them
        summary = re.sub(r"^<summary>\s*", "", summary)
        summary = re.sub(r"\s*</summary>\s*$", "", summary)
        summary = summary.strip()

        if not summary:
            logger.warning("[Compact] Empty summary after stripping tags — keeping original")
            return history

        logger.info(
            f"[Compact] Compacted {len(history)} messages → 3 "
            f"(summary: {len(summary)} chars)"
        )
        return [
            system_msg,
            {
                "role": "user",
                "content": (
                    "[CONVERSATION SUMMARY — context was compacted to save tokens]\n\n"
                    + summary
                ),
            },
            {
                "role": "assistant",
                "content": "Summary received. Continuing from where we left off.",
            },
        ]

    except Exception as e:
        logger.warning(f"[Compact] Compaction failed ({e}) — keeping original history")
        return history
