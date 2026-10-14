"""Servidor web local: o relógio da luta corre no servidor e o navegador dá as instruções."""
from __future__ import annotations

import itertools
import json
import threading
import time
import webbrowser
from datetime import date
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .batch import batch, report
from .career import CAMPS, Career
from .engine import ROUND_SECONDS, Fight, clock_str
from .models import ATTRIBUTE_GROUPS, ATTRIBUTE_LABELS, load_roster
from .tactics import AUTO, CATEGORIES, COMMANDS, CORNER_ACTIONS, GamePlan, capacity, describe_plan

WEB_DIR = Path(__file__).resolve().parent.parent / "web"
SPEEDS = [1, 2, 4, 8, 16]          # segundos de luta por segundo real
DEFAULT_SPEED = 4
INTERMISSION_REAL = 60.0          # intervalo (segundos reais) quando você é o treinador
INTERMISSION_WATCH = 6.0

# Gritos rápidos (como no Football Manager)
SHOUTS = ["st_pressao", "st_distancia", "st_contra", "st_ritmo_alto", "st_poupar", "df_cabeca",
          "df_guarda", "st_finish", "st_recover", "mv_centro"]


_ids = itertools.count(1)


class Session:
    def __init__(self, fight: Fight, coached: int | None, title: str, career: bool = False,
                 opponent_id: str | None = None):
        self.id = next(_ids)
        self.fight = fight
        self.coached = coached
        self.title = title
        self.career = career
        self.opponent_id = opponent_id
        self.mode = "pre"              # pre | live | end
        self.paused = False
        self.speed = DEFAULT_SPEED
        self.acc = 0.0
        self.last = time.monotonic()
        self.inter_left: float | None = None
        self.corner_done = False
        self.career_applied: list[str] | None = None
        f = fight
        f.emit(f"Bem-vindos ao {title}! {f.fs[0].f.name} (canto vermelho) contra {f.fs[1].f.name} "
               f"(canto azul), {f.rounds} rounds.", "round")
        if coached is not None:
            f.emit(f"Você é o treinador de {f.fs[coached].f.name}. Defina a estratégia inicial e comece a luta.",
                   "coach", coached)

    def start(self) -> None:
        if self.mode == "pre":
            self.mode = "live"
            self.last = time.monotonic()
            self.fight.emit("ROUND 1! Valendo!", "round")

    def advance(self) -> None:
        now = time.monotonic()
        dt = min(now - self.last, 1.0)   # aba em segundo plano não "pula" a luta
        self.last = now
        f = self.fight
        if self.mode != "live":
            return
        if f.finished:
            self.mode = "end"
            return
        if self.paused:
            return
        if f.intermission:
            if self.inter_left is None:
                self.inter_left = INTERMISSION_REAL if self.coached is not None else INTERMISSION_WATCH
                self.corner_done = False
            self.inter_left -= dt
            if self.inter_left <= 0:
                self.next_round()
            return
        self.acc += dt * self.speed
        n = min(int(self.acc), 120)
        self.acc -= n
        for _ in range(n):
            f.step()
            if f.finished or f.intermission:
                self.acc = 0.0
                break
        if f.finished:
            self.mode = "end"

    def next_round(self) -> None:
        if self.fight.intermission:
            self.fight.next_round()
            self.inter_left = None
            self.corner_done = False

    # ------------------------------------------------------------------ estado
    def state(self, since: int) -> dict:
        f = self.fight
        events = []
        for i, ev in enumerate(f.log[since:], start=since):
            if ev.kind == "hint" and self.coached is not None and ev.side != self.coached:
                continue
            if ev.kind == "hint" and self.coached is None:
                continue
            events.append({"rnd": ev.rnd, "t": clock_str(ev.t), "text": ev.text, "kind": ev.kind, "side": ev.side})
        fighters = []
        for fs in f.fs:
            fighters.append({
                "id": fs.f.id, "name": fs.name, "full": fs.f.name, "nickname": fs.f.nickname,
                "record": str(fs.f.record), "stamina": round(fs.stamina), "max_stamina": round(fs.max_stamina),
                "head": round(fs.head), "body": round(fs.body), "legs": round(fs.legs),
                "rocked": fs.rock_level, "cut": round(fs.cut), "stance": fs.stance,
                "intent": f.intent(fs.idx), "plan": plan_items(fs.plan),
                "instructions": fs.plan.specific_count(), "capacity": capacity(fs.a("fight_iq")),
            })
        a, b = f.fs
        rounds = [{"a": [ra["sig_land"], ra["sig_att"], ra["td_land"], ra["kd"]],
                   "b": [rb["sig_land"], rb["sig_att"], rb["td_land"], rb["kd"]]}
                  for ra, rb in zip(a.rounds, b.rounds)]
        result = None
        if f.finished and f.result:
            result = {"summary": f.result.summary([a.name, b.name]), "winner": f.result.winner,
                      "method": f.result.method, "cards": f.scorecards_text()}
        active = active_commands(f.fs[self.coached].plan) if self.coached is not None else []
        return {
            "id": self.id, "active": active, "title": self.title, "mode": self.mode, "paused": self.paused, "speed": self.speed, "speeds": SPEEDS,
            "round": f.round, "rounds": f.rounds, "clock": clock_str(f.clock), "clock_s": f.clock,
            "round_len": ROUND_SECONDS, "position": ("Intervalo · lutadores nos córneres" if f.intermission and not f.finished else f.position_text()), "intermission": f.intermission,
            "inter_left": None if self.inter_left is None else max(0, round(self.inter_left)),
            "corner_done": self.corner_done, "coached": self.coached, "career": self.career,
            "career_applied": self.career_applied,
            "finished": f.finished, "result": result, "fighters": fighters,
            "stats": f.stats_table(), "by_round": rounds, "events": events, "next": len(f.log),
        }


