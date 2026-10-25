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
from PySide6.QtCore import QObject, Signal, Slot

GITHUB_API_URL: str = "https://api.github.com/repos/baibai25/filtflow/releases/latest"

# リリース一覧ページ (タグ名が不正な場合のフォールバック先)
RELEASES_URL: str = "https://github.com/baibai25/filtflow/releases"

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


def _build_release_url(tag_name: str) -> str:
    """タグ名からリリースページの URL を自前で構築する。

    API レスポンス由来の URL (html_url) をそのままブラウザに渡さず、
    英数字と ".-_" のみからなるタグ名で URL を組み立てる。
    タグ名が不正な場合はリリース一覧ページにフォールバックする。
    """
    if tag_name and all(c.isalnum() or c in ".-_" for c in tag_name):
        return f"{RELEASES_URL}/tag/{tag_name}"
    return RELEASES_URL


class UpdateChecker(QObject):
    """バックグラウンドスレッドで GitHub の最新リリースをチェックする。

    新しいバージョンが見つかった場合、update_available シグナルを発火する。
    update_available は常に本オブジェクトの所属スレッド（通常はメインスレッド）
    で発火されるため、素の Python 関数を接続しても安全に GUI を操作できる。
    """

    update_available = Signal(str, str)  # (latest_version, release_url)

    # ワーカースレッドから発火する内部シグナル。受け側 _relay が QObject の
    # バウンドメソッドのため AutoConnection がスレッド境界を検出して
    # QueuedConnection となり、_relay は本オブジェクトの所属スレッドで実行される。
    _found = Signal(str, str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._found.connect(self._relay)

    @Slot(str, str)
    def _relay(self, latest_version: str, release_url: str) -> None:
        self.update_available.emit(latest_version, release_url)

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
            self._found.emit(str(latest), _build_release_url(tag_name))
