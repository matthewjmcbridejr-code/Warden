from pathlib import Path

from warden.webstudio.commands import run_command, run_sequence


def test_run_command_success(tmp_path: Path) -> None:
    result = run_command(["echo", "hello"], cwd=tmp_path, timeout=5)
    assert result.ok
    assert "hello" in result.stdout
    assert result.returncode == 0


def test_run_command_failure(tmp_path: Path) -> None:
    result = run_command(["false"], cwd=tmp_path, timeout=5)
    assert not result.ok
    assert result.returncode != 0
    assert not result.timed_out


def test_run_command_timeout(tmp_path: Path) -> None:
    result = run_command(["sleep", "5"], cwd=tmp_path, timeout=0.2)
    assert not result.ok
    assert result.timed_out
    assert result.error is not None


def test_run_command_missing_executable(tmp_path: Path) -> None:
    result = run_command(["definitely-not-a-real-binary-xyz"], cwd=tmp_path, timeout=5)
    assert not result.ok
    assert result.error is not None


def test_run_sequence_stops_on_failure(tmp_path: Path) -> None:
    results = run_sequence([["true"], ["false"], ["echo", "never"]], cwd=tmp_path, timeout=5)
    assert len(results) == 2
    assert results[0].ok
    assert not results[1].ok


def test_run_sequence_continues_when_not_stopping(tmp_path: Path) -> None:
    results = run_sequence(
        [["false"], ["echo", "still-ran"]], cwd=tmp_path, timeout=5, stop_on_failure=False
    )
    assert len(results) == 2
    assert "still-ran" in results[1].stdout
