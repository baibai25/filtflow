"""起動時の更新チェック

GitHub Releases API を使って最新バージョンを取得し、
現在のバージョンより新しいリリースがあればシグナルで通知する。
ネットワークエラー時は静かにスキップする。
"""

from __future__ import annotations

import json
import urllib.request
from threading import Thread
from typing import Any

from packaging.version import InvalidVersion, Version
from PySide6.QtCore import QObject, Signal

GITHUB_API_URL: str = "https://api.github.com/repos/baibai25/filtflow/releases/latest"

# API リクエストのタイムアウト (秒)
REQUEST_TIMEOUT: int = 5


def _fetch_latest_release() -> dict[str, Any] | None:
    """GitHub Releases API から最新リリース情報を取得する。

    Returns:
        レスポンス JSON の dict。失敗時は None。
    """
    req = urllib.request.Request(
        GITHUB_API_URL,
        headers={"Accept": "application/vnd.github.v3+json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
            return json.loads(resp.read().decode("utf-8"))  # type: ignore[no-any-return]
    except Exception:
        return None


def _parse_version(tag: str) -> Version | None:
    """タグ文字列 ("v0.1.0" 等) を Version に変換する。"""
    try:
        return Version(tag.removeprefix("v"))
    except InvalidVersion:
        return None


class UpdateChecker(QObject):
    """バックグラウンドスレッドで GitHub の最新リリースをチェックする。

    新しいバージョンが見つかった場合、update_available シグナルを発火する。
    """

    update_available = Signal(str, str)  # (latest_version, release_url)

    def check(self, current_version: str) -> None:
        """別スレッドで最新バージョンをチェックする。

        Args:
            current_version: 現在のアプリバージョン (例: "0.1.0")
        """
        thread = Thread(
            target=self._run,
            args=(current_version,),
            name="UpdateCheckerThread",
            daemon=True,
        )
        thread.start()

    def _run(self, current_version: str) -> None:
        current = _parse_version(current_version)
        if current is None:
            return

        data = _fetch_latest_release()
        if data is None:
            return

        tag_name = data.get("tag_name", "")
        latest = _parse_version(tag_name)
        if latest is None:
            return

        if latest > current:
            release_url = data.get(
                "html_url",
                "https://github.com/baibai25/filtflow/releases",
            )
            self.update_available.emit(str(latest), release_url)
