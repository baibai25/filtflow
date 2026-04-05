# Filtflow

[English](docs/README_en.md)

任意のマイク入力にエキスパンダーとコンプレッサーをリアルタイム適用し、Windows 上の全アプリケーションにフィルタ済み音声を提供する常駐ツール。

フィルタアルゴリズムは **OBS Studio の音声フィルタ機能（GPL-2.0）から派生**。

## 動作環境

- OS: Windows 10 / 11
- Python: 3.13.5 以上
- 仮想オーディオデバイス: [VB-Cable](https://vb-audio.com/Cable/)（別途インストール要）

## セットアップ

```bash
# 依存ライブラリインストール
uv sync

# アイコン生成（初回のみ）
cd Filtflow/assets && uv run python create_icons.py && cd ../..

# 起動
uv run python Filtflow/main.py
```

起動するとウィンドウは表示されずタスクトレイにアイコンが常駐する。
トレイアイコンを右クリック →「Settings」で設定ウィンドウを呼び出す。

## 機能

### フィルタチェーン

```
マイク入力 → [Expander] → [Compressor] → VB-Cable Input
```

| フィルタ | 参照元 | 説明 |
|---------|--------|------|
| Expander / Gate | `expander-filter.c` | RMS/peak 検出によるノイズ除去・エキスパンション |
| Compressor | `compressor-filter.c` | ピーク検出によるダイナミックコンプレッション |

### 設定 UI

- **デバイス選択**: 入力マイク・出力（VB-Cable）をドロップダウンで切替
- **Expander**: Preset（expander / gate）/ Ratio / Threshold / Attack / Release / Output Gain / Detector（RMS / peak）をリアルタイム調整
- **Compressor**: Ratio / Threshold / Attack / Release / Output Gain をリアルタイム調整
- **レベルメーター**: フィルタ後の OUT レベルを OBS 準拠3色で表示（30ms 更新・2秒ピーク保持）
- **保存 / デフォルトに戻す**: 設定を JSON 保存、OBS デフォルト値にリセット

### タスクトレイ

起動時はウィンドウなしでトレイに常駐。右クリックメニュー:

```
Settings
─────────
Quit
```

デバイスエラー時はアイコンが赤に変わる。

## パラメータ一覧（OBS デフォルト値）

### Expander

| パラメータ | 範囲 | expander デフォルト | gate デフォルト |
|-----------|------|---------------------|----------------|
| Ratio | 1.0 – 20.0 | 2.0 | 10.0 |
| Threshold | -60 – 0 dB | -40.0 dB | -40.0 dB |
| Attack | 1 – 100 ms | 10 ms | 10 ms |
| Release | 1 – 1000 ms | 50 ms | 125 ms |
| Output Gain | -32 – 32 dB | 0.0 dB | 0.0 dB |
| Detector | RMS / peak | RMS | RMS |

### Compressor

| パラメータ | 範囲 | デフォルト |
|-----------|------|-----------|
| Ratio | 1.0 – 32.0 | 10.0 |
| Threshold | -60 – 0 dB | -18.0 dB |
| Attack | 1 – 100 ms | 6 ms |
| Release | 1 – 1000 ms | 60 ms |
| Output Gain | -32 – 32 dB | 0.0 dB |

## 設定ファイル

```
%APPDATA%\Filtflow\config.json
```

初回起動時に OBS デフォルト値で自動生成される。

## ファイル構成

```
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

## exe ビルド

```bash
# アイコンが未生成の場合
cd Filtflow/assets && uv run python create_icons.py && cd ../..

cd Filtflow
uv run pyinstaller filtflow.spec
# → Filtflow/dist/Filtflow.exe
```

`console=False` でコンソールウィンドウは表示されない。

## 自動起動設定（Windows タスクスケジューラ）

| 項目 | 設定値 |
|------|--------|
| トリガー | ログオン時 |
| 操作 | `Filtflow.exe` |
| 失敗時の再起動 | 1 分後・最大 3 回 |
| 条件 → 電源 | AC 電源のみのチェックを外す |

## 依存ライブラリ

| ライブラリ | 用途 |
|-----------|------|
| sounddevice | WASAPI 入出力ストリーム |
| numpy | 信号処理 |
| pystray | タスクトレイ常駐 |
| Pillow | トレイアイコン画像処理 |
| PySide6 | 設定 UI（Qt6） |
| pyqtdarktheme | ダーク/ライトテーマ切替 |

依存関係は `pyproject.toml` で管理し、`uv` で解決する。

## ライセンス

本プロジェクトは [GNU General Public License v2 (GPL-2.0)](LICENSE) の下で公開されています。

本プロジェクトの音声フィルタは、
[OBS Studio](https://github.com/obsproject/obs-studio) の音声フィルタ機能（C 実装）を参考に Python で再実装したものです。
OBS Studio は GPL-2.0 でライセンスされており、本プロジェクトも同じく GPL-2.0 に従います。
