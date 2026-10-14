"""Interface de terminal (curses): menus, tela de luta em tempo real e carreira."""
from __future__ import annotations

import curses
import locale
import textwrap
import time
from datetime import date

from .batch import batch, report
from .career import CAMPS, Career
from .engine import Fight, clock_str
from .models import ATTRIBUTE_GROUPS, ATTRIBUTE_LABELS, Fighter, cm_to_ft, load_roster
from .tactics import CATEGORIES, CORNER_ACTIONS, capacity, describe_plan

KEYS = "123456789abcdef"
SPEEDS = [("lenta", 0.5), ("normal", 0.25), ("rápida", 0.1), ("muito rápida", 0.04), ("turbo", 0.0)]
PANEL_W = 46

# pares de cor
C_RED, C_BLUE, C_BIG, C_COACH, C_HINT, C_DIM, C_ROUND, C_HEAD, C_OK = range(1, 10)


def init_colors() -> None:
    curses.start_color()
    try:
        curses.use_default_colors()
        bg = -1
    except curses.error:
        bg = curses.COLOR_BLACK
    curses.init_pair(C_RED, curses.COLOR_RED, bg)
    curses.init_pair(C_BLUE, curses.COLOR_CYAN, bg)
    curses.init_pair(C_BIG, curses.COLOR_YELLOW, bg)
    curses.init_pair(C_COACH, curses.COLOR_GREEN, bg)
    curses.init_pair(C_HINT, curses.COLOR_MAGENTA, bg)
    curses.init_pair(C_DIM, curses.COLOR_WHITE, bg)
    curses.init_pair(C_ROUND, curses.COLOR_WHITE, bg)
    curses.init_pair(C_HEAD, curses.COLOR_BLACK, curses.COLOR_WHITE)
    curses.init_pair(C_OK, curses.COLOR_GREEN, bg)


def put(win, y: int, x: int, text: str, attr: int = 0, width: int | None = None) -> None:
    h, w = win.getmaxyx()
    if y < 0 or y >= h or x >= w:
        return
    maxw = (w - x) if width is None else min(width, w - x)
    if y == h - 1:
        maxw -= 1
    if maxw <= 0:
        return
    try:
        win.addstr(y, x, text[:maxw], attr)
    except curses.error:
        pass


def side_attr(side: int | None) -> int:
    if side == 0:
        return curses.color_pair(C_RED)
    if side == 1:
        return curses.color_pair(C_BLUE)
    return 0


def event_attr(ev) -> int:
    k = ev.kind
    if k == "big":
        return curses.color_pair(C_BIG) | curses.A_BOLD
    if k == "result":
        return curses.color_pair(C_BIG) | curses.A_BOLD | curses.A_REVERSE
    if k == "coach":
        return curses.color_pair(C_COACH) | curses.A_BOLD
    if k == "corner":
        return curses.color_pair(C_COACH)
    if k == "hint":
        return curses.color_pair(C_HINT) | curses.A_BOLD
    if k == "round":
        return curses.color_pair(C_ROUND) | curses.A_BOLD
    if k == "miss":
        return side_attr(ev.side) | curses.A_DIM
    if k in ("sub", "ground"):
        return side_attr(ev.side) | curses.A_BOLD
    return side_attr(ev.side)


