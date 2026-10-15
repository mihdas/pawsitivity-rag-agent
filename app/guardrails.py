"""Guardrails that run before and after the LLM.

Layered on purpose. Each layer is cheap and catches a different failure:
  1. input_check   - length, blocked terms, prompt-injection patterns (no LLM call)
  2. topic_check   - LLM classifier: IN_SCOPE / SMALLTALK / OUT_OF_SCOPE   (in graph.py)
  3. relevance     - retrieval score threshold, no relevant chunk -> no answer (in graph.py)
  4. grounding     - answer prompt only allows CONTEXT, NO_ANSWER token       (prompts.py)
  5. output_check  - never leak the system prompt or the context markup
"""

import re
from dataclasses import dataclass

from app.config import GuardrailConfig


@dataclass
class CheckResult:
    ok: bool
    reason: str = ""


def input_check(message: str, cfg: GuardrailConfig, max_chars: int) -> CheckResult:
    text = message.strip()
    if not text:
        return CheckResult(False, "empty")
    if len(text) > max_chars:
        return CheckResult(False, "too_long")
    lowered = text.lower()
    for term in cfg.blocked_terms:
        if term.lower() in lowered:
            return CheckResult(False, "blocked_term")
    for pattern in cfg.injection_patterns:
        if re.search(pattern, text, flags=re.IGNORECASE):
            return CheckResult(False, "prompt_injection")
    return CheckResult(True)


LEAK_MARKERS = (
    "Answer ONLY with information from the CONTEXT",
    "strict topic classifier",
    "Reply with the label only",
    "<source ",
)


def output_check(answer: str) -> CheckResult:
    lowered = answer.lower()
    for marker in LEAK_MARKERS:
        if marker.lower() in lowered:
            return CheckResult(False, "possible_prompt_leak")
    return CheckResult(True)


def parse_topic_label(raw: str) -> str:
    """Map the classifier output to a label. Anything unclear counts as OUT_OF_SCOPE (fail closed)."""
    upper = raw.strip().upper()
    for label in ("OUT_OF_SCOPE", "IN_SCOPE", "SMALLTALK"):
        if label in upper:
            return label
    return "OUT_OF_SCOPE"
