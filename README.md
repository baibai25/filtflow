# Filtflow

[English](docs/README_en.md)

任意のマイク入力にエキスパンダーとコンプレッサーをリアルタイム適用し、Windows 上の全アプリケーションにフィルタ済み音声を提供する常駐ツールです。

フィルタアルゴリズムは **OBS Studio の音声フィルタ機能（GPL-2.0）から派生**しています。

## 動作環境

- OS: Windows 10 / 11
- 仮想オーディオデバイス: [VB-Cable](https://vb-audio.com/Cable/)（別途インストールが必要です）

## インストール

### 1. VB-Cable のインストール

Filtflow はフィルタ処理した音声を仮想オーディオデバイス経由で通話アプリ（Discord・Teams など）に渡します。そのため事前に VB-Cable のインストールが必要です。

1. [VB-Cable 公式サイト](https://vb-audio.com/Cable/) からインストーラをダウンロードします
2. `VBCABLE_Setup_x64.exe` を**管理者として実行**してインストールします
3. 求められた場合は PC を再起動してください

### 2. Filtflow のインストール

1. [GitHub Releases](https://github.com/baibai25/filtflow/releases) から最新の zip をダウンロードします
2. zip を任意のフォルダに展開します
3. `Filtflow.exe` を実行します

## 使い方

起動するとウィンドウは表示されず、タスクトレイにアイコンが常駐します。

1. トレイアイコンを右クリック →「Settings」で設定画面を開きます
2. 入力マイクと出力デバイス（VB-Cable）を選択し、フィルタのパラメータを調整します
3. 通話アプリ側のマイク設定を **「CABLE Output (VB-Audio Virtual Cable)」** に変更します

> デバイスエラー時はトレイアイコンが赤に変わります。

## 設定ファイル

```text
%APPDATA%\Filtflow\config.json
```

初回起動時に OBS デフォルト値で自動生成されます。

## 開発者向け

### セットアップ

```bash
# 依存ライブラリインストール
uv sync

# アイコン生成（初回のみ）
cd Filtflow/assets && uv run python create_icons.py && cd ../..

# 起動
uv run python Filtflow/main.py
```

### ファイル構成

```text
Filtflow/
├── main.py              エントリポイント・起動制御
├── audio_stream.py      デバイス列挙・WASAPI ストリーム管理
├── compressor.py        コンプレッサーフィルタ（OBS 準拠）
├── expander.py          エキスパンダーフィルタ（OBS 準拠）
├── config.py            設定値の定義・ロード・保存
├── ui.py                設定 UI（PySide6）
├── tray.py              タスクトレイ常駐（pystray）
├── filtflow.spec        PyInstaller ビルド設定
└── assets/
    ├── create_icons.py  icon.png / icon.ico 生成スクリプト
    ├── icon.png         トレイアイコン（create_icons.py で生成）
    └── icon.ico         exe アイコン（create_icons.py で生成）
```

### exe ビルド

```bash
# アイコンが未生成の場合
cd Filtflow/assets && uv run python create_icons.py && cd ../..

cd Filtflow
uv run pyinstaller filtflow.spec
# → Filtflow/dist/Filtflow.exe
```

`console=False` でコンソールウィンドウは表示されません。

## ライセンス

本プロジェクトは [GNU General Public License v2 or later (GPL-2.0-or-later)](LICENSE) の下で公開されています。

本プロジェクトの音声フィルタは、
[OBS Studio](https://github.com/obsproject/obs-studio) の音声フィルタ機能（C 実装）を参考に Python で再実装したものです。
OBS Studio は GPL-2.0-or-later でライセンスされており、本プロジェクトも同じく GPL-2.0-or-later に従います。
