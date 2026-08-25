from __future__ import annotations

from storage_ai.config_discovery import (
    discover_config,
    find_candidate_config_files,
    find_storage_path_candidates,
    parse_config_file,
)

_MONGOD_CONF = """
storage:
  dbPath: /var/lib/mongodb
systemLog:
  destination: file
  path: /var/log/mongodb/mongod.log
net:
  port: 27017
"""

_POSTGRESQL_CONF = """
# PostgreSQL configuration file
data_directory = '/var/lib/postgresql/14/main'
max_connections = 100
"""

_JSON_CONF = """
{"app": {"storagePath": "/srv/appdata", "port": 8080}}
"""

_TOML_CONF = """
[storage]
path = "/opt/myapp/data"
"""


def test_discovers_mongodb_style_yaml_config(tmp_path):
    etc = tmp_path / "etc"
    (etc / "mongod").mkdir(parents=True)
    (etc / "mongod" / "mongod.yaml").write_text(_MONGOD_CONF)

    [discovered] = discover_config("mongod", etc_root=str(etc))

    assert discovered.format == "yaml"
    values = {c.key_path: c.value for c in discovered.candidates}
    assert values["storage.dbPath"] == "/var/lib/mongodb"
    assert values["systemLog.path"] == "/var/log/mongodb/mongod.log"


def test_discovers_postgresql_style_flat_conf(tmp_path):
    etc = tmp_path / "etc"
    etc.mkdir()
    (etc / "postgresql.conf").write_text(_POSTGRESQL_CONF)

    [discovered] = discover_config("postgresql", etc_root=str(etc))

    assert discovered.format == "ini"
    [candidate] = discovered.candidates
    assert candidate.key_path == "ROOT.data_directory"
    assert candidate.value == "/var/lib/postgresql/14/main"  # quotes stripped


def test_json_config_is_parsed_and_matched(tmp_path):
    etc = tmp_path / "etc"
    etc.mkdir()
    (etc / "myapp.json").write_text(_JSON_CONF)

    [discovered] = discover_config("myapp", etc_root=str(etc))

    assert discovered.format == "json"
    [candidate] = discovered.candidates
    assert candidate.key_path == "app.storagePath"
    assert candidate.value == "/srv/appdata"


def test_toml_config_is_parsed_and_matched(tmp_path):
    etc = tmp_path / "etc"
    etc.mkdir()
    (etc / "myapp.toml").write_text(_TOML_CONF)

    [discovered] = discover_config("myapp", etc_root=str(etc))

    assert discovered.format == "toml"
    [candidate] = discovered.candidates
    assert candidate.key_path == "storage.path"
    assert candidate.value == "/opt/myapp/data"


def test_existing_path_scores_higher_confidence_than_nonexistent(tmp_path):
    real_dir = tmp_path / "real_data"
    real_dir.mkdir()
    config = {"storage": {"dbPath": str(real_dir), "backupPath": "/definitely/not/real/xyz"}}

    candidates = find_storage_path_candidates(config)

    by_key = {c.key_path: c for c in candidates}
    assert by_key["storage.dbPath"].exists_on_disk is True
    assert by_key["storage.backupPath"].exists_on_disk is False
    assert by_key["storage.dbPath"].confidence > by_key["storage.backupPath"].confidence


def test_non_path_keys_are_not_matched():
    config = {"port": "8080", "hostname": "localhost", "storage": {"dbPath": "/var/lib/x"}}

    candidates = find_storage_path_candidates(config)

    assert [c.key_path for c in candidates] == ["storage.dbPath"]


def test_relative_looking_values_are_not_treated_as_paths():
    config = {"storagePath": "relative/not/absolute"}

    candidates = find_storage_path_candidates(config)

    assert candidates == []


def test_find_candidate_config_files_only_returns_existing_files(tmp_path):
    etc = tmp_path / "etc"
    etc.mkdir()
    (etc / "realapp.conf").write_text("data_directory = /var/lib/realapp\n")

    found = find_candidate_config_files("realapp", etc_root=str(etc))
    not_found = find_candidate_config_files("nonexistent_app_xyz", etc_root=str(etc))

    assert found == [str(etc / "realapp.conf")]
    assert not_found == []


def test_home_config_dir_is_also_checked(tmp_path):
    home = tmp_path / "home"
    (home / ".config" / "myapp").mkdir(parents=True)
    (home / ".config" / "myapp" / "config.yaml").write_text("dataDir: /home/user/myapp-data\n")

    etc = tmp_path / "etc"
    etc.mkdir()

    [discovered] = discover_config("myapp", home=str(home), etc_root=str(etc))

    assert discovered.candidates[0].value == "/home/user/myapp-data"


def test_apps_with_no_config_present_yield_nothing(tmp_path):
    etc = tmp_path / "etc"
    etc.mkdir()

    assert discover_config("totally_unknown_app", home=str(tmp_path / "home"), etc_root=str(etc)) == []


def test_malformed_config_file_does_not_raise(tmp_path):
    etc = tmp_path / "etc"
    etc.mkdir()
    (etc / "broken.json").write_text("{not valid json!!!")

    assert parse_config_file(str(etc / "broken.json")) is None
    assert discover_config("broken", etc_root=str(etc)) == []
