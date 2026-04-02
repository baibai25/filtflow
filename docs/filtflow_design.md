# Filtflow 設計書

## 1. 概要

### 1.1 目的

任意のマイク入力にコンプレッサーとエキスパンダーをリアルタイム適用し、
Windows上の全アプリケーションに対してフィルタ済み音声を提供する常駐ツール。

フィルタのアルゴリズムおよびパラメータはすべて
**OBS Studio のソースコード（MITライセンス）に完全準拠**する。

- compressor: `plugins/obs-filters/compressor-filter.c`
- expander:   `plugins/obs-filters/expander-filter.c`

### 1.2 対象ユーザー

開発者本人のみ（自分用ツール）

### 1.3 動作環境

- OS: Windows 10 / 11
- Python: 3.10以上
- 入力デバイス: 任意のマイク / オーディオインタフェース（UI上で選択）
- 仮想デバイス: VB-Cable（別途インストール要）

---

## 2. アーキテクチャ

### 2.1 全体構成

```
【物理層】
任意のマイク入力（UIで選択）
    ↓ WASAPI
【処理層】
Pythonプロセス
  ├─ AudioStream   WASAPIストリーム管理
  ├─ Compressor    OBS compressor-filter.c 準拠
  └─ Expander      OBS expander-filter.c 準拠
    ↓ WASAPI write
【仮想層】
VB-Cable CABLE Input（UIで選択）
    ↓ Windowsデフォルトマイクに設定
【アプリ層】
Discord / OBS / ブラウザ / その他すべて
```

### 2.2 フィルタチェーン順序

OBSのベストプラクティスに準拠し、以下の順で適用する：

```
入力 → [Expander] → [Compressor] → 出力
```

エキスパンダーで無音部分を削ってからコンプレッサーで音量の突出を抑えることで、
ゲインの暴れを最小化する。

### 2.3 モジュール構成

```
Filtflow/
├── main.py            エントリポイント・起動制御
├── audio_stream.py    デバイス列挙・WASAPIストリーム管理
├── compressor.py      コンプレッサーフィルタ本体
├── expander.py        エキスパンダーフィルタ本体
├── config.py          設定値の定義・ロード・保存（JSON）
├── ui.py              設定UI（tkinter）
├── tray.py            タスクトレイ常駐
├── filtflow.spec      PyInstallerビルド設定
├── requirements.txt
└── assets/
    ├── icon.png       トレイアイコン（PNG）
    └── icon.ico       exeアイコン（ICO）
```

---

## 3. フィルタ仕様（OBS完全準拠）

### 3.1 Compressor（compressor-filter.c 準拠）

#### パラメータ

| パラメータ | 型 | 範囲 | OBSデフォルト | 説明 |
|-----------|-----|------|-------------|------|
| ratio | float | 1.0 – 32.0 | 10.0 | 圧縮比（X:1） |
| threshold | float (dB) | -60.0 – 0.0 | -18.0 | 圧縮開始レベル |
| attack_time | int (ms) | 1 – 100 | 6 | 圧縮到達時間 |
| release_time | int (ms) | 1 – 1000 | 60 | 圧縮解除時間 |
| output_gain | float (dB) | -32.0 – 32.0 | 0.0 | 圧縮後の出力ゲイン |

※ sidechain_source はスタンドアロンツールのためスコープ外

#### アルゴリズム（OBS準拠）

```
gain_coefficient(sample_rate, time_ms):
    return exp(-1.0 / (sample_rate * time_ms / 1000))

slope = 1.0 - (1.0 / ratio)

サンプル毎の処理（analyze_envelope → process_compression）:
1. エンベロープ検出（ピーク検出）
   - 上昇時: envelope = attack_gain  * envelope + (1 - attack_gain)  * |sample|
   - 下降時: envelope = release_gain * envelope + (1 - release_gain) * |sample|

2. ゲイン計算
   - envelope_db = 20 * log10(envelope)
   - if envelope_db > threshold:
       gain_db = slope * (threshold - envelope_db)
   - else:
       gain_db = 0.0

3. 適用
   sample_out = sample * db_to_mul(gain_db) * output_gain
```

#### 主要インターフェース

