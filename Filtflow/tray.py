"""タスクトレイ常駐

QSystemTrayIcon を使ったシステムトレイアイコンを管理する。
アイコンファイルが存在しない場合は QPainter で最小限のアイコンを生成する。
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from PySide6.QtGui import QBrush, QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

ASSETS_DIR: Path = Path(__file__).parent / "assets"
ICON_PNG: Path = ASSETS_DIR / "icon.png"

# アイコンサイズ
ICON_SIZE: int = 64


def _generate_icon(
    inner_color: QColor = QColor(0, 200, 80, 255),
) -> QIcon:
    """円形フォールバックアイコンを生成する。

    assets/icon.png が存在しない場合や、状態表示アイコンの生成に使用する。
    """
    pixmap = QPixmap(ICON_SIZE, ICON_SIZE)
    pixmap.fill(QColor(0, 0, 0, 0))

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)

    # 外側の暗い円
    painter.setBrush(QBrush(QColor(30, 30, 30, 255)))
    painter.setPen(QColor(0, 0, 0, 0))
    painter.drawEllipse(2, 2, ICON_SIZE - 4, ICON_SIZE - 4)

    # 内側のカラー円
    margin = ICON_SIZE // 5
    painter.setBrush(QBrush(inner_color))
    painter.drawEllipse(margin, margin, ICON_SIZE - margin * 2, ICON_SIZE - margin * 2)

    painter.end()
    return QIcon(pixmap)


def _load_icon() -> QIcon:
    """トレイアイコン画像を読み込む。ファイルがなければ生成する。"""
    if ICON_PNG.exists():
        return QIcon(str(ICON_PNG))
    return _generate_icon()


class TrayIcon:
    """QSystemTrayIcon タスクトレイアイコン。

    メニュー構成:
        Settings
        ─────────
        Quit
    """

    def __init__(
        self,
        on_open_settings: Callable[[], None],
        on_quit: Callable[[], None],
    ) -> None:
        self._on_open_settings = on_open_settings
        self._on_quit = on_quit

        # メニュー構築
        self._menu = QMenu()
        self._menu.addAction("Settings", self._on_open_settings)
        self._menu.addSeparator()
        self._menu.addAction("Quit", self._on_quit)

        # トレイアイコン構築
        self._tray = QSystemTrayIcon()
        self._tray.setIcon(_load_icon())
        self._tray.setToolTip("Filtflow")
        self._tray.setContextMenu(self._menu)

    def show(self) -> None:
        """トレイアイコンを表示する。"""
        self._tray.show()

    def stop(self) -> None:
        """トレイアイコンを停止する。"""
        self._tray.hide()

    def set_error_state(self) -> None:
        """エラー状態を示すアイコンに切り替える。"""
        self._tray.setIcon(_generate_icon(inner_color=QColor(220, 50, 50, 255)))

    def set_normal_state(self) -> None:
        """通常状態のアイコンに戻す。"""
        self._tray.setIcon(_load_icon())
