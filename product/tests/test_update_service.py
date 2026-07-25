from __future__ import annotations

import json
from pathlib import Path

import app.update_service as update_service


class FakeResponse:
    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")


def test_github_release_check_detects_new_version(tmp_path: Path, monkeypatch) -> None:
    version_file = tmp_path / "VERSION"
    version_file.write_text("0.10.0\n", encoding="utf-8")
    monkeypatch.setattr(update_service, "VERSION_FILE", version_file)
    monkeypatch.setattr(update_service, "STATUS_FILE", tmp_path / "update-status.json")
    monkeypatch.setattr(update_service, "RUNTIME_DIR", tmp_path)
    monkeypatch.setattr(update_service, "UPDATE_REPOSITORY", "owner/releases")

    def opener(request, timeout: int):
        assert request.full_url == "https://api.github.com/repos/owner/releases/releases/latest"
        assert timeout == 20
        return FakeResponse(
            {
                "tag_name": "v0.11.0",
                "html_url": "https://github.com/owner/releases/releases/tag/v0.11.0",
            }
        )

    result = update_service.check_latest(opener=opener)
    assert result["current_version"] == "0.10.0"
    assert result["latest_version"] == "0.11.0"
    assert result["update_available"] is True
    assert result["state"] == "available"
    assert (tmp_path / "update-status.json").is_file()


def test_github_release_check_reports_current_version(tmp_path: Path, monkeypatch) -> None:
    version_file = tmp_path / "VERSION"
    version_file.write_text("0.11.0\n", encoding="utf-8")
    monkeypatch.setattr(update_service, "VERSION_FILE", version_file)
    monkeypatch.setattr(update_service, "STATUS_FILE", tmp_path / "update-status.json")
    monkeypatch.setattr(update_service, "RUNTIME_DIR", tmp_path)
    monkeypatch.setattr(update_service, "UPDATE_REPOSITORY", "owner/releases")

    result = update_service.check_latest(
        opener=lambda *_args, **_kwargs: FakeResponse({"tag_name": "v0.11.0"})
    )
    assert result["update_available"] is False
    assert result["state"] == "current"


def test_windows_update_command_is_explicit_and_non_shell(monkeypatch) -> None:
    monkeypatch.setenv("SystemRoot", r"C:\Windows")
    command = update_service.windows_update_command(automatic=True)
    assert command[0].endswith(r"WindowsPowerShell/v1.0/powershell.exe") or command[0].endswith(
        r"WindowsPowerShell\v1.0\powershell.exe"
    )
    assert "-ExecutionPolicy" in command
    assert "Bypass" in command
    assert command[-1] == "-Automatic"
    assert any(item.endswith("update.ps1") for item in command)