```python
class Compressor:
    def __init__(self, ratio: float, threshold: float, attack_ms: int,
                 release_ms: int, output_gain_db: float, sample_rate: int)
    def process(self, frame: np.ndarray) -> np.ndarray
    def update_params(self, **kwargs) -> None
```

---

### 3.2 Expander（expander-filter.c 準拠）

#### パラメータ

| パラメータ | 型 | 範囲 | expander デフォルト | gate デフォルト | 説明 |
|-----------|-----|------|-------------------|----------------|------|
| preset | str | expander / gate | expander | gate | プリセット（presetsパラメータ） |
| ratio | float | 1.0 – 20.0 | 2.0 | 10.0 | 拡張比 |
| threshold | float (dB) | -60.0 – 0.0 | -40.0 | -40.0 | 拡張開始レベル |
| attack_time | int (ms) | 1 – 100 | 10 | 10 | 拡張到達時間 |
| release_time | int (ms) | 1 – 1000 | 50 | 125 | 拡張解除時間 |
| output_gain | float (dB) | -32.0 – 32.0 | 0.0 | 0.0 | 出力ゲイン |
| detector | str | RMS / peak | RMS | RMS | レベル検出方式 |

#### アルゴリズム（OBS準拠）

```
slope = 1.0 - ratio   ← OBS: slope = 1.0f - cd->ratio

RMS検出時（10ms RMSウィンドウ / DEFAULT_AUDIO_BUF_MS = 10）:
    rmscoef = exp2(-100.0 / sample_rate)
    runave[i] = rmscoef * runave[i-1] + (1 - rmscoef) * sample[i]^2
    env_in[i] = sqrt(max(runave[i], 0))

Peak検出時:
    env_in[i] = |sample[i]|

envelope_buf = max(envelope_buf, env_in)  ← チャンネル間でmax

サンプル毎のゲイン計算（process_sample 準拠）:
1. envelope_db = 20 * log10(envelope)

2. if envelope_db < threshold:
       gain_db = slope * (envelope_db - threshold)
   else:
       gain_db = 0.0

3. アタック/リリースで平滑化
   - gain_db < gain_db_prev: attack_gain で追う
   - gain_db > gain_db_prev: release_gain で戻す

4. sample_out = sample * db_to_mul(gain_db) * output_gain
```

#### 主要インターフェース

```python
class Expander:
    def __init__(self, preset: str, ratio: float, threshold: float,
                 attack_ms: int, release_ms: int, output_gain_db: float,
                 detector: str, sample_rate: int)
    def process(self, frame: np.ndarray) -> np.ndarray
    def update_params(self, **kwargs) -> None
```

---

## 4. モジュール詳細

### 4.1 audio_stream.py

**責務**

- sounddevice を使ったWASAPIストリームの開通
- コールバック経由でフィルタチェーン（Expander → Compressor）を呼び出す
- デバイス一覧の列挙とインデックス特定

**パラメータ**

| 項目 | 値 | 備考 |
|------|----|------|
| sample_rate | 48000 Hz | デフォルト（UI上で変更可） |
| block_size | 480 samples | 10ms |
| channels | 1 (mono) | マイクはモノラル |
| dtype | float32 | sounddevice 標準 |

**主要インターフェース**

```python
class AudioStream:
    def __init__(self, input_device: int, output_device: int,
                 filter_chain: list[callable], sample_rate: int, block_size: int)
    def start(self) -> None
    def stop(self) -> None
    def restart(self) -> None   # デバイス変更時に呼び出す

def list_devices() -> list[dict]          # 入出力デバイス一覧
def find_device_index(name: str) -> int   # 名前からインデックス取得
```

---

### 4.2 config.py

**設定ファイル（config.json）配置場所**

```
%APPDATA%\Filtflow\config.json
```

**スキーマ**

```json
{
  "input_device_name": "",
  "output_device_name": "CABLE Input (VB-Audio Virtual Cable)",
  "sample_rate": 48000,
  "block_size": 480,
  "compressor": {
    "enabled": true,
    "ratio": 10.0,
    "threshold_db": -18.0,
    "attack_ms": 6,
    "release_ms": 60,
    "output_gain_db": 0.0
  },
  "expander": {
    "enabled": true,
    "preset": "expander",
    "ratio": 2.0,
    "threshold_db": -40.0,
    "attack_ms": 10,
    "release_ms": 50,
    "output_gain_db": 0.0,
    "detector": "RMS"
  }
}
```

