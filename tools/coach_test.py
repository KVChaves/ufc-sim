"""Mede o impacto de planos de treinador: python3 tools/coach_test.py [n]"""
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ufcsim.engine import Fight  # noqa: E402
from ufcsim.models import load_roster  # noqa: E402

PLANS = {
    "sem comandos": [],
    "genérico (pressão + tudo)": ["st_pressao", "st_tudo"],
    "ruim (andar p/ mão forte, trocar no bolso)": ["mv_esquerda", "st_pressao", "w_2-3-up"],
    "específico (anti-Topuria)": ["mv_direita", "df_mao_forte", "ct_entra_upper", "ct_hook_cross",
                                   "w_corpo-cabeca", "st_ritmo_alto", "df_sprawl"],
}


def run(cmds, n, side=1, seed=1000):
    roster = load_roster()
    wins = Counter()
    for i in range(n):
        f = Fight(roster["topuria"], roster["holloway"], rounds=5, seed=seed + i, coached=side)
        for c in cmds:
            f.issue_command(side, c)
        while not f.finished:
            f.step()
            if f.intermission:
                f.next_round()
        r = f.result
        wins["vitória" if r.winner == side else ("empate" if r.winner is None else "derrota")] += 1
    return wins


n = int(sys.argv[1]) if len(sys.argv) > 1 else 300
for name, cmds in PLANS.items():
    w = run(cmds, n)
    print(f"Holloway com plano {name:<45} vitórias {w['vitória'] / n:6.1%}")
