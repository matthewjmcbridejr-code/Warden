import pytest

from warden.webstudio import vercel


def test_build_pull_command_is_safe() -> None:
    args = vercel.build_pull_command(environment="preview")
    assert args == ["vercel", "pull", "--yes", "--environment=preview"]


def test_build_build_command_rejects_prod() -> None:
    with pytest.raises(ValueError):
        vercel.build_build_command(prod=True)


def test_build_preview_deploy_command_never_includes_prod_flag() -> None:
    args = vercel.build_preview_deploy_command()
    assert "--prod" not in args
    assert "-p" not in args
    assert args[0] == "vercel"
    assert args[1] == "deploy"


def test_build_inspect_and_logs_commands() -> None:
    assert vercel.build_inspect_command("abc123") == ["vercel", "inspect", "abc123"]
    assert vercel.build_logs_command("abc123") == ["vercel", "logs", "abc123"]


def test_extract_preview_url_from_stdout() -> None:
    from warden.webstudio.commands import CommandResult

    result = CommandResult(
        args=["vercel", "deploy"],
        cwd="/tmp",
        returncode=0,
        stdout="Some build logs\nhttps://usemarius-abc123.vercel.app\n",
        stderr="",
        duration_seconds=1.0,
    )
    assert vercel.extract_preview_url(result) == "https://usemarius-abc123.vercel.app"


def test_extract_preview_url_returns_none_when_absent() -> None:
    from warden.webstudio.commands import CommandResult

    result = CommandResult(
        args=["vercel", "deploy"],
        cwd="/tmp",
        returncode=1,
        stdout="error: something went wrong\n",
        stderr="",
        duration_seconds=1.0,
    )
    assert vercel.extract_preview_url(result) is None