---

### 4.3 ui.py

**責務**

- デバイス選択（入力・出力）
- コンプレッサー / エキスパンダー各パラメータのスライダー操作
- スライダー操作中リアルタイムで `update_params()` を呼び出し即時反映
- レベルメーターの表示（フィルタ前・フィルタ後）
- 設定のJSONへの保存

**UIレイアウト（tkinterウィンドウ）**

```
┌─────────────────────────────────────────┐
│  Filtflow 設定                           │
├─────────────────────────────────────────┤
│  [レベルメーター]                         │
│  OUT ████████████░░░░░░  -12.4 dB        │
│                          peak: -10.2 dB  │
├─────────────────────────────────────────┤
│  [デバイス設定]                           │
│  入力デバイス: [ドロップダウン ▼]          │
│  出力デバイス: [ドロップダウン ▼]          │
├─────────────────────────────────────────┤
│  [Compressor]               有効 [✓]    │
│  Ratio       ●────────  10.0 (1.0-32.0) │
│  Threshold   ●──────── -18.0 (-60 - 0)  │
│  Attack      ●────────    6  (1-100 ms) │
│  Release     ●────────   60  (1-1000ms) │
│  Output Gain ●────────  0.0  (-32 - 32) │
├─────────────────────────────────────────┤
│  [Expander]                 有効 [✓]    │
│  Preset      [expander ▼]               │
│  Ratio       ●────────  2.0  (1.0-20.0) │
│  Threshold   ●──────── -40.0 (-60 - 0)  │
│  Attack      ●────────   10  (1-100 ms) │
│  Release     ●────────   50  (1-1000ms) │
│  Output Gain ●────────  0.0  (-32 - 32) │
│  Detector    [RMS ▼]                    │
├─────────────────────────────────────────┤
│       [保存]      [デフォルトに戻す]      │
└─────────────────────────────────────────┘
```

**パラメータ変更のタイミング**

- スライダー操作中 → `update_params()` をリアルタイム呼び出し（即時反映）
- 「保存」押下 → `config.json` へ書き込み
- 「デフォルトに戻す」→ OBSデフォルト値をUIとフィルタに適用

**レベルメーターの仕様**

| 項目 | 内容 |
|------|------|
| 表示対象 | OUT（フィルタ後）一本 |
| レベル計算 | 各フレームのRMSをdBに変換 |
| ピーク保持 | 2秒間ピーク値を保持して表示 |
| 更新レート | 30ms ごとに `canvas.after()` で再描画 |
| 範囲 | -60 dB 〜 0 dB |

**OBS準拠の配色**

OBSのメーターは -20 dBFS をAlignment Level（AL）、-9 dBFS をPermitted Maximum Level（PML）として3色に分割している。

| 区間 | 色 | 意味 |
|------|----|------|
| -60 〜 -20 dBFS | 緑 `#00cc00` | 正常範囲 |
| -20 〜 -9 dBFS | 黄 `#ffff00` | 注意範囲（音声はここを目標） |
| -9 〜 0 dBFS | 赤 `#ff0000` | 危険範囲（クリップの恐れ） |

**レベル計算式**

```python
rms = np.sqrt(np.mean(frame ** 2) + 1e-10)
level_db = 20 * np.log10(rms)
level_db = max(-60.0, level_db)   # 下限クリップ
```

audioストリームのコールバック内でフィルタ後の値をスレッドセーフなキューに積み、UIスレッド側で30msごとに読み出して描画する。

---

### 4.4 tray.py

**メニュー構成**

```
Filtflow [動作中 ✓]
─────────────────────
設定を開く
─────────────────────
終了
```

起動時はウィンドウを表示せずトレイアイコンのみ常駐。
「設定を開く」から ui.py のウィンドウを呼び出す。

---

## 5. OBSソース参照まとめ

