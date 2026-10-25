"""PyInstaller 用エントリスクリプト。

パッケージ内モジュールは相対 import を使うため、main.py を直接スクリプトとして
実行できない。PyInstaller にはこのランチャーを渡し、絶対 import 経由で起動する。
"""

from Filtflow.main import main

if __name__ == "__main__":
    main()