# ====================================================================== menus genéricos
def menu(stdscr, title: str, options: list[str], subtitle: list[str] | None = None, start: int = 0) -> int | None:
    """Menu vertical com setas/Enter ou número. Retorna índice ou None (Esc)."""
    stdscr.nodelay(False)
    sel = start
    while True:
        stdscr.erase()
        h, w = stdscr.getmaxyx()
        put(stdscr, 1, 2, title, curses.A_BOLD | curses.color_pair(C_BIG))
        y = 3
        for line in subtitle or []:
            put(stdscr, y, 2, line)
            y += 1
        if subtitle:
            y += 1
        for i, opt in enumerate(options):
            key = KEYS[i] if i < len(KEYS) else " "
            attr = curses.A_REVERSE if i == sel else 0
            put(stdscr, y + i, 4, f" {key}  {opt} ", attr)
        put(stdscr, h - 1, 2, "↑↓ escolher · Enter confirmar · número atalho · Esc voltar", curses.A_DIM)
        stdscr.refresh()
        ch = stdscr.getch()
        if ch in (curses.KEY_UP, ord("k")):
            sel = (sel - 1) % len(options)
        elif ch in (curses.KEY_DOWN, ord("j")):
            sel = (sel + 1) % len(options)
        elif ch in (10, 13, curses.KEY_ENTER):
            return sel
        elif ch in (27, curses.KEY_BACKSPACE, 127):
            return None
        elif 0 <= ch < 256 and chr(ch) in KEYS[:len(options)]:
            return KEYS.index(chr(ch))


def pager(stdscr, title: str, lines: list[tuple[str, int]]) -> None:
    stdscr.nodelay(False)
    top = 0
    while True:
        stdscr.erase()
        h, w = stdscr.getmaxyx()
        put(stdscr, 0, 2, title, curses.A_BOLD | curses.color_pair(C_BIG))
        view = h - 3
        for i, (txt, attr) in enumerate(lines[top:top + view]):
            put(stdscr, 2 + i, 2, txt, attr)
        put(stdscr, h - 1, 2, "↑↓/PgUp/PgDn rolar · qualquer outra tecla volta", curses.A_DIM)
        stdscr.refresh()
        ch = stdscr.getch()
        if ch in (curses.KEY_DOWN, ord("j")):
            top = min(max(0, len(lines) - view), top + 1)
        elif ch in (curses.KEY_UP, ord("k")):
            top = max(0, top - 1)
        elif ch == curses.KEY_NPAGE:
            top = min(max(0, len(lines) - view), top + view)
        elif ch == curses.KEY_PPAGE:
            top = max(0, top - view)
        else:
            return


def message(stdscr, title: str, lines: list[str]) -> None:
    pager(stdscr, title, [(l, 0) for l in lines] + [("", 0), ("Pressione qualquer tecla.", curses.A_DIM)])