| モジュール | 参照ファイル | 主な参照箇所 |
|-----------|------------|-------------|
| compressor.py | compressor-filter.c | `compressor_defaults()`, `analyze_envelope()`, `process_compression()` |
| expander.py | expander-filter.c | `expander_defaults()`, `analyze_envelope()`, `process_sample()`, `process_expansion()` |

定数はソースコードの `#define` と完全一致させること：

```python
# compressor-filter.c 由来
COMP_MIN_RATIO        =  1.0
COMP_MAX_RATIO        = 32.0
COMP_MIN_THRESHOLD_DB = -60.0
COMP_MAX_THRESHOLD_DB =   0.0
COMP_MIN_OUTPUT_GAIN  = -32.0
COMP_MAX_OUTPUT_GAIN  =  32.0
COMP_MIN_ATK_RLS_MS   =   1
COMP_MAX_ATK_MS       = 100
COMP_MAX_RLS_MS       = 1000

# expander-filter.c 由来
EXP_MIN_RATIO         =  1.0
EXP_MAX_RATIO         = 20.0
EXP_MIN_THRESHOLD_DB  = -60.0
EXP_MAX_THRESHOLD_DB  =   0.0
EXP_MIN_OUTPUT_GAIN   = -32.0
EXP_MAX_OUTPUT_GAIN   =  32.0
EXP_MIN_ATK_RLS_MS    =   1
EXP_MAX_ATK_MS        = 100
EXP_MAX_RLS_MS        = 1000
EXP_DEFAULT_AUDIO_BUF_MS = 10   # RMSウィンドウ幅（10ms）
```

---

## 6. 依存ライブラリ

```
sounddevice   # WASAPIオーディオI/O
numpy         # 信号処理
pystray       # タスクトレイ常駐
Pillow        # トレイアイコン
tkinter       # 設定UI（Python標準ライブラリ・追加インストール不要）
pyinstaller   # exeビルド用（開発時のみ）
```

---

## 7. 自動起動設定

Windowsタスクスケジューラで以下を設定する：

| 項目 | 設定値 |
|------|--------|
| トリガー | ログオン時 |
| 操作 | `Filtflow.exe`（コンソール非表示） |
| 失敗時の再起動 | 1分後に再試行・最大3回 |
| 条件 → 電源 | AC電源のみのチェックを外す |

---

## 8. エラーハンドリング

| エラー | 対応 |
|--------|------|
| 入力デバイスが見つからない | トレイアイコンをエラー状態に変更・UI上に警告表示 |
| VB-Cableが見つからない | 同上 |
| ストリーム途切れ | 3秒後に自動再接続 |
| 予期せぬクラッシュ | タスクスケジューラの再起動設定に委任 |

---

## 9. ビルドと配布

### 9.1 ビルド方法

PyInstaller を使ってPython環境ごと単一exeに梱包する。

```
pip install pyinstaller
pyinstaller filtflow.spec
```

出力先：`dist/Filtflow.exe`

---

### 9.2 filtflow.spec

```python
# filtflow.spec
block_cipher = None

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('assets/icon.png', 'assets'),  # トレイアイコン
    ],
    hiddenimports=[
        'sounddevice',
        'numpy',
        'pystray',
        'PIL',
    ],
    hookspath=[],
    cipher=block_cipher,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    name='Filtflow',
    debug=False,
    console=False,      # コンソールウィンドウを表示しない
    icon='assets/icon.ico',
)
```

**ビルド時の注意点**

- `console=False` で起動時にコンソールウィンドウが出ないようにする
- sounddevice は内部でPortAudioのDLLを使うため、`--onefile` ビルド後に動作確認を必ず行う
- アイコンは `.ico` 形式が必要（`.png` とは別に用意する）

---

### 9.3 配布パッケージ

```
Filtflow.zip
└── Filtflow.exe
```

zipに固めて配布するだけでよい。設定ファイルは初回起動時に自動生成される：

```
%APPDATA%\Filtflow\config.json   ← 初回起動時に自動作成
```

---

## 10. スコープ外

- サイドチェーン圧縮（sidechain_source）
- 複数マイク同時処理
- 他OSへの対応
- EQ・リミッター等の追加フィルタ
