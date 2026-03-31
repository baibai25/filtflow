"""タスクトレイ常駐

pystray を使ったシステムトレイアイコンを管理する。
アイコンファイルが存在しない場合は PIL で最小限のアイコンを生成する。
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Callable

import pystray
from PIL import Image, ImageDraw

ASSETS_DIR: Path = Path(__file__).parent / "assets"
ICON_PNG: Path = ASSETS_DIR / "icon.png"

# アイコンサイズ
ICON_SIZE: int = 64


def _generate_icon() -> Image.Image:
    """assets/icon.png が存在しない場合にフォールバックアイコンを生成する。

    32x32 の円形アイコン（緑ベース）を返す。
    """
    img = Image.new("RGBA", (ICON_SIZE, ICON_SIZE), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    # 外円（ダーク）
    draw.ellipse([2, 2, ICON_SIZE - 2, ICON_SIZE - 2], fill=(30, 30, 30, 255))
    # 内円（緑）
    margin = ICON_SIZE // 5
    draw.ellipse(
        [margin, margin, ICON_SIZE - margin, ICON_SIZE - margin],
        fill=(0, 200, 80, 255),
    )
    return img


def _load_icon() -> Image.Image:
    """トレイアイコン画像を読み込む。ファイルがなければ生成する。"""
    if ICON_PNG.exists():
        return Image.open(ICON_PNG).convert("RGBA")
    return _generate_icon()


class TrayIcon:
    """pystray タスクトレイアイコン。

    メニュー構成:
        Filtflow [動作中 ✓]
        ─────────────────────
        設定を開く
        ─────────────────────
        終了
    """

    def __init__(
        self,
        on_open_settings: Callable[[], None],
        on_quit: Callable[[], None],
    ) -> None:
        self._on_open_settings = on_open_settings
        self._on_quit = on_quit
        self._icon: pystray.Icon | None = None
        self._thread: threading.Thread | None = None

    def _build_icon(self) -> pystray.Icon:
        menu = pystray.Menu(
            pystray.MenuItem("Filtflow  動作中 ✓", None, enabled=False),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("設定を開く", self._handle_open_settings),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("終了", self._handle_quit),
        )
        return pystray.Icon(
            name="Filtflow",
            icon=_load_icon(),
            title="Filtflow",
            menu=menu,
        )

    def _handle_open_settings(
        self, icon: pystray.Icon, item: pystray.MenuItem
    ) -> None:
        self._on_open_settings()

    def _handle_quit(self, icon: pystray.Icon, item: pystray.MenuItem) -> None:
        self._on_quit()
        if self._icon is not None:
            self._icon.stop()

    def run_detached(self) -> None:
        """バックグラウンドスレッドでトレイアイコンを起動する。

        メインスレッドで tkinter の mainloop() を実行できるよう、
        pystray はデーモンスレッドで動かす。
        """
        self._icon = self._build_icon()
        self._thread = threading.Thread(
            target=self._icon.run,
            name="TrayIconThread",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        """トレイアイコンを停止する。"""
        if self._icon is not None:
            try:
                self._icon.stop()
            except Exception:
                pass

    def set_error_state(self) -> None:
        """エラー状態を示すアイコンに切り替える。"""
        if self._icon is None:
            return
        img = Image.new("RGBA", (ICON_SIZE, ICON_SIZE), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        draw.ellipse([2, 2, ICON_SIZE - 2, ICON_SIZE - 2], fill=(30, 30, 30, 255))
        margin = ICON_SIZE // 5
        # 赤で塗る（エラー状態）
        draw.ellipse(
            [margin, margin, ICON_SIZE - margin, ICON_SIZE - margin],
            fill=(220, 50, 50, 255),
        )
        self._icon.icon = img

    def set_normal_state(self) -> None:
        """通常状態のアイコンに戻す。"""
        if self._icon is None:
            return
        self._icon.icon = _load_icon()
