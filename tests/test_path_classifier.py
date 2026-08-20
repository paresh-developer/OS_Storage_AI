from storage_ai.path_classifier import (
    CATEGORY_APPLICATION_DATA,
    CATEGORY_CACHE,
    CATEGORY_LOG,
    CATEGORY_OTHER,
    CATEGORY_SYSTEM,
    CATEGORY_TRASH,
    CATEGORY_USER_DATA,
    classify_path,
)

LINUX_HOME = "/home/alice"
WINDOWS_HOME = r"C:\Users\alice"


def _linux(path):
    return classify_path(path, is_windows=False, home=LINUX_HOME)


def _windows(path):
    return classify_path(path, is_windows=True, home=WINDOWS_HOME)


def test_linux_known_service_data_dirs_are_labeled_and_protected():
    result = _linux("/var/lib/postgresql/14/main/base/16384/12345")
    assert result.category == CATEGORY_APPLICATION_DATA
    assert result.known_service == "PostgreSQL"
    assert result.protected is True


def test_linux_mongodb_and_mysql_are_recognized():
    assert _linux("/var/lib/mongodb/collection-0.wt").known_service == "MongoDB"
    assert _linux("/var/lib/mysql/ibdata1").known_service == "MySQL"


def test_linux_var_log_is_log_category_and_not_protected():
    result = _linux("/var/log/postgresql/postgresql-14-main.log")
    assert result.category == CATEGORY_LOG
    assert result.protected is False


def test_real_tmp_directory_is_cache():
    assert _linux("/tmp/some_download.zip").category == CATEGORY_CACHE


def test_a_project_folder_merely_named_tmp_is_not_swept_into_cache():
    # Regression test: a personal or project folder named "tmp"/"temp"
    # elsewhere in the tree is NOT the real system temp directory and must
    # not be misclassified just because a path segment matches that name.
    result = _linux("/home/alice/myproject/tmp/build-output.bin")
    assert result.category != CATEGORY_CACHE
    result = _linux("/home/alice/scratch/temp/notes.txt")
    assert result.category != CATEGORY_CACHE


def test_linux_system_dirs_are_protected():
    for path in ("/usr/bin/python3", "/boot/vmlinuz", "/lib/systemd/systemd", "/sbin/init"):
        result = _linux(path)
        assert result.category == CATEGORY_SYSTEM, path
        assert result.protected is True


def test_lib_does_not_falsely_match_lib64():
    # "/lib" must not swallow "/lib64" via naive string prefixing.
    result = _linux("/lib64/ld-linux-x86-64.so.2")
    assert result.category == CATEGORY_SYSTEM


def test_extension_based_log_detection_works_anywhere():
    result = _linux("/home/alice/myapp/debug.log")
    assert result.category == CATEGORY_LOG
    assert result.known_service is None


def test_name_based_cache_detection():
    result = _linux("/home/alice/.cache/pip/http/abc123")
    assert result.category == CATEGORY_CACHE


def test_name_based_trash_detection():
    result = _linux("/home/alice/.local/share/Trash/files/old.txt")
    assert result.category == CATEGORY_TRASH


def test_home_directory_files_default_to_user_data():
    result = _linux("/home/alice/Documents/resume.pdf")
    assert result.category == CATEGORY_USER_DATA
    assert result.protected is False


def test_unmatched_outside_home_falls_back_to_other():
    result = _linux("/mnt/external-drive/random/file.bin")
    assert result.category == CATEGORY_OTHER


def test_windows_known_service_dirs():
    result = _windows(r"C:\Program Files\PostgreSQL\16\data\base\1")
    assert result.category == CATEGORY_APPLICATION_DATA
    assert result.known_service == "PostgreSQL"
    assert result.protected is True


def test_windows_system_and_recycle_bin():
    assert _windows(r"C:\Windows\System32\drivers\etc\hosts").category == CATEGORY_SYSTEM
    assert _windows(r"C:\$Recycle.Bin\S-1-5-21\file.txt").category == CATEGORY_TRASH


def test_windows_matching_is_case_insensitive():
    result = _windows(r"c:\program files\mongodb\server\7.0\data\file.wt")
    assert result.known_service == "MongoDB"


def test_windows_home_directory_defaults_to_user_data():
    result = _windows(r"C:\Users\alice\Pictures\photo.jpg")
    assert result.category == CATEGORY_USER_DATA