# ====================================================================== perfil
def profile_lines(f: Fighter, on: date | None = None) -> list[tuple[str, int]]:
    b = curses.A_BOLD
    rec = f.record
    out = [
        (f"{f.name} \"{f.nickname}\"", b | curses.color_pair(C_BIG)),
        (f"{f.nationality} · {f.hometown} · {f.team}", 0),
        (f"Idade {f.age(on)} · Altura {f.height_cm} cm ({cm_to_ft(f.height_cm)}) · Envergadura {f.reach_cm} cm"
         f" · Peso {f.weight_lbs} lb ({f.division}) · Base {'ortodoxa' if f.stance == 'orthodox' else 'canhota'}", 0),
        (f"Cartel {rec}  —  vitórias: {rec.wins_by['ko']} KO/TKO, {rec.wins_by['sub']} fin., {rec.wins_by['dec']} dec."
         f"  |  derrotas: {rec.losses_by['ko']} KO/TKO, {rec.losses_by['sub']} fin., {rec.losses_by['dec']} dec.", 0),
        (f"Estilo: {f.base_style} · Geral {f.overall}", 0),
        ("", 0),
        ("ESTATÍSTICAS OFICIAIS (UFC)", b),
    ]
    u = f.ufc_stats
    out += [
        (f"  Golpes sig. por minuto {u['slpm']:.2f} · Precisão {u['str_acc']:.0%} · Absorvidos/min {u['sapm']:.2f}"
         f" · Defesa {u['str_def']:.0%}", 0),
        (f"  Quedas {u['td_landed']}/{u['td_attempted']} ({u['td_acc']:.0%}) · Defesa de queda {u['td_def']:.0%}"
         f" · Finalizações/15min {u['sub_avg']} · Knockdowns/15min {u['kd_avg']} · Tempo médio {u['avg_fight_time']}", 0),
        (f"  Por alvo: cabeça {u['sig_by_target']['head']}, corpo {u['sig_by_target']['body']}, perna {u['sig_by_target']['leg']}"
         f"  ·  Por posição: em pé {u['sig_by_position']['standing']}, clinch {u['sig_by_position']['clinch']},"
         f" chão {u['sig_by_position']['ground']}", 0),
        ("", 0),
        ("ATRIBUTOS DO JOGO", b),
    ]
    for group, keys in ATTRIBUTE_GROUPS.items():
        out.append((f"  {group}", b))
        row = ""
        for i, k in enumerate(keys):
            v = f.attributes[k]
            bar = "█" * (v // 10) + "░" * (10 - v // 10)
            cell = f"{ATTRIBUTE_LABELS[k]:<24}{v:>3} {bar}"
            row += cell.ljust(44)
            if i % 2 == 1:
                out.append(("    " + row, 0))
                row = ""
        if row:
            out.append(("    " + row, 0))
    out += [("", 0), ("CARTEL COMPLETO", b)]
    for h in f.fight_history:
        tag = {"W": "V", "L": "D", "D": "E"}[h["result"]]
        attr = curses.color_pair(C_OK) if tag == "V" else (curses.color_pair(C_RED) if tag == "D" else 0)
        out.append((f"  {tag}  {h['date']}  {h['opponent']:<26} {h['method']:<38} R{h['round']} {h['time']:<5} {h['event']}", attr))
    return out


# ====================================================================== tela de luta
class FightScreen:
    def __init__(self, stdscr, fight: Fight, coached: int | None, title: str):
        self.s = stdscr
        self.f = fight
        self.coached = coached
        self.title = title
        self.cat: int | None = None
        self.paused = coached is not None
        self.speed = 1
        self.scroll = 0
        self.corner_done = False
        self.mode = "luta"           # luta | intervalo | fim
        self.confirm_quit = False
        self.last_auto = 0.0
        self.started = False

    # -------------------------------------------------------------- desenho
    def draw(self) -> None:
        s = self.s
        s.erase()
        h, w = s.getmaxyx()
        f = self.f
        a, b = f.fs
        sp = SPEEDS[self.speed][0]
        state = "PAUSADO" if self.paused else sp
        if f.finished:
            state = "FIM"
        elif f.intermission:
            state = "INTERVALO"
        head = f" {self.title} │ R{f.round}/{f.rounds} {clock_str(f.clock)} │ {f.position_text()} │ {state} "
        put(s, 0, 0, head.ljust(w), curses.color_pair(C_HEAD) | curses.A_BOLD)
        put(s, 1, 1, f"● {a.name} ({a.f.record})", curses.color_pair(C_RED) | curses.A_BOLD)
        put(s, 1, w // 2, f"● {b.name} ({b.f.record})", curses.color_pair(C_BLUE) | curses.A_BOLD)
        put(s, 2, 1, f.status_line(0), curses.color_pair(C_RED), w // 2 - 2)
        put(s, 2, w // 2, f.status_line(1), curses.color_pair(C_BLUE))
        put(s, 3, 0, "─" * w, curses.A_DIM)

        pw = PANEL_W if w >= 100 else max(30, w // 3)
        lw = w - pw - 1
        top, bottom = 4, h - 2
        for y in range(top, bottom + 1):
            put(s, y, lw, "│", curses.A_DIM)
        self.draw_log(top, bottom, lw)
        self.draw_panel(top, bottom, lw + 2, pw - 2)
        help_txt = "Espaço pausa · +/- velocidade · ↑↓ rolar log · Q sair"
        if self.coached is not None:
            help_txt = "Número: categoria/comando · Esc voltar · " + help_txt
        put(s, h - 1, 1, help_txt, curses.A_DIM)
        s.refresh()

    def draw_log(self, top: int, bottom: int, width: int) -> None:
        lines = []
        for ev in self.f.log:
            if ev.kind == "hint" and self.coached is not None and ev.side != self.coached:
                continue
            prefix = f"R{ev.rnd} {clock_str(ev.t)}  "
            wrapped = textwrap.wrap(ev.text, max(10, width - len(prefix) - 1)) or [""]
            for i, part in enumerate(wrapped):
                lines.append(((prefix if i == 0 else " " * len(prefix)) + part, event_attr(ev)))
        view = bottom - top + 1
        end = len(lines) - self.scroll
        start = max(0, end - view)
        for i, (txt, attr) in enumerate(lines[start:end]):
            put(self.s, top + i, 1, txt, attr, width - 1)
        if self.scroll:
            put(self.s, top, width - 14, f" ↑ rolado {self.scroll} ", curses.A_REVERSE)

    def draw_panel(self, top: int, bottom: int, x: int, width: int) -> None:
        s = self.s
        y = top
        B = curses.A_BOLD
        f = self.f
        if f.finished:
            put(s, y, x, "RESULTADO", B | curses.color_pair(C_BIG))
            y += 1
            for line in textwrap.wrap(f.result.summary([fs.name for fs in f.fs]), width):
                put(s, y, x, line, B)
                y += 1
            y += 1
            for line in f.scorecards_text():
                for part in textwrap.wrap(line, width):
                    put(s, y, x, part)
                    y += 1
            y += 1
            put(s, y, x, "Enter: estatísticas completas", curses.A_DIM)
            return
        if self.coached is None:
            self.draw_stats(y, x, width)
            if f.intermission:
                put(s, bottom, x, "Enter: próximo round", B | curses.color_pair(C_BIG))
            return
        me = f.fs[self.coached]
        if f.intermission and self.cat is None and not self.in_cmd_menu:
            put(s, y, x, "INTERVALO — você está no córner", B | curses.color_pair(C_BIG))
            y += 2
            put(s, y, x, "Ação do córner (uma por intervalo):", B)
            y += 1
            for i, (_, label) in enumerate(CORNER_ACTIONS):
                attr = curses.A_DIM if self.corner_done else 0
                for j, part in enumerate(textwrap.wrap(f"{i + 1}  {label}", width)):
                    put(s, y, x + (3 if j else 0), part, attr)
                    y += 1
            y += 1
            put(s, y, x, "C  Dar instruções táticas", 0)
            y += 1
            put(s, y, x, "T  Jogar a toalha", curses.color_pair(C_RED))
            y += 1
            put(s, y, x, "Enter  Começar o próximo round", B | curses.color_pair(C_COACH))
            y += 2
            y = self.draw_plan(me, y, x, width, bottom)
            return
        if self.cat is None:
            put(s, y, x, f"COMANDOS — córner de {me.name}", B | curses.color_pair(C_COACH))
            y += 1
            for i, cat in enumerate(CATEGORIES):
                put(s, y, x, f"{cat.key}  {cat.label}")
                y += 1
            if f.intermission:
                put(s, y, x, "Esc  voltar ao intervalo", curses.A_DIM)
                y += 1
            y += 1
            self.draw_plan(me, y, x, width, bottom)
        else:
            cat = CATEGORIES[self.cat]
            put(s, y, x, f"{cat.label.upper()}  (Esc volta)", B | curses.color_pair(C_COACH))
            y += 1
            for i, cmd in enumerate(cat.commands):
                lvl = "·" * cmd.level
                for j, part in enumerate(textwrap.wrap(f"{KEYS[i]}  {cmd.label} {lvl}", width)):
                    if y > bottom:
                        break
                    put(s, y, x + (3 if j else 0), part)
                    y += 1
            y += 1
            put(s, y, x, "· genérico ·· direcionado ··· técnico"[:width], curses.A_DIM)
            y += 2
            self.draw_plan(me, y, x, width, bottom)

    def draw_plan(self, me, y: int, x: int, width: int, bottom: int) -> int:
        put(self.s, y, x, "PLANO ATUAL", curses.A_BOLD)
        y += 1
        lines = describe_plan(me.plan) or ["(estilo natural do lutador)"]
        cap = capacity(me.a("fight_iq"))
        n = me.plan.specific_count()
        attr = curses.color_pair(C_RED) if n > cap else curses.A_DIM
        put(self.s, y, x, f"Instruções: {n}/{cap} (QI de luta)", attr)
        y += 1
        for line in lines:
            for part in textwrap.wrap("- " + line, width):
                if y > bottom:
                    return y
                put(self.s, y, x, part, curses.color_pair(C_COACH))
                y += 1
        return y

    def draw_stats(self, y: int, x: int, width: int) -> None:
        a, b = self.f.fs
        put(self.s, y, x, "ESTATÍSTICAS", curses.A_BOLD)
        y += 1
        cw = (width - 18) // 2
        put(self.s, y, x + 18, a.name[:cw].ljust(cw), curses.color_pair(C_RED) | curses.A_BOLD)
        put(self.s, y, x + 18 + cw, b.name[:cw], curses.color_pair(C_BLUE) | curses.A_BOLD)
        y += 1
        for label, va, vb in self.f.stats_table():
            put(self.s, y, x, label[:17])
            put(self.s, y, x + 18, va[:cw - 1], curses.color_pair(C_RED))
            put(self.s, y, x + 18 + cw, vb[:cw], curses.color_pair(C_BLUE))
            y += 1

    # -------------------------------------------------------------- entrada
    def handle_key(self, ch: int) -> bool:
        """Retorna False para sair da tela."""
        f = self.f
        if ch == -1:
            return True
        if self.confirm_quit:
            self.confirm_quit = False
            if ch in (ord("s"), ord("S"), ord("y")):
                return False
            f.emit("(Saída cancelada.)", "info")
            return True
        if f.finished:
            if ch in (10, 13, curses.KEY_ENTER, ord("q"), ord("Q"), 27):
                return False
            return True
        if ch in (ord("q"), ord("Q")):
            self.confirm_quit = True
            f.emit("Sair da luta? Pressione S para confirmar.", "result")
            return True
        if ch in (ord(" "), ord("p"), ord("P")):
            self.paused = not self.paused
            return True
        if ch in (ord("+"), ord("=")):
            self.speed = min(len(SPEEDS) - 1, self.speed + 1)
            return True
        if ch in (ord("-"), ord("_")):
            self.speed = max(0, self.speed - 1)
            return True
        if ch in (curses.KEY_UP,):
            self.scroll += 1
            return True
        if ch in (curses.KEY_DOWN,):
            self.scroll = max(0, self.scroll - 1)
            return True
        if ch == curses.KEY_PPAGE:
            self.scroll += 10
            return True
        if ch == curses.KEY_NPAGE:
            self.scroll = max(0, self.scroll - 10)
            return True
        if f.intermission and ch in (10, 13, curses.KEY_ENTER) and self.cat is None:
            f.next_round()
            self.corner_done = False
            self.in_cmd_menu = False
            if self.coached is not None:
                self.paused = False
            return True
        if self.coached is None:
            return True
        c = chr(ch) if 0 <= ch < 256 else ""
        if f.intermission and self.cat is None and not self.in_cmd_menu:
            if c in "1234" and c and not self.corner_done:
                f.corner_action(self.coached, CORNER_ACTIONS[int(c) - 1][0])
                self.corner_done = True
            elif c in ("c", "C"):
                self.in_cmd_menu = True
            elif c in ("t", "T"):
                f.stop_by_corner(self.coached)
            return True
        if ch in (27, curses.KEY_BACKSPACE, 127, ord("0")):
            if self.cat is not None:
                self.cat = None
            elif f.intermission:
                self.in_cmd_menu = False
            return True
        if self.cat is None:
            for i, cat in enumerate(CATEGORIES):
                if c == cat.key:
                    self.cat = i
            return True
        cmds = CATEGORIES[self.cat].commands
        if c and c in KEYS[:len(cmds)]:
            f.issue_command(self.coached, cmds[KEYS.index(c)].id)
            self.cat = None
            self.scroll = 0
        return True

    in_cmd_menu = False

    # -------------------------------------------------------------- loop
    def run(self) -> Fight:
        s = self.s
        s.nodelay(True)
        s.keypad(True)
        curses.curs_set(0)
        f = self.f
        if not f.log:
            f.emit(f"Bem-vindos ao {self.title}! {f.fs[0].f.name} (canto vermelho) contra {f.fs[1].f.name} (canto azul), "
                   f"{f.rounds} rounds.", "round")
            if self.coached is not None:
                f.emit("Você está no córner de " + f.fs[self.coached].f.name +
                       ". Monte o plano de jogo agora (luta pausada) e aperte Espaço para começar.", "coach", self.coached)
            f.emit("ROUND 1!", "round")
        acc = 0.0
        last = time.monotonic()
        while True:
            # entrada
            while True:
                ch = s.getch()
                if ch == -1:
                    break
                if ch == curses.KEY_RESIZE:
                    continue
                if not self.handle_key(ch):
                    s.nodelay(False)
                    return f
            # avanço do tempo
            now = time.monotonic()
            dt = now - last
            last = now
            if not self.paused and not f.finished and not f.intermission and not self.confirm_quit:
                delay = SPEEDS[self.speed][1]
                if delay == 0:
                    for _ in range(25):
                        f.step()
                        if f.finished or f.intermission:
                            break
                else:
                    acc += dt
                    steps = 0
                    while acc >= delay and steps < 50:
                        acc -= delay
                        f.step()
                        steps += 1
                        if f.finished or f.intermission:
                            acc = 0
                            break
            else:
                acc = 0
            if f.intermission and self.coached is None:
                if not self.last_auto:
                    self.last_auto = now
                elif now - self.last_auto > 3 and not self.paused:
                    f.next_round()
                    self.last_auto = 0.0
            self.draw()
            time.sleep(0.03)


def stats_screen(stdscr, fight: Fight) -> None:
    a, b = fight.fs
    lines = [(fight.result.summary([a.name, b.name]), curses.A_BOLD | curses.color_pair(C_BIG)), ("", 0)]
    lines += [(l, 0) for l in fight.scorecards_text()]
    lines += [("", 0), (f"{'':<20}{a.name:<24}{b.name:<24}", curses.A_BOLD)]
    for label, va, vb in fight.stats_table():
        lines.append((f"{label:<20}{va:<24}{vb:<24}", 0))
    lines += [("", 0), ("POR ROUND (golpes sig. conectados/tentados)", curses.A_BOLD)]
    for i in range(len(a.rounds)):
        ra, rb = a.rounds[i], b.rounds[i]
        lines.append((f"  R{i + 1}: {a.name} {ra['sig_land']}/{ra['sig_att']}  ·  {b.name} {rb['sig_land']}/{rb['sig_att']}", 0))
    pager(stdscr, "ESTATÍSTICAS DA LUTA", lines)


# ====================================================================== fluxos
def pick_fighter(stdscr, roster: dict, title: str, exclude: str | None = None) -> Fighter | None:
    fs = [f for f in roster.values() if f.id != exclude]
    opts = [f"{f.name:<20} {str(f.record):<9} {f.division:<12} Geral {f.overall}" for f in fs]
    i = menu(stdscr, title, opts)
    return None if i is None else fs[i]


def quick_fight(stdscr, roster: dict) -> None:
    a = pick_fighter(stdscr, roster, "Luta rápida — canto VERMELHO")
    if not a:
        return
    b = pick_fighter(stdscr, roster, "Luta rápida — canto AZUL", exclude=a.id)
    if not b:
        return
    r = menu(stdscr, "Número de rounds", ["3 rounds", "5 rounds (luta principal / cinturão)"])
    if r is None:
        return
    rounds = 3 if r == 0 else 5
    m = menu(stdscr, f"{a.name} vs {b.name} — modo", [
        f"Ser o treinador de {a.name}",
        f"Ser o treinador de {b.name}",
        "Assistir (IA nos dois córneres)",
        "Simulação instantânea (só o resultado)",
        "Simular 500 lutas (validação estatística)",
    ])
    if m is None:
        return
    if m == 4:
        stdscr.erase()
        put(stdscr, 1, 2, "Simulando 500 lutas...")
        stdscr.refresh()
        txt = report(a, b, batch(a, b, 500, rounds))
        message(stdscr, "Validação estatística", txt.split("\n"))
        return
    coached = {0: 0, 1: 1}.get(m)
    fight = Fight(a, b, rounds=rounds, coached=coached)
    if m == 3:
        while not fight.finished:
            fight.step()
            if fight.intermission:
                fight.next_round()
        lines = [(f"R{e.rnd} {clock_str(e.t)}  {e.text}", event_attr(e)) for e in fight.log if e.kind not in ("miss",)]
        pager(stdscr, f"{a.short} vs {b.short} — narração", lines)
        stats_screen(stdscr, fight)
        return
    FightScreen(stdscr, fight, coached, "UFC SIM").run()
    if fight.finished:
        stats_screen(stdscr, fight)


def career_mode(stdscr, roster: dict) -> None:
    car = Career.load()
    if car:
        i = menu(stdscr, "Modo carreira", [f"Continuar carreira ({car.fighter.name}, {car.fighter.record})", "Nova carreira"])
        if i is None:
            return
        if i == 1:
            car = None
    if car is None:
        f = pick_fighter(stdscr, roster, "Nova carreira — escolha seu lutador")
        if not f:
            return
        car = Career.new(f.id)
        car.save()
    while True:
        fi = car.fighter
        sub = [f"Data: {car.date} · Idade {fi.age(car.today)} · Cartel {fi.record} · Dinheiro US$ {car.money:,}".replace(",", "."),
               f"Popularidade {car.popularity}/100 · Eventos disputados {len(car.fights)}"]
        if car.suspended_until and date.fromisoformat(car.suspended_until) > car.today:
            sub.append(f"SUSPENSÃO MÉDICA até {car.suspended_until}")
        i = menu(stdscr, f"CARREIRA — Treinador de {fi.name}", [
            "Marcar próxima luta", "Ver lutador", "Histórico na carreira", "Salvar e voltar"], sub)
        if i is None or i == 3:
            car.save()
            return
        if i == 1:
            pager(stdscr, "Perfil", profile_lines(fi, car.today))
        elif i == 2:
            lines = [(f"{h['result']}  {h['date']}  {h['opponent']:<24} {h['method']:<36} R{h['round']} {h['time']}  {h['event']}", 0)
                     for h in car.fights] or [("Nenhuma luta ainda.", 0)]
            pager(stdscr, "Histórico na carreira", lines)
        elif i == 0:
            ok, why = car.can_fight()
            if not ok:
                j = menu(stdscr, why, ["Esperar a liberação médica", "Voltar"])
                if j == 0:
                    car.date = car.suspended_until
                    car.suspended_until = None
                continue
            opps = car.available_opponents()
            if not opps:
                message(stdscr, "Sem adversários", ["Não há adversários disponíveis no elenco."])
                continue
            opts = [f"{o.name:<20} {str(o.record):<8} Geral {o.overall}" for o in opps]
            j = menu(stdscr, "Adversários oferecidos pela UFC", opts)
            if j is None:
                continue
            opp = opps[j]
            r = menu(stdscr, "Formato", ["3 rounds", "5 rounds (luta principal)"])
            if r is None:
                continue
            rounds = 3 if r == 0 else 5
            keys = list(CAMPS)
            k = menu(stdscr, f"Camp de treinamento para {opp.name} (8 semanas)", [CAMPS[c][0] for c in keys])
            if k is None:
                continue
            scouted = car.set_camp(keys[k], opp)
            if scouted:
                message(stdscr, f"Relatório de estudo: {opp.name}", ["- " + s for s in scouted] +
                        ["", "Dica: use os contra-ataques (categoria 7) para punir esses vícios."])
            fight = car.make_fight(opp, rounds)
            FightScreen(stdscr, fight, 0, f"UFC SIM {car.event_no}").run()
            if not fight.finished:
                message(stdscr, "Luta abandonada", ["A luta não terminou; nada foi registrado."])
                continue
            stats_screen(stdscr, fight)
            msgs = car.apply_result(fight, opp, rounds)
            car.save()
            message(stdscr, "Pós-luta", [fight.result.summary([fs.name for fs in fight.fs]), ""] + msgs)


def fighters_screen(stdscr, roster: dict) -> None:
    while True:
        f = pick_fighter(stdscr, roster, "Lutadores")
        if not f:
            return
        pager(stdscr, "Perfil", profile_lines(f))


def help_screen(stdscr) -> None:
    lines = [
        "COMO JOGAR",
        "",
        "A tela de luta tem o log em tempo real (esquerda) e os comandos do córner (direita).",
        "Aperte o número de uma categoria e depois o número do comando. Esc volta.",
        "",
        "Os comandos montam o PLANO DE JOGO do lutador. Cada categoria ocupa um 'slot'",
        "(estratégia, alvo, arma, movimentação, defesa, contra-ataques, grappling, chão).",
        "",
        "Quanto mais específico o comando, maior o bônus de execução:",
        "  ·   genérico     — muda tendências (ex.: 'pressione')",
        "  ··  direcionado  — muda alvo/área (ex.: 'trabalhe o corpo', 'ande para a direita')",
        "  ··· técnico      — técnica exata ou reação a um gatilho (ex.: 'ele entrar → uppercut')",
        "",
        "Leia o log! Linhas '◆ Leitura' revelam vícios do adversário. Contra-atacar o gatilho",
        "certo com a resposta certa dá um bônus grande.",
        "",
        "Movimentação importa: circular para o lado da mão forte do adversário é perigoso.",
        "Contra um ortodoxo, ande para a DIREITA; contra um canhoto, para a ESQUERDA.",
        "",
        "Limite: o lutador só guarda um número de instruções (depende do QI de luta).",
        "Passar do limite ou mudar o plano toda hora reduz a execução. Machucado, ele não ouve.",
        "",
        "No intervalo você escolhe uma ação de córner e pode reajustar o plano com calma.",
        "",
        "Teclas: Espaço pausa · +/- velocidade · ↑↓ rolam o log · Q sai da luta.",
    ]
    message(stdscr, "Ajuda", lines)


def main(stdscr) -> None:
    locale.setlocale(locale.LC_ALL, "")
    init_colors()
    curses.curs_set(0)
    stdscr.keypad(True)
    roster = load_roster()
    while True:
        i = menu(stdscr, "UFC SIM — simulador de MMA", [
            "Luta rápida", "Modo carreira", "Lutadores", "Como jogar", "Sair"],
            [f"{len(roster)} lutadores no elenco · dados oficiais UFC atualizados em 2026-10-13"])
        if i is None or i == 4:
            return
        if i == 0:
            quick_fight(stdscr, roster)
        elif i == 1:
            career_mode(stdscr, roster)
        elif i == 2:
            fighters_screen(stdscr, roster)
        elif i == 3:
            help_screen(stdscr)


def run() -> None:
    curses.wrapper(main)