def active_commands(plan: GamePlan) -> list[str]:
    out = []
    for c in COMMANDS.values():
        if c.slot == "counter":
            if plan.counters.get(c.value[0]) == c.value[1]:
                out.append(c.id)
        elif c.slot in ("finish", "recover"):
            if getattr(plan, c.slot):
                out.append(c.id)
        elif c.slot in GamePlan.SLOTS and c.value != AUTO and getattr(plan, c.slot) == c.value:
            out.append(c.id)
    return out


def plan_items(plan: GamePlan) -> list[dict]:
    """Itens do plano com o slot, para o botão de remover na interface."""
    items = []
    texts = describe_plan(plan)
    slots = [s for s in ("posture", "pace", "target", "weapon", "movement", "stance", "defense", "grapple",
                         "takedown", "clinch", "ground_top", "sub_pref", "ground_bottom")
             if getattr(plan, s) != "auto"]
    slots += [f"counter:{t}" for t in plan.counters]
    if plan.finish:
        slots.append("finish")
    if plan.recover:
        slots.append("recover")
    for slot, txt in zip(slots, texts):
        items.append({"slot": slot, "text": txt})
    return items


def fighter_payload(f, on: date | None = None) -> dict:
    d = f.to_dict()
    d["age"] = f.age(on)
    d["overall"] = f.overall
    d["record_str"] = str(f.record)
    return d


