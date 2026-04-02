# filtflow.spec
# PyInstaller ビルド設定
# 使い方: pyinstaller filtflow.spec
block_cipher = None

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('assets/icon.png', 'assets'),
    ],
    hiddenimports=[
        'sounddevice',
        'numpy',
        'pystray',
        'PIL',
        'PIL.Image',
        'PIL.ImageDraw',
        'PySide6',
        'PySide6.QtCore',
        'PySide6.QtGui',
        'PySide6.QtWidgets',
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
