"""Tests against the real model (not mocked) -- this is a small, genuinely
local, CPU-only model, and the whole point of this module is its actual
extraction behavior, including its real failure modes. The first test in
this file pays the one-time model-load cost; @lru_cache keeps it loaded for
the rest of the process, so subsequent tests are fast.

Every test here documents something actually observed while building this
module, not a hypothetical -- see llm_config_extractor.py's docstring and
docs/METHODOLOGY.md for the same findings written up for a reader."""

from __future__ import annotations

import pytest

from storage_ai import llm_config_extractor
from storage_ai.llm_config_extractor import LLMUnavailable, extract_storage_path, is_available

pytestmark = pytest.mark.skipif(not is_available(), reason="transformers/torch not installed (optional dependency)")


def test_is_available_reflects_real_installation_state():
    assert is_available() is True


def test_extracts_correct_path_from_mongodb_style_line():
    result = extract_storage_path("dbPath = /mnt/company-data/mongo-storage")

    assert result is not None
    assert result.path == "/mnt/company-data/mongo-storage"
    assert result.confidence >= llm_config_extractor.MIN_CONFIDENCE


def test_extracts_correct_path_from_postgresql_style_line():
    result = extract_storage_path("data_directory = /var/lib/postgresql/14/main")

    assert result is not None
    assert result.path == "/var/lib/postgresql/14/main"


def test_extracts_correct_path_from_generic_yaml_style_line():
    result = extract_storage_path("storagePath: /srv/appdata/storage")

    assert result is not None
    assert result.path == "/srv/appdata/storage"


def test_rejects_the_verified_hallucination_case():
    """Regression test for a real finding, not a hypothetical: this model
    was trained on SQuAD 1.1 (no "unanswerable" examples), and fed a config
    with no storage path in it at all, at least one question phrasing
    confidently (0.47 -- above this module's own 0.4 floor) pointed at
    unrelated text as if it were the answer. The mandatory path-substring
    extraction is what actually catches this, not the confidence score:
    none of the model's answer spans for this input contain anything
    path-shaped."""
    result = extract_storage_path("port: 8080\nhost: localhost\ntimeout: 30")

    assert result is None


def test_explicit_zero_min_confidence_still_requires_path_shape():
    """Even with no confidence floor at all, an answer with no path-shaped
    substring anywhere in it must still be rejected -- the shape check is
    not optional or bypassable via the confidence parameter."""
    result = extract_storage_path("port: 8080\nhost: localhost\ntimeout: 30", min_confidence=0.0)

    assert result is None


def test_result_reports_which_question_produced_it():
    result = extract_storage_path("data_directory = /var/lib/postgresql/14/main")

    assert result is not None
    assert result.question in llm_config_extractor.DEFAULT_QUESTIONS


def test_raises_llm_unavailable_when_dependency_missing(monkeypatch):
    monkeypatch.setattr(llm_config_extractor, "is_available", lambda: False)

    with pytest.raises(LLMUnavailable):
        extract_storage_path("dbPath = /var/lib/x")
