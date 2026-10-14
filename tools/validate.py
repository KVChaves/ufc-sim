"""Valida o motor: python3 tools/validate.py [n] [rounds] [id1] [id2]"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ufcsim.batch import batch, report  # noqa: E402
from ufcsim.models import load_roster  # noqa: E402

n = int(sys.argv[1]) if len(sys.argv) > 1 else 300
rounds = int(sys.argv[2]) if len(sys.argv) > 2 else 5
a = sys.argv[3] if len(sys.argv) > 3 else "topuria"
b = sys.argv[4] if len(sys.argv) > 4 else "holloway"
roster = load_roster()
print(report(roster[a], roster[b], batch(roster[a], roster[b], n, rounds)))
