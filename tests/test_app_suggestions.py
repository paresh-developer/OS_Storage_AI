"""Tests app_suggestions.py's batch-discovery orchestration logic --
mocks the underlying tiers (already tested on their own in
test_app_discovery.py, test_process_introspection.py, etc.) to isolate
this module's own responsibilities: which process names get asked about,
which findings are actually worth surfacing, and cooperative
cancellation."""

from __future__ import annotations

import pytest

from storage_ai import app_discovery, app_suggestions, category_advisor, path_classifier, process_introspection
from storage_ai.exceptions import ScanCancelled
from storage_ai.path_classifier import PathClassification


def test_skips_process_names_with_no_discovery_findings(monkeypatch):
    monkeypatch.setattr(process_introspection, "list_running_process_names", lambda: ["myapp"])
    monkeypatch.setattr(app_discovery, "discover_app_storage_paths", lambda name, **kwargs: [])

    suggestions = app_suggestions.discover_running_app_suggestions()

    assert suggestions == []


def test_skips_findings_with_no_advice(monkeypatch):
    monkeypatch.setattr(process_introspection, "list_running_process_names", lambda: ["myapp"])
    monkeypatch.setattr(
        app_discovery,
        "discover_app_storage_paths",
        lambda name, **kwargs: [app_discovery.StoragePathFinding(path="/tmp/x", confidence=0.9, source="config_file", detail="d")],
    )
    monkeypatch.setattr(path_classifier, "classify_path", lambda path: PathClassification(category="other", known_service=None))
    monkeypatch.setattr(category_advisor, "advice_for", lambda category, service: None)

    suggestions = app_suggestions.discover_running_app_suggestions()

    assert suggestions == []


def test_includes_findings_with_advice(monkeypatch):
    monkeypatch.setattr(process_introspection, "list_running_process_names", lambda: ["mongod"])
    monkeypatch.setattr(
        app_discovery,
        "discover_app_storage_paths",
        lambda name, **kwargs: [app_discovery.StoragePathFinding(path="/var/lib/mongodb", confidence=0.95, source="process_cmdline_flag", detail="--dbpath")],
    )
    monkeypatch.setattr(
        path_classifier, "classify_path", lambda path: PathClassification(category="application_data", known_service="MongoDB")
    )
    monkeypatch.setattr(category_advisor, "advice_for", lambda category, service: "Consider log rotation.")

    suggestions = app_suggestions.discover_running_app_suggestions()

    assert len(suggestions) == 1
    assert suggestions[0].app_name == "mongod"
    assert suggestions[0].path == "/var/lib/mongodb"
    assert suggestions[0].known_service == "MongoDB"
    assert suggestions[0].advice == "Consider log rotation."


def test_sorts_by_confidence_descending(monkeypatch):
    monkeypatch.setattr(process_introspection, "list_running_process_names", lambda: ["low", "high"])

    def fake_discover(name, **kwargs):
        confidence = 0.3 if name == "low" else 0.9
        return [app_discovery.StoragePathFinding(path=f"/data/{name}", confidence=confidence, source="config_file", detail="d")]

    monkeypatch.setattr(app_discovery, "discover_app_storage_paths", fake_discover)
    monkeypatch.setattr(path_classifier, "classify_path", lambda path: PathClassification(category="log", known_service=None))
    monkeypatch.setattr(category_advisor, "advice_for", lambda category, service: "Rotate logs.")

    suggestions = app_suggestions.discover_running_app_suggestions()

    assert [s.app_name for s in suggestions] == ["high", "low"]


def test_universal_noise_process_names_are_never_even_checked(monkeypatch):
    monkeypatch.setattr(process_introspection, "list_running_process_names", lambda: ["bash", "systemd", "myrealapp"])
    checked = []
    monkeypatch.setattr(app_discovery, "discover_app_storage_paths", lambda name, **kwargs: checked.append(name) or [])

    app_suggestions.discover_running_app_suggestions()

    assert checked == ["myrealapp"]


def test_reports_progress_for_each_app_checked(monkeypatch):
    monkeypatch.setattr(process_introspection, "list_running_process_names", lambda: ["appone", "apptwo"])
    monkeypatch.setattr(app_discovery, "discover_app_storage_paths", lambda name, **kwargs: [])

    updates = []
    app_suggestions.discover_running_app_suggestions(on_progress=updates.append)

    assert len(updates) == 2
    assert updates[0].fraction == pytest.approx(0.5)
    assert updates[1].fraction == pytest.approx(1.0)


def test_cancellation_raises_scan_cancelled(monkeypatch):
    monkeypatch.setattr(process_introspection, "list_running_process_names", lambda: ["appone", "apptwo"])
    monkeypatch.setattr(app_discovery, "discover_app_storage_paths", lambda name, **kwargs: [])

    with pytest.raises(ScanCancelled):
        app_suggestions.discover_running_app_suggestions(cancel_check=lambda: True)


