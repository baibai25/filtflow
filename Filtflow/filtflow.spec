# filtflow.spec
# PyInstaller ビルド設定
# 使い方: pyinstaller filtflow.spec
block_cipher = None

a = Analysis(
    # main.py はパッケージ内相対 import を使うため直接エントリにできない。
    # 絶対 import で起動する薄いランチャーを経由する
    ['launcher.py'],
    # リポジトリルートを追加して Filtflow パッケージを解決可能にする
    pathex=['..'],
    binaries=[],
    datas=[
        # 各モジュールは Path(__file__).parent / "assets" で参照するため、
        # frozen 時のモジュール配置 (_MEIPASS/Filtflow/) に合わせて配置する
        ('assets/icon.png', 'Filtflow/assets'),
        ('../LICENSE', '.'),
    ],
    hiddenimports=[
        'sounddevice',
        'numpy',
        'PySide6',
        'PySide6.QtCore',
        'PySide6.QtGui',
        'PySide6.QtWidgets',
    ],
    excludes=[
        # Qt モジュール（アプリは QtCore/QtGui/QtWidgets のみ使用）
        'PySide6.Qt3DAnimation',
        'PySide6.Qt3DCore',
        'PySide6.Qt3DExtras',
        'PySide6.Qt3DInput',
        'PySide6.Qt3DLogic',
        'PySide6.Qt3DRender',
        'PySide6.QtBluetooth',
        'PySide6.QtCharts',
        'PySide6.QtConcurrent',
        'PySide6.QtDataVisualization',
        'PySide6.QtDBus',
        'PySide6.QtDesigner',
        'PySide6.QtGraphs',
        'PySide6.QtHelp',
        'PySide6.QtHttpServer',
        'PySide6.QtLocation',
        'PySide6.QtMultimedia',
        'PySide6.QtMultimediaWidgets',
        'PySide6.QtNetwork',
        'PySide6.QtNetworkAuth',
        'PySide6.QtNfc',
        'PySide6.QtOpenGL',
        'PySide6.QtOpenGLWidgets',
        'PySide6.QtPdf',
        'PySide6.QtPdfWidgets',
        'PySide6.QtPositioning',
        'PySide6.QtPrintSupport',
        'PySide6.QtQml',
        'PySide6.QtQuick',
        'PySide6.QtQuickWidgets',
        'PySide6.QtRemoteObjects',
        'PySide6.QtSensors',
        'PySide6.QtSerialBus',
        'PySide6.QtSerialPort',
        'PySide6.QtSpatialAudio',
        'PySide6.QtSql',
        # PySide6.QtSvg — qdarktheme が内部で使用するため除外不可
        'PySide6.QtSvgWidgets',
        'PySide6.QtTest',
        'PySide6.QtWebChannel',
        'PySide6.QtWebEngineCore',
        'PySide6.QtWebEngineQuick',
        'PySide6.QtWebEngineWidgets',
        'PySide6.QtWebSockets',
        'PySide6.QtXml',
        # numpy 未使用サブパッケージ（コア非依存が確実なもののみ）
        'numpy.f2py',
        'numpy.testing',
        'numpy.distutils',
    ],
    hookspath=[],
    cipher=block_cipher,
)

# 不要な Qt 翻訳ファイル・プラグイン・リソースを除去
_exclude_data_prefixes = (
    'PySide6/translations/',
    'PySide6/resources/',          # icudtl.dat (~10 MB)
    'PySide6/plugins/multimedia',
    'PySide6/plugins/sqldrivers',
    'PySide6/plugins/designer',
    'PySide6/plugins/qmltooling',
    'PySide6/plugins/networkinformation',    # Qt6Network 除外済みのため不要
    'PySide6/plugins/tls',                   # 同上
    'PySide6/plugins/generic',               # タッチ入力等、本アプリでは未使用
    'PySide6/plugins/platforminputcontexts', # 仮想キーボード連携、未使用
    'PySide6/qml/',                # QML ファイル群
)

# imageformats プラグインは使用フォーマットのみ残す
# PNG は Qt6Gui 組み込みのためプラグイン不要。qsvg は qdarktheme が使用するため除外不可
_keep_imageformats = {'qsvg'}


def _is_excluded(dest_name):
    name = dest_name.replace('\\', '/')
    # Linux/macOS では Qt プラグイン等が PySide6/Qt/ 配下に置かれるため層を揃える
    name = name.replace('PySide6/Qt/', 'PySide6/')
    if any(name.startswith(p) for p in _exclude_data_prefixes):
        return True
    if name.startswith('PySide6/plugins/imageformats/'):
        # qsvg.dll (Windows) / libqsvg.so (Linux) / libqsvg.dylib (macOS)
        stem = name.rsplit('/', 1)[-1].split('.', 1)[0]
        if stem.startswith('lib'):
            stem = stem[3:]
        return stem not in _keep_imageformats
    return False


a.datas = [d for d in a.datas if not _is_excluded(d[0])]

# 不要な DLL・バイナリを除去（excludes では除外しきれないもの）
_exclude_binaries = {
    'opengl32sw.dll',               # ソフトウェア OpenGL フォールバック (~20 MB)
    'Qt6Quick.dll',
    'Qt6Qml.dll',
    'Qt6QmlModels.dll',
    'Qt6QmlWorkerScript.dll',
    'Qt6QmlCompiler.dll',
    'Qt6Designer.dll',
    'Qt6DesignerComponents.dll',
    'Qt6OpenGL.dll',
    'Qt6OpenGLWidgets.dll',
    'Qt6Network.dll',
    'Qt6DBus.dll',
    'Qt6Help.dll',
    'Qt6Sql.dll',
    'Qt6Xml.dll',
    'Qt6PrintSupport.dll',
    'Qt6Pdf.dll',                   # qpdf.dll (imageformats) が依存として道連れにする
    'Qt6UiTools.dll',
    # Qt6Svg.dll — qdarktheme が使用するため除外不可
    'Qt6SvgWidgets.dll',
    'Qt6QuickControls2.dll',
    'Qt6QuickControls2Impl.dll',
    'Qt6QuickDialogs2.dll',
    'Qt6QuickDialogs2QuickImpl.dll',
    'Qt6QuickDialogs2Utils.dll',
    'Qt6QuickEffects.dll',
    'Qt6QuickLayouts.dll',
    'Qt6QuickParticles.dll',
    'Qt6QuickShapes.dll',
    'Qt6QuickTemplates2.dll',
    'Qt6QuickTimeline.dll',
    'Qt6QuickControls2Basic.dll',
    'Qt6QuickControls2BasicStyleImpl.dll',
    'Qt6QuickControls2Fusion.dll',
    'Qt6QuickControls2FusionStyleImpl.dll',
    'Qt6QuickControls2Imagine.dll',
    'Qt6QuickControls2ImagineStyleImpl.dll',
    'Qt6QuickControls2Material.dll',
    'Qt6QuickControls2MaterialStyleImpl.dll',
    'Qt6QuickControls2Universal.dll',
    'Qt6QuickControls2UniversalStyleImpl.dll',
    'Qt6QuickTest.dll',
}
# プラグイン DLL は a.binaries 側に入るため、パス prefix の除外も両方に適用する
a.binaries = [
    b for b in a.binaries
    if not _is_excluded(b[0])
    and b[0].replace('\\', '/').rsplit('/', 1)[-1] not in _exclude_binaries
]

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
