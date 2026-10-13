import os
import stat
import subprocess
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "fetch_db.sh"


def fake_gh(tmp_path, view_exit, view_stderr="", download_exit=0):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    gh = bin_dir / "gh"
    gh.write_text(
        "#!/usr/bin/env bash\n"
        f'if [ "$2" = view ]; then echo "{view_stderr}" >&2; exit {view_exit}; fi\n'
        f'if [ "$2" = download ]; then touch sponsorscope.db; exit {download_exit}; fi\n'
        "exit 99\n"
    )
    gh.chmod(gh.stat().st_mode | stat.S_IEXEC)
    return {**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}"}


def run(tmp_path, env):
    return subprocess.run(["bash", str(SCRIPT)], cwd=tmp_path, env=env, capture_output=True, text=True)


def test_downloads_when_release_exists(tmp_path):
    result = run(tmp_path, fake_gh(tmp_path, view_exit=0))
    assert result.returncode == 0 and (tmp_path / "sponsorscope.db").exists()


def test_starts_fresh_only_when_release_not_found(tmp_path):
    result = run(tmp_path, fake_gh(tmp_path, view_exit=1, view_stderr="release not found"))
    assert result.returncode == 0 and "starting fresh" in result.stdout
    assert not (tmp_path / "sponsorscope.db").exists()


def test_other_errors_fail_instead_of_starting_fresh(tmp_path):
    result = run(tmp_path, fake_gh(tmp_path, view_exit=1, view_stderr="HTTP 502: Bad Gateway"))
    assert result.returncode != 0


def test_failed_download_fails(tmp_path):
    result = run(tmp_path, fake_gh(tmp_path, view_exit=0, download_exit=1))
    assert result.returncode != 0
