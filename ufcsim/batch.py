"""Simulação em lote para validar o motor contra as estatísticas reais."""
from __future__ import annotations

from collections import Counter

from .engine import ROUND_SECONDS, Fight
from .models import Fighter


def run_fight(f1: Fighter, f2: Fighter, rounds: int, seed: int | None = None) -> Fight:
    fight = Fight(f1, f2, rounds=rounds, seed=seed)
    while not fight.finished:
        fight.step()
        if fight.intermission:
            fight.next_round()
    return fight


def batch(f1: Fighter, f2: Fighter, n: int = 500, rounds: int = 5, seed: int = 0) -> dict:
    wins = Counter()
    methods = Counter()
    finish_rounds = Counter()
    agg = [Counter(), Counter()]
    minutes = 0.0
    for i in range(n):
        fight = run_fight(f1, f2, rounds, seed + i)
        r = fight.result
        key = r.winner if r.winner is not None else "empate"
        wins[key] += 1
        methods[(key, r.method)] += 1
        if r.method != "DEC":
            finish_rounds[r.rnd] += 1
        minutes += ((r.rnd - 1) * ROUND_SECONDS + r.time) / 60
        for idx, fs in enumerate(fight.fs):
            for k in fs.rs:
                agg[idx][k] += fs.total(k)
    return {"n": n, "wins": wins, "methods": methods, "finish_rounds": finish_rounds, "agg": agg, "minutes": minutes}


def report(f1: Fighter, f2: Fighter, res: dict) -> str:
    n = res["n"]
    names = [f1.short, f2.short]
    lines = [f"=== {f1.name} vs {f2.name} — {n} lutas ==="]
    for idx in (0, 1):
        w = res["wins"][idx]
        by = {m: res["methods"][(idx, m)] for m in ("KO", "TKO", "SUB", "DEC")}
        lines.append(f"{names[idx]:>10}: {w / n:6.1%} vitórias  | KO {by['KO'] / n:5.1%}  TKO {by['TKO'] / n:5.1%}"
                     f"  SUB {by['SUB'] / n:5.1%}  DEC {by['DEC'] / n:5.1%}")
    lines.append(f"{'Empates':>10}: {res['wins']['empate'] / n:6.1%}")
    fr = res["finish_rounds"]
    lines.append("Finalizações por round: " + ", ".join(f"R{k}: {fr[k]}" for k in sorted(fr)))
    mins = res["minutes"]
    lines.append(f"Duração média: {mins / n:.1f} min")
    lines.append("")
    lines.append(f"{'':>10}  {'SLpM':>5} {'Prec.':>6} {'SApM':>5} {'Def.':>5} {'KD/15':>6} {'TD/15':>6} {'TD%':>5} {'Sub/15':>6}  Cabeça/Corpo/Perna   (real: SLpM, Prec, SApM, Def)")
    for idx, f in enumerate((f1, f2)):
        a, o = res["agg"][idx], res["agg"][1 - idx]
        slpm = a["sig_land"] / mins
        acc = a["sig_land"] / max(1, a["sig_att"])
        sapm = o["sig_land"] / mins
        dfn = 1 - o["sig_land"] / max(1, o["sig_att"])
        kd = a["kd"] / mins * 15
        td = a["td_land"] / mins * 15
        tdp = a["td_land"] / max(1, a["td_att"])
        sub = a["sub_att"] / mins * 15
        tot = max(1, a["head"] + a["body"] + a["leg"])
        u = f.ufc_stats
        lines.append(f"{names[idx]:>10}  {slpm:5.2f} {acc:6.0%} {sapm:5.2f} {dfn:5.0%} {kd:6.2f} {td:6.2f} {tdp:5.0%} {sub:6.2f}"
                     f"  {a['head'] / tot:.0%}/{a['body'] / tot:.0%}/{a['leg'] / tot:.0%}"
                     f"           ({u['slpm']}, {u['str_acc']:.0%}, {u['sapm']}, {u['str_def']:.0%})")
    return "\n".join(lines)
