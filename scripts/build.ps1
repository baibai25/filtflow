# Filtflow ビルド＆配布zipスクリプト
# 使い方: powershell -ExecutionPolicy Bypass -File scripts\build.ps1

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$DistDir  = "Filtflow\dist"
$BuildDir = "Filtflow\build"
$ZipName  = "Filtflow.zip"
$StageDir = "_staging\Filtflow"

# 1. _version.py 生成 (setuptools-scm: git タグからバージョンを取得)
uv run python -c "from setuptools_scm import get_version; get_version(write_to='Filtflow/_version.py')"

# 2. PyInstaller ビルド
Push-Location Filtflow
uv run pyinstaller filtflow.spec --noconfirm
Pop-Location

# 3. ステージング準備
Remove-Item -Recurse -Force -ErrorAction SilentlyContinue _staging, $ZipName
New-Item -ItemType Directory -Force -Path "$StageDir\source" | Out-Null

# 4. exe をコピー
Copy-Item "$DistDir\Filtflow.exe" "$StageDir\"

# 5. ソースコードをコピー (.claude/ を除外)
git ls-files | Where-Object { $_ -notmatch '\.claude|\.gitignore' } | ForEach-Object {
    $dest = "$StageDir\source\$_"
    New-Item -ItemType Directory -Force -Path (Split-Path $dest) | Out-Null
    Copy-Item $_ $dest
}

# 6. zip 作成
Compress-Archive -Path $StageDir -DestinationPath $ZipName

# 7. クリーンアップ
Remove-Item -Recurse -Force $DistDir, $BuildDir, _staging

Write-Host "Done: $ZipName"