def test_real_running_process_end_to_end(monkeypatch):
    """No mocking of app_discovery/process_introspection -- just disables
    the optional LLM tier so this stays fast and dependency-free, then
    runs the real batch discovery against whatever's actually running on
    this machine. Only asserts it completes without error and returns a
    list -- what's actually running varies by machine, so nothing
    specific can be asserted about the contents."""
    suggestions = app_suggestions.discover_running_app_suggestions(try_llm_fallback=False)

    assert isinstance(suggestions, list)
    assert all(s.advice for s in suggestions)


def test_path_size_bytes_for_a_real_file(tmp_path):
    f = tmp_path / "data.bin"
    f.write_bytes(b"x" * 12345)

    assert app_suggestions.path_size_bytes(str(f)) == 12345


def test_path_size_bytes_sums_nested_directory_contents(tmp_path):
    (tmp_path / "sub").mkdir()
    (tmp_path / "a.log").write_bytes(b"1" * 100)
    (tmp_path / "sub" / "b.log").write_bytes(b"2" * 250)

    assert app_suggestions.path_size_bytes(str(tmp_path)) == 350


def test_path_size_bytes_returns_zero_for_a_nonexistent_path():
    assert app_suggestions.path_size_bytes("/this/path/does/not/exist/anywhere") == 0


def test_severity_for_size_thresholds():
    assert app_suggestions.severity_for_size(0) == app_suggestions.SEVERITY_NORMAL
    assert app_suggestions.severity_for_size(app_suggestions.LARGE_SIZE_BYTES - 1) == app_suggestions.SEVERITY_NORMAL
    assert app_suggestions.severity_for_size(app_suggestions.LARGE_SIZE_BYTES) == app_suggestions.SEVERITY_LARGE
    assert app_suggestions.severity_for_size(app_suggestions.CRITICAL_SIZE_BYTES - 1) == app_suggestions.SEVERITY_LARGE
    assert app_suggestions.severity_for_size(app_suggestions.CRITICAL_SIZE_BYTES) == app_suggestions.SEVERITY_CRITICAL


def test_suggestion_reports_real_size_and_flags_it_as_large(monkeypatch, tmp_path):
    """End-to-end: a real directory on disk, discovered via mocked
    process_introspection/app_discovery (those tiers are tested on their
    own elsewhere), but the size walk and severity classification below
    that point are entirely real -- this is the exact mechanism a 1 TB
    MongoDB data directory would go through, just with the LARGE/CRITICAL
    thresholds lowered so a small real directory can cross them in a test
    without writing gigabytes of test data."""
    (tmp_path / "big.log").write_bytes(b"x" * 2000)
    monkeypatch.setattr(app_suggestions, "LARGE_SIZE_BYTES", 1000)
    monkeypatch.setattr(app_suggestions, "CRITICAL_SIZE_BYTES", 10_000)

    monkeypatch.setattr(process_introspection, "list_running_process_names", lambda: ["mongod"])
    monkeypatch.setattr(
        app_discovery,
        "discover_app_storage_paths",
        lambda name, **kwargs: [app_discovery.StoragePathFinding(path=str(tmp_path), confidence=0.95, source="process_cmdline_flag", detail="--dbpath")],
    )
    monkeypatch.setattr(
        path_classifier, "classify_path", lambda path: PathClassification(category="application_data", known_service="MongoDB")
    )
    monkeypatch.setattr(category_advisor, "advice_for", lambda category, service: "Consider log rotation.")

    suggestions = app_suggestions.discover_running_app_suggestions()

    assert len(suggestions) == 1
    assert suggestions[0].size_bytes == 2000
    assert suggestions[0].severity == app_suggestions.SEVERITY_LARGE


def test_sort_prioritizes_severity_over_confidence(monkeypatch, tmp_path):
    big_dir = tmp_path / "big"
    big_dir.mkdir()
    (big_dir / "f.log").write_bytes(b"x" * 5000)

    monkeypatch.setattr(app_suggestions, "LARGE_SIZE_BYTES", 1000)
    monkeypatch.setattr(app_suggestions, "CRITICAL_SIZE_BYTES", 3000)
    monkeypatch.setattr(process_introspection, "list_running_process_names", lambda: ["lowconf_critical", "highconf_normal"])

    def fake_discover(name, **kwargs):
        if name == "lowconf_critical":
            return [app_discovery.StoragePathFinding(path=str(big_dir), confidence=0.2, source="config_file", detail="d")]
        return [app_discovery.StoragePathFinding(path="/does/not/exist", confidence=0.95, source="config_file", detail="d")]

    monkeypatch.setattr(app_discovery, "discover_app_storage_paths", fake_discover)
    monkeypatch.setattr(path_classifier, "classify_path", lambda path: PathClassification(category="log", known_service=None))
    monkeypatch.setattr(category_advisor, "advice_for", lambda category, service: "Rotate logs.")

    suggestions = app_suggestions.discover_running_app_suggestions()

    assert [s.app_name for s in suggestions] == ["lowconf_critical", "highconf_normal"]
