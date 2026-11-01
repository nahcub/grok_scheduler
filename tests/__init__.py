# 저장소 루트에서 `python -m unittest`만으로 돌도록 src를 경로에 넣는다(설치 없이).
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