class App:
    def __init__(self):
        self.lock = threading.Lock()
        self.session: Session | None = None
        self.roster = load_roster()

    # ------------------------------------------------------------------ rotas
    def get(self, path: str, q: dict) -> tuple[int, dict]:
        if path == "/api/meta":
            cats = [{"key": c.key, "label": c.label,
                     "commands": [{"id": m.id, "label": m.label, "level": m.level, "shout": m.shout} for m in c.commands]}
                    for c in CATEGORIES]
            return 200, {"categories": cats, "corner": [{"id": i, "label": l} for i, l in CORNER_ACTIONS],
                         "shouts": [{"id": s, "label": COMMANDS[s].label, "shout": COMMANDS[s].shout} for s in SHOUTS],
                         "camps": [{"id": k, "label": v[0]} for k, v in CAMPS.items()],
                         "attr_groups": ATTRIBUTE_GROUPS, "attr_labels": ATTRIBUTE_LABELS}
        if path == "/api/roster":
            return 200, {"fighters": [fighter_payload(f) for f in self.roster.values()]}
        if path == "/api/state":
            if not self.session:
                return 200, {"mode": "none"}
            self.session.advance()
            return 200, self.session.state(int(q.get("since", ["0"])[0]))
        if path == "/api/career":
            car = Career.load()
            if not car:
                return 200, {"exists": False}
            return 200, self.career_payload(car)
        if path == "/api/batch":
            a = self.roster[q["red"][0]]
            b = self.roster[q["blue"][0]]
            n = min(2000, int(q.get("n", ["300"])[0]))
            rounds = int(q.get("rounds", ["5"])[0])
            return 200, {"report": report(a, b, batch(a, b, n, rounds))}
        return 404, {"error": "rota desconhecida"}

    def post(self, path: str, body: dict) -> tuple[int, dict]:
        s = self.session
        if path == "/api/fight/new":
            red, blue = self.roster[body["red"]], self.roster[body["blue"]]
            coached = body.get("coached")
            fight = Fight(red, blue, rounds=int(body.get("rounds", 3)), coached=coached)
            self.session = Session(fight, coached, "UFC SIM")
            if coached is None:
                self.session.start()
            return 200, {"ok": True}
        if path == "/api/career/new":
            car = Career.new(body["fighter"])
            car.save()
            return 200, self.career_payload(car)
        if path == "/api/career/fight":
            car = Career.load()
            if not car:
                return 400, {"error": "sem carreira"}
            ok, why = car.can_fight()
            if not ok:
                if body.get("wait"):
                    car.date = car.suspended_until
                    car.suspended_until = None
                    car.save()
                else:
                    return 400, {"error": why}
            opp = self.roster[body["opponent"]]
            scouted = car.set_camp(body["camp"], opp)
            car.save()
            fight = car.make_fight(opp, int(body.get("rounds", 3)))
            self.session = Session(fight, 0, f"UFC SIM {car.event_no}", career=True, opponent_id=opp.id)
            return 200, {"ok": True, "scouted": scouted}
        if not s:
            return 400, {"error": "nenhuma luta em andamento"}
        s.advance()
        f = s.fight
        side = s.coached
        if path == "/api/fight/start":
            s.start()
        elif path == "/api/fight/command":
            if side is None or f.finished:
                return 400, {"error": "sem córner"}
            f.issue_command(side, body["id"], immediate=(s.mode == "pre"))
        elif path == "/api/fight/clear":
            if side is not None:
                f.clear_slot(side, body["slot"])
                f.emit(f"» Córner de {f.fs[side].name}: \"Esquece isso!\"", "coach", side)
        elif path == "/api/fight/pause":
            s.paused = bool(body.get("paused", not s.paused))
        elif path == "/api/fight/speed":
            if int(body["speed"]) in SPEEDS:
                s.speed = int(body["speed"])
        elif path == "/api/fight/corner":
            if side is not None and f.intermission and not s.corner_done:
                f.corner_action(side, body["id"])
                s.corner_done = True
        elif path == "/api/fight/next_round":
            s.next_round()
        elif path == "/api/fight/towel":
            if side is not None and not f.finished:
                f.stop_by_corner(side)
                s.mode = "end"
        elif path == "/api/fight/abandon":
            self.session = None
            return 200, {"ok": True}
        elif path == "/api/career/complete":
            if not (s.career and f.finished):
                return 400, {"error": "luta de carreira não terminou"}
            if s.career_applied is None:
                car = Career.load()
                opp = self.roster[s.opponent_id]
                s.career_applied = car.apply_result(f, opp, f.rounds)
                car.save()
            return 200, {"messages": s.career_applied}
        else:
            return 404, {"error": "rota desconhecida"}
        return 200, {"ok": True}

    def career_payload(self, car: Career) -> dict:
        ok, why = car.can_fight()
        return {"exists": True, "fighter": fighter_payload(car.fighter, car.today), "date": car.date,
                "money": car.money, "popularity": car.popularity, "fights": car.fights,
                "suspended": None if ok else why,
                "opponents": [{"id": o.id, "name": o.name, "record": str(o.record), "overall": o.overall}
                              for o in car.available_opponents()]}


def make_handler(app: App):
    class Handler(SimpleHTTPRequestHandler):
        def __init__(self, *a, **kw):
            super().__init__(*a, directory=str(WEB_DIR), **kw)

        def log_message(self, *args):  # silencioso
            pass

        def _json(self, code: int, payload: dict) -> None:
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            u = urlparse(self.path)
            if u.path.startswith("/api/"):
                try:
                    with app.lock:
                        code, payload = app.get(u.path, parse_qs(u.query))
                except Exception as e:  # noqa: BLE001
                    code, payload = 500, {"error": repr(e)}
                return self._json(code, payload)
            return super().do_GET()

        def do_POST(self):
            u = urlparse(self.path)
            n = int(self.headers.get("Content-Length") or 0)
            try:
                body = json.loads(self.rfile.read(n) or b"{}")
                with app.lock:
                    code, payload = app.post(u.path, body)
            except Exception as e:  # noqa: BLE001
                code, payload = 500, {"error": repr(e)}
            return self._json(code, payload)

        def end_headers(self):
            if not self.path.startswith("/api/"):
                self.send_header("Cache-Control", "no-cache")
            super().end_headers()

    return Handler


def serve(port: int = 8765, open_browser: bool = True) -> None:
    app = App()
    server = ThreadingHTTPServer(("127.0.0.1", port), make_handler(app))
    url = f"http://127.0.0.1:{port}/"
    print(f"UFC SIM rodando em {url}  (Ctrl+C para encerrar)")
    if open_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nAté a próxima!")
    finally:
        server.server_close()
