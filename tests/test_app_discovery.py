"""Tests the discovery orchestrator's tier precedence: process
introspection > structured config > optional LLM fallback, each tried only
when the previous ones found nothing. Most of these mock the underlying
modules to isolate the *ordering* logic; one test (the real-process case)
exercises a genuine subprocess end to end, since that's cheap and doesn't
need mocking at all."""

from __future__ import annotations

import subprocess
import sys
import time

from storage_ai import app_discovery, config_discovery, process_introspection


def test_prefers_process_tier_over_config_tier(monkeypatch):
    monkeypatch.setattr(
        process_introspection,
        "discover_storage_paths_by_name",
        lambda name: [
            process_introspection.ProcessStorageInfo(
                pid=123,
                process_name=name,
                cmdline=[name, "--datadir", "/from/process"],
                hints=[process_introspection.ProcessPathHint(path="/from/process", confidence="cmdline_flag", detail="--datadir")],
            )
        ],
    )
    monkeypatch.setattr(
        config_discovery,
        "discover_config",
        lambda name, **kwargs: [
            config_discovery.DiscoveredConfig(
                config_path="/etc/x.conf",
                format="ini",
                candidates=[config_discovery.PathCandidate(key_path="x", value="/from/config", exists_on_disk=True, confidence=0.7)],
            )
        ],
    )

    findings = app_discovery.discover_app_storage_paths("myapp")

    assert len(findings) == 1
    assert findings[0].path == "/from/process"
    assert findings[0].source == "process_cmdline_flag"


def test_falls_back_to_config_tier_when_no_process_running(monkeypatch):
    monkeypatch.setattr(process_introspection, "discover_storage_paths_by_name", lambda name: [])
    monkeypatch.setattr(
        config_discovery,
        "discover_config",
        lambda name, **kwargs: [
            config_discovery.DiscoveredConfig(
                config_path="/etc/x.conf",
                format="ini",
                candidates=[config_discovery.PathCandidate(key_path="x", value="/from/config", exists_on_disk=True, confidence=0.7)],
            )
        ],
    )

    findings = app_discovery.discover_app_storage_paths("myapp")

    assert len(findings) == 1
    assert findings[0].path == "/from/config"
    assert findings[0].source == "config_file"


def test_falls_back_to_llm_tier_only_when_nothing_else_found(monkeypatch, tmp_path):
    unparseable = tmp_path / "myapp.conf"
    unparseable.write_text("this is not valid ini, json, yaml, or toml at all !!\ndbPath is /srv/somewhere")

    monkeypatch.setattr(process_introspection, "discover_storage_paths_by_name", lambda name: [])
    monkeypatch.setattr(config_discovery, "discover_config", lambda name, **kwargs: [])
    monkeypatch.setattr(config_discovery, "find_candidate_config_files", lambda name, **kwargs: [str(unparseable)])
    monkeypatch.setattr(config_discovery, "parse_config_file", lambda path: None)

    from storage_ai import llm_config_extractor

    monkeypatch.setattr(llm_config_extractor, "is_available", lambda: True)
    monkeypatch.setattr(
        llm_config_extractor,
        "extract_storage_path",
        lambda text, **kwargs: llm_config_extractor.LLMExtractionResult(path="/srv/somewhere", confidence=0.5, question="What is the path?"),
    )

    findings = app_discovery.discover_app_storage_paths("myapp")

    assert len(findings) == 1
    assert findings[0].path == "/srv/somewhere"
    assert findings[0].source == "llm_extraction"
    assert findings[0].confidence == 0.5 * app_discovery._LLM_CONFIDENCE_DISCOUNT


def test_llm_tier_skipped_when_dependency_unavailable(monkeypatch, tmp_path):
    unparseable = tmp_path / "myapp.conf"
    unparseable.write_text("not structured at all")

    monkeypatch.setattr(process_introspection, "discover_storage_paths_by_name", lambda name: [])
    monkeypatch.setattr(config_discovery, "discover_config", lambda name, **kwargs: [])
    monkeypatch.setattr(config_discovery, "find_candidate_config_files", lambda name, **kwargs: [str(unparseable)])
    monkeypatch.setattr(config_discovery, "parse_config_file", lambda path: None)

    from storage_ai import llm_config_extractor

    monkeypatch.setattr(llm_config_extractor, "is_available", lambda: False)

    findings = app_discovery.discover_app_storage_paths("myapp")

    assert findings == []


def test_llm_tier_not_tried_when_config_parsed_but_had_no_path_candidates(monkeypatch, tmp_path):
    """A config that parses successfully but has no path-shaped setting is
    a confirmed structured answer of "nothing here" -- it must not fall
    through to the LLM tier, which is reserved for configs that failed to
    parse at all."""
    parseable = tmp_path / "myapp.conf"
    parseable.write_text('[section]\nport = 8080\n')

    monkeypatch.setattr(process_introspection, "discover_storage_paths_by_name", lambda name: [])
    monkeypatch.setattr(config_discovery, "discover_config", lambda name, **kwargs: [])
    monkeypatch.setattr(config_discovery, "find_candidate_config_files", lambda name, **kwargs: [str(parseable)])
    # parse_config_file is NOT patched -- it will genuinely parse this INI successfully.

    from storage_ai import llm_config_extractor

    was_called = []
    monkeypatch.setattr(llm_config_extractor, "is_available", lambda: True)
    monkeypatch.setattr(
        llm_config_extractor,
        "extract_storage_path",
        lambda text, **kwargs: was_called.append(text) or None,
    )

    findings = app_discovery.discover_app_storage_paths("myapp")

    assert findings == []
    assert was_called == []  # the LLM was never even asked


def test_real_running_process_is_discovered_end_to_end(tmp_path):
    """No mocking -- a genuine subprocess with a --datadir flag, found via
    the real process_introspection module."""
    script = "import sys, time\nf = open(sys.argv[2] + '/data.db', 'wb'); f.write(b'x'); f.flush()\ntime.sleep(10)\n"
    proc = subprocess.Popen([sys.executable, "-c", script, "--datadir", str(tmp_path)])
    try:
        deadline = time.time() + 5
        while not (tmp_path / "data.db").exists() and time.time() < deadline:
            time.sleep(0.05)

        with open(f"/proc/{proc.pid}/comm") as f:
            real_comm = f.read().strip()

        findings = app_discovery.discover_app_storage_paths(real_comm)

        assert any(f.path == str(tmp_path) for f in findings)
        assert findings[0].source.startswith("process_")
    finally:
        proc.terminate()
        proc.wait(timeout=5)
