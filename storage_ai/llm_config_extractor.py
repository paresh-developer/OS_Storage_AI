"""Optional, CPU-only extractive-QA fallback for finding a storage-path
setting in a config file's raw text -- for the case where the file didn't
parse as any of config_discovery.py's supported structured formats (JSON/
YAML/TOML/INI): an unusual/exotic format, a genuinely freeform text
config, or a file this project's parser just doesn't understand yet.

This is deliberately the LAST tier tried (see app_discovery.py), not the
first: it needs `torch` + `transformers` installed (~1GB combined, an
*optional* dependency -- see requirements-llm.txt, not a core requirement
of this app), it's slower (seconds, not milliseconds), and it is
meaningfully less reliable than either process introspection or structured
config parsing.

It's an extractive question-answering model (DistilBERT fine-tuned on
SQuAD), not a generative one -- deliberately: "find the span of text in
this document that answers the question" is a narrower, safer task for a
small model than "write me the answer," and it can only ever return text
that actually appears in the input, never fabricate a path from nothing.

Two real failure modes were found and worked around while building this
(not hypothetical -- reproduced in tests/test_llm_config_extractor.py):

1. **Question phrasing matters far more than expected for a model this
   small.** The exact same text answered with the exact same model swings
   from a correct, confident extraction to a wrong one depending on
   whether the question happens to lexically overlap with the config's own
   terminology (e.g. "What is the data directory?" works well against a
   `data_directory` key; a more generic phrasing does not, on the same
   line). There is no single phrasing that reliably works, so this asks
   several genuinely different questions and keeps the best result --
   not one fixed prompt.
2. **The model's answer span often includes more than just the value**
   (e.g. the whole "dbPath = /mnt/data" line, or just the bare key name
   with no value at all) rather than cleanly bounding the path itself. A
   regex pulls the actual path-shaped substring out of whatever span the
   model returns, which recovers a correct answer even from an imprecise
   span -- and finding no such substring in *any* attempted question is
   itself a hard rejection signal, independent of confidence.
3. **Confidence alone is not trustworthy.** This model was trained on
   SQuAD 1.1, which has no "unanswerable" examples -- fed a config with no
   path in it at all, at least one question phrasing confidently (0.47,
   comfortably above a naive threshold) pointed at unrelated text as if it
   were the answer. The regex path-shape extraction is what actually
   catches this (no path-shaped substring exists in the nonsense span),
   not the score. This module leans on that classical, deterministic check
   to keep the model honest, consistent with how every other ML component
   in this app is used (see unused.py's heuristic fallback, or
   category_advisor.py never auto-editing a config it merely read).

Uses the model directly via AutoModelForQuestionAnswering rather than
transformers' pipeline() convenience wrapper -- as of the transformers
version this was built against, the classic single-span
"question-answering" pipeline task was no longer registered under that
name (a real, verified change encountered while building this, not a
design preference).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache

MODEL_NAME = "distilbert-base-cased-distilled-squad"

# Deliberately varied phrasings, not near-duplicates -- see the module
# docstring's finding #1. Covers the vocabulary real config keys tend to
# use ("path", "directory", "storage", "data") in different combinations
# so at least one is likely to lexically overlap with whatever a given
# config actually calls its setting.
DEFAULT_QUESTIONS = [
    "What is the path?",
    "What is the storage directory?",
    "What is the data directory?",
    "Where is data stored?",
]

# A path-shaped substring: a slash followed by at least 3 more
# non-whitespace, non-quote characters -- long enough to exclude a bare
# "/" or a truncated one-character fragment.
_PATH_SUBSTRING_RE = re.compile(r"/[^\s'\"]{3,}")

# Calibrated against the false-positive described above (0.47, wrong) and
# the correct extractions (0.4-0.6) -- there's no threshold that cleanly
# separates them on confidence alone, which is exactly why the path-shape
# extraction exists as a second, mandatory gate rather than a nice-to-have.
MIN_CONFIDENCE = 0.4


class LLMUnavailable(Exception):
    """Raised when `transformers`/`torch` aren't installed. These are an
    optional dependency -- install with `pip install -r requirements-llm.txt`.
    Never silently degrade to a different behavior; callers should catch
    this and skip the LLM tier entirely, the same as any other optional
    capability in this app."""


@dataclass
class LLMExtractionResult:
    path: str
    confidence: float
    question: str  # which phrasing produced this result, for transparency


def is_available() -> bool:
    try:
        import torch  # noqa: F401
        import transformers  # noqa: F401
    except ImportError:
        return False
    return True


@lru_cache(maxsize=1)
def _load_model():
    """Loaded once per process and cached -- this is the expensive part
    (reading ~260MB of weights from disk), not something to redo per call."""
    try:
        from transformers import AutoModelForQuestionAnswering, AutoTokenizer
    except ImportError as exc:
        raise LLMUnavailable(
            "transformers/torch aren't installed -- this is an optional dependency: "
            "pip install -r requirements-llm.txt"
        ) from exc
    tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME)
    model = AutoModelForQuestionAnswering.from_pretrained(MODEL_NAME)
    model.eval()
    return tokenizer, model


def _ask_one(tokenizer, model, question: str, context: str):
    import torch

    encoded = tokenizer(
        question,
        context,
        return_tensors="pt",
        return_offsets_mapping=True,
        truncation=True,
        max_length=512,
    )
    offsets = encoded.pop("offset_mapping")[0]
    sequence_ids = encoded.sequence_ids(0)

    with torch.no_grad():
        outputs = model(**encoded)

    # Only tokens belonging to the context (sequence_id == 1) are eligible
    # answers -- without this, the model can "answer" using the question's
    # own tokens, which is never a meaningful result.
    context_mask = torch.tensor([sid != 1 for sid in sequence_ids])
    start_logits = outputs.start_logits[0].masked_fill(context_mask, -1e9)
    end_logits = outputs.end_logits[0].masked_fill(context_mask, -1e9)

    start = start_logits.argmax().item()
    end = end_logits.argmax().item()
    if end < start:
        return None, 0.0

    confidence = (
        torch.softmax(start_logits, dim=-1)[start].item() * torch.softmax(end_logits, dim=-1)[end].item()
    )
    char_start, char_end = offsets[start][0].item(), offsets[end][1].item()
    if char_start == char_end:
        return None, confidence
    return context[char_start:char_end], confidence


def extract_storage_path(
    config_text: str,
    questions: list[str] | None = None,
    min_confidence: float = MIN_CONFIDENCE,
) -> LLMExtractionResult | None:
    """Tries each question in `questions` (default: DEFAULT_QUESTIONS) and
    returns the highest-confidence result whose answer span contains an
    actual path-shaped substring -- or None if none of them do, or the
    best one still falls below `min_confidence`. Raises LLMUnavailable if
    the optional dependency isn't installed; callers should catch that and
    skip this tier."""
    if not is_available():
        raise LLMUnavailable(
            "transformers/torch aren't installed -- this is an optional dependency: "
            "pip install -r requirements-llm.txt"
        )

    tokenizer, model = _load_model()
    questions = DEFAULT_QUESTIONS if questions is None else questions

    best: LLMExtractionResult | None = None
    for question in questions:
        span, confidence = _ask_one(tokenizer, model, question, config_text)
        if not span:
            continue
        match = _PATH_SUBSTRING_RE.search(span)
        if not match:
            continue
        path = match.group(0).rstrip(".,;:'\"")
        if best is None or confidence > best.confidence:
            best = LLMExtractionResult(path=path, confidence=confidence, question=question)

    if best is None or best.confidence < min_confidence:
        return None
    return best
