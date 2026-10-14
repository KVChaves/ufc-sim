"""UFC SIM — simulador de MMA com modo treinador.

Uso:
  python3 main.py                         abre o jogo no navegador (http://127.0.0.1:8765)
  python3 main.py --terminal              versão antiga em terminal (curses)
  python3 main.py --texto [A B] [-r 5]    narra uma luta em texto puro (sem interface)
  python3 main.py --lote 500 [A B] [-r 5] simula N lutas e compara com as estatísticas reais
"""
import argparse
import sys

from ufcsim.batch import batch, report, run_fight
from ufcsim.engine import clock_str
from ufcsim.models import load_roster


def main() -> None:
    ap = argparse.ArgumentParser(description="UFC SIM")
    ap.add_argument("lutadores", nargs="*", help="ids dos lutadores (ex.: topuria holloway)")
    ap.add_argument("-r", "--rounds", type=int, default=5, choices=(3, 5))
    ap.add_argument("--texto", action="store_true", help="narra uma luta em texto puro")
    ap.add_argument("--lote", type=int, metavar="N", help="simula N lutas e mostra estatísticas")
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("--terminal", action="store_true", help="interface antiga em terminal")
    ap.add_argument("--porta", type=int, default=8765)
    ap.add_argument("--sem-navegador", action="store_true", help="não abre o navegador automaticamente")
    args = ap.parse_args()

    roster = load_roster()
    ids = args.lutadores or ["topuria", "holloway"]
    if len(ids) != 2 or any(i not in roster for i in ids):
        sys.exit(f"Informe dois lutadores entre: {', '.join(roster)}")
    a, b = roster[ids[0]], roster[ids[1]]

    if args.lote:
        print(report(a, b, batch(a, b, args.lote, args.rounds, seed=args.seed or 0)))
    elif args.texto:
        fight = run_fight(a, b, args.rounds, args.seed)
        for ev in fight.log:
            print(f"R{ev.rnd} {clock_str(ev.t)}  {ev.text}")
        print()
        for line in fight.scorecards_text():
            print(line)
        for label, va, vb in fight.stats_table():
            print(f"{label:<20}{va:<22}{vb}")
    elif args.terminal:
        from ufcsim.tui import run
        run()
    else:
        from ufcsim.web import serve
        serve(args.porta, open_browser=not args.sem_navegador)


if __name__ == "__main__":
    main()
