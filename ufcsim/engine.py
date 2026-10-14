"""Motor da luta: simulação segundo a segundo.

Estados: em pé (com distância, grade e lateralidade), clinch, chão (com
posições) e finalização em andamento. Cada segundo cada lutador pode agir de
acordo com estilo + plano de jogo (instruções do córner).
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass, field

from .models import Fighter
from .moves import (COMBOS, CURTA, FOLLOW_UPS, GNP_ACC, GNP_MULT, GROUND_POSITIONS, KICKS, LONGE,
                    MEDIA, PUNCHES, RANGE_NAMES, STRIKES, SUBMISSIONS)
from .tactics import AUTO, COMMANDS, GamePlan, apply_command, capacity

ROUND_SECONDS = 300


def sigmoid(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))


def logit(p: float) -> float:
    p = min(max(p, 1e-4), 1 - 1e-4)
    return math.log(p / (1 - p))


def sub_art(name: str, prep: str = "") -> str:
    """Artigo/contração correta para o nome da finalização (a guilhotina, o triângulo...)."""
    fem = not name.startswith(("katagatame", "mata-leão", "triângulo"))
    art = "a" if fem else "o"
    if prep == "em":
        art = "na" if fem else "no"
    elif prep == "de":
        art = "da" if fem else "do"
    return f"{art} {name}"


ACKS = ("ouve o córner", "acena para o córner", "faz sinal de positivo", "entende o recado")

POSTURE_TXT = {"pressao": "Pressionando", "contra": "Esperando para contra-atacar", "distancia": "Lutando de fora",
               "equilibrado": "Trocação equilibrada", "tudo": "Tudo ou nada", "seguro": "Lutando seguro"}
MOVE_TXT = {"direita": "Circulando para a direita", "esquerda": "Circulando para a esquerda",
            "cortar": "Cortando o octógono", "centro": "Buscando o centro", "entra_sai": "Entra e sai"}
DEF_TXT = {"guarda_alta": "Guarda alta", "cabeca": "Mexendo a cabeça", "checar": "Checando chutes",
           "sprawl": "Atento às quedas", "mao_forte": "Vigiando a mão forte", "finalizacao": "Defendendo finalizações"}
TARGET_TXT = {"cabeca": "Mirando a cabeça", "corpo": "Trabalhando o corpo", "pernas": "Atacando as pernas"}


def clock_str(sec: int) -> str:
    return f"{sec // 60}:{sec % 60:02d}"


@dataclass
class Event:
    rnd: int
    t: int
    text: str
    kind: str = "info"       # info, hit, miss, big, ground, sub, coach, hint, round, result, corner
    side: int | None = None  # lutador "dono" do evento (quem age)


def new_round_stats() -> dict:
    return {"sig_att": 0, "sig_land": 0, "head": 0, "body": 0, "leg": 0, "dist": 0, "clinch": 0,
            "ground": 0, "total_att": 0, "total_land": 0, "kd": 0, "td_att": 0, "td_land": 0,
            "sub_att": 0, "near_sub": 0, "ctrl": 0, "dmg": 0.0, "rev": 0}


class FighterState:
    def __init__(self, f: Fighter, idx: int):
        self.f = f
        self.idx = idx
        self.name = f.short
        self.head = 100.0
        self.body = 100.0
        self.legs = 100.0
        self.stamina = 100.0
        self.max_stamina = 100.0
        self.rocked = 0.0
        self.rock_level = 0
        self.cut = 0.0
        self.cage = 0.0
        self.ref_meter = 0.0
        self.stance = f.stance
        self.plan = GamePlan()
        self.pending: list[tuple[int, object]] = []
        self.cmd_times: list[int] = []
        self.tactical_round = False
        self.motivated = 0.0
        self.rounds: list[dict] = [new_round_stats()]
        self.thrown: dict[str, int] = {}
        self.hint_cooldown: dict[str, int] = {}
        self.flags: set[str] = set()

    # --- atributos efetivos -------------------------------------------------
    def a(self, key: str) -> float:
        return self.f.attributes[key]

    @property
    def gas(self) -> float:
        """Fator de rendimento pelo cansaço (0.55 a 1.0)."""
        return 0.55 + 0.45 * (self.stamina / 100.0)

    @property
    def rs(self) -> dict:
        return self.rounds[-1]

    def total(self, key: str) -> float:
        return sum(r[key] for r in self.rounds)

    def spend(self, amount: float) -> None:
        cardio = self.a("cardio")
        self.stamina = max(0.0, self.stamina - amount * (1.7 - cardio / 100 * 1.0))


@dataclass
class Result:
    winner: int | None
    method: str          # KO, TKO, SUB, DEC, DRAW
    detail: str
    rnd: int
    time: int
    cards: list = field(default_factory=list)

    def summary(self, names: list[str]) -> str:
        if self.winner is None:
            return f"Empate ({self.detail})"
        w = names[self.winner]
        if self.method == "DEC":
            return f"{w} vence por decisão {self.detail}"
        return f"{w} vence por {self.method} ({self.detail}) — R{self.rnd} {clock_str(self.time)}"


class Fight:
    def __init__(self, f1: Fighter, f2: Fighter, rounds: int = 3, seed: int | None = None,
                 coached: int | None = None):
        self.rng = random.Random(seed)
        self.fs = [FighterState(f1, 0), FighterState(f2, 1)]
        self.rounds = rounds
        self.round = 1
        self.clock = 0
        self.phase = "em_pe"           # em_pe | clinch | chao
        self.range = LONGE
        self.ground: dict | None = None    # {"top": idx, "pos": str, "idle": int}
        self.clinch: dict | None = None    # {"ctrl": idx, "cage": idx|None, "secs": int}
        self.sub: dict | None = None
        self.coached = coached
        self.finished = False
        self.result: Result | None = None
        self.intermission = False
        self.out: list[Event] = []
        self.log: list[Event] = []
        self.quiet = 0
        self.cards: list[list[tuple[int, int]]] = [[], [], []]
        self.judge_style = [self.rng.uniform(-0.25, 0.25) for _ in range(3)]  # >0 valoriza grappling
        self.last_round_events: list[Event] = []

    # ------------------------------------------------------------------ util
    def other(self, fs: FighterState) -> FighterState:
        return self.fs[1 - fs.idx]

    def emit(self, text: str, kind: str = "info", side: int | None = None) -> None:
        ev = Event(self.round, self.clock, text, kind, side)
        self.out.append(ev)
        self.log.append(ev)
        if kind not in ("miss",):
            self.quiet = 0

    def mark(self) -> tuple[int, int]:
        return len(self.out), len(self.log)

    def emit_at(self, mark: tuple[int, int], text: str, kind: str = "info", side: int | None = None) -> None:
        """Insere um evento antes dos eventos emitidos depois de `mark` (ex.: narra o golpe antes do knockdown)."""
        ev = Event(self.round, self.clock, text, kind, side)
        self.out.insert(mark[0], ev)
        self.log.insert(mark[1], ev)
        self.quiet = 0

    def chance(self, p: float) -> bool:
        return self.rng.random() < p

    def adherence(self, fs: FighterState) -> float:
        if fs.tactical_round:
            return 1.0
        iq = fs.a("fight_iq")
        adh = 0.55 + iq / 250
        over = fs.plan.specific_count() - capacity(iq)
        if over > 0:
            adh -= 0.08 * over
        recent = [t for t in fs.cmd_times if self.abs_time() - t < 20]
        if len(recent) >= 4:
            adh -= 0.04 * (len(recent) - 3)
        if fs.rock_level >= 2:
            adh -= 0.3
        return max(0.2, min(1.0, adh))

    def abs_time(self) -> int:
        return (self.round - 1) * ROUND_SECONDS + self.clock

    def follows(self, fs: FighterState) -> bool:
        return self.chance(self.adherence(fs))

    def slot(self, fs: FighterState, name: str) -> str:
        """Valor efetivo de um slot do plano (pode cair no 'auto' se não seguir a instrução)."""
        v = getattr(fs.plan, name)
        if v == AUTO:
            return AUTO
        return v if self.follows(fs) else AUTO

    def power_side_safe(self, mover: FighterState, opp: FighterState) -> str:
        """Lado 'seguro' para circular: longe da mão forte do adversário."""
        return "direita" if opp.stance == "orthodox" else "esquerda"

    # ------------------------------------------------------------------ comandos
    def issue_command(self, side: int, cmd_id: str, immediate: bool = False) -> None:
        cmd = COMMANDS[cmd_id]
        fs = self.fs[side]
        immediate = immediate or self.intermission
        delay = 0 if immediate else 1 + self.rng.randint(0, 2)
        fs.pending.append((self.abs_time() + delay, cmd))
        fs.cmd_times.append(self.abs_time())
        self.emit(f"» Córner de {fs.name}: \"{cmd.shout}\"", "coach", side)
        if immediate:
            self._apply_pending(fs, quiet=True)

    def clear_slot(self, side: int, slot: str) -> None:
        """Remove uma instrução do plano (volta ao estilo natural naquele aspecto)."""
        fs = self.fs[side]
        plan = fs.plan
        if slot.startswith("counter:"):
            plan.counters.pop(slot.split(":", 1)[1], None)
        elif slot in ("finish", "recover"):
            setattr(plan, slot, False)
        elif slot in GamePlan.SLOTS:
            setattr(plan, slot, AUTO)
            if slot == "stance":
                fs.stance = fs.f.stance
        fs.flags.discard("confuso")

    def _apply_pending(self, fs: FighterState, quiet: bool = False) -> None:
        now = self.abs_time()
        keep = []
        for when, cmd in fs.pending:
            if when > now:
                keep.append((when, cmd))
                continue
            if fs.rock_level >= 2 and not self.intermission:
                keep.append((now + 2, cmd))   # machucado, não escuta agora
                if "surdo" not in fs.flags:
                    fs.flags.add("surdo")
                    self.emit(f"{fs.name} está machucado e não consegue ouvir o córner.", "hint", fs.idx)
                continue
            apply_command(fs.plan, cmd)
            if not quiet:
                self.emit(f"{fs.name} {self.rng.choice(ACKS)}: {cmd.label[0].lower() + cmd.label[1:]}.", "ack", fs.idx)
            if cmd.slot == "stance" and cmd.value != AUTO and fs.stance != cmd.value:
                fs.stance = cmd.value
                self.emit(f"{fs.name} troca para a base {'canhota' if fs.stance == 'southpaw' else 'ortodoxa'}.", "info", fs.idx)
            if cmd.slot == "movement" and cmd.value in ("direita", "esquerda") and self.phase == "em_pe":
                opp = self.other(fs)
                if cmd.value != self.power_side_safe(fs, opp):
                    self.emit(f"{fs.name} passa a circular para o lado da mão forte de {opp.name}.", "hint", fs.idx)
            if fs.plan.specific_count() > capacity(fs.a("fight_iq")) and "confuso" not in fs.flags:
                fs.flags.add("confuso")
                self.emit(f"{fs.name} parece sobrecarregado com tantas instruções.", "hint", fs.idx)
        fs.pending = keep
        if fs.rock_level < 2:
            fs.flags.discard("surdo")

    def corner_action(self, side: int, action: str) -> None:
        fs = self.fs[side]
        if action == "respirar":
            fs.stamina = min(fs.max_stamina, fs.stamina + 12)
            self.emit(f"No córner de {fs.name}: gelo na nuca e respiração controlada.", "corner", side)
        elif action == "corte":
            fs.cut = max(0.0, fs.cut - 35)
            fs.head = min(100.0, fs.head + 4)
            self.emit(f"O cutman trabalha no rosto de {fs.name}.", "corner", side)
        elif action == "motivar":
            fs.motivated = 1.0
            self.emit(f"O córner de {fs.name} levanta o ânimo: \"Esse round é teu!\"", "corner", side)
        elif action == "tatico":
            fs.tactical_round = True
            self.emit(f"O córner de {fs.name} desenha o plano com calma. Instruções claras.", "corner", side)

    # ------------------------------------------------------------------ ciclo
    def step(self) -> list[Event]:
        self.out = []
        if self.finished or self.intermission:
            return self.out
        self.clock += 1
        self.quiet += 1
        for fs in self.fs:
            self._apply_pending(fs)
            self._tick_status(fs)

        if self.sub:
            self._sub_tick()
        elif self.phase == "em_pe":
            self._standing_tick()
        elif self.phase == "clinch":
            self._clinch_tick()
        else:
            self._ground_tick()

        if not self.finished:
            self._check_ref()
        if not self.finished and self.quiet > 9 and self.chance(0.16):
            self._ambient()
        if not self.finished and self.clock in (240, 290) and self.round == self.rounds:
            if self.clock == 240:
                self.emit("Último minuto da luta!", "round")
            else:
                self.emit("Dez segundos!", "round")
        elif not self.finished and self.clock == 290:
            self.emit("Dez segundos no round!", "round")
        if not self.finished and self.clock >= ROUND_SECONDS:
            self._end_round()
        return self.out

    def _tick_status(self, fs: FighterState) -> None:
        if fs.rocked > 0:
            rate = 0.9 + fs.a("recovery") / 100
            if self.phase == "clinch" or (self.phase == "chao" and fs.plan.ground_bottom == "amarrar"):
                rate *= 1.6
            if fs.plan.recover and self.phase == "em_pe" and self.range == LONGE:
                rate *= 1.5
            fs.rocked -= rate
            if fs.rocked <= 0:
                fs.rocked = 0
                fs.rock_level = 0
                fs.ref_meter = 0
                self.emit(f"{fs.name} parece ter se recuperado.", "info", fs.idx)
            elif fs.rock_level == 3 and fs.rocked < 9:
                fs.rock_level = 2
            elif fs.rock_level == 2 and fs.rocked < 4:
                fs.rock_level = 1
        fs.ref_meter *= 0.88
        # recuperação de fôlego
        if self.phase == "em_pe":
            regen = 0.2
        elif self.phase == "clinch":
            regen = 0.05
        else:
            top = self.ground and self.ground["top"] == fs.idx
            regen = 0.12 if top else -0.12
        pace = fs.plan.pace
        if pace == "poupar":
            regen += 0.12
        regen *= fs.a("cardio") / 90
        fs.stamina = max(0.0, min(fs.max_stamina, fs.stamina + regen))

    # ------------------------------------------------------------------ em pé
    def _desired_range(self, fs: FighterState) -> int:
        opp = self.other(fs)
        if fs.rock_level >= 2:
            if fs.a("wrestling") + fs.a("clinch_control") > 150 or fs.plan.recover:
                return CURTA if fs.plan.recover else LONGE
            return LONGE
        if opp.rock_level >= 1 and (fs.plan.finish or self.chance(fs.a("aggression") / 120)):
            return CURTA
        posture = self.slot(fs, "posture")
        if posture in ("pressao", "tudo"):
            return CURTA
        if posture in ("distancia", "seguro"):
            return LONGE
        if posture == "contra":
            return MEDIA
        if self.slot(fs, "movement") == "entra_sai":
            return LONGE
        return int(fs.f.style["preferred_range"])

    def _pressure_power(self, fs: FighterState) -> float:
        p = fs.a("footwork") * fs.gas + fs.f.style["pressure"] * 12
        mv = self.slot(fs, "movement")
        if mv == "cortar":
            p += 14
        if self.slot(fs, "posture") in ("pressao", "tudo"):
            p += 6
        return p - (100 - fs.legs) * 0.25

    def _evade_power(self, fs: FighterState, opp: FighterState) -> float:
        p = fs.a("footwork") * fs.gas - fs.cage * 18 - (100 - fs.legs) * 0.35 - fs.rock_level * 8
        mv = self.slot(fs, "movement")
        if mv in ("direita", "esquerda", "entra_sai"):
            p += 6
        return p

    def _movement(self) -> None:
        a, b = self.fs
        da, db = self._desired_range(a), self._desired_range(b)
        for fs in self.fs:
            opp = self.other(fs)
            mv = self.slot(fs, "movement")
            if mv in ("direita", "esquerda", "centro"):
                fs.cage = max(0.0, fs.cage - (0.07 if mv == "centro" else 0.04))
                fs.spend(0.08)
            else:
                fs.cage = max(0.0, fs.cage - 0.01)
        if not self.chance(0.32):
            return
        if da == db:
            if self.range < da:
                self.range += 1
            elif self.range > da:
                self.range -= 1
            return
        presser, runner = (a, b) if da > db else (b, a)
        want_close = max(da, db)
        want_far = min(da, db)
        diff = self._pressure_power(presser) - self._evade_power(runner, presser)
        circling = self.slot(runner, "movement") in ("direita", "esquerda", "centro")
        if self.chance(sigmoid(diff / 12)):
            if self.range < want_close:
                self.range += 1
                runner.cage = min(1.0, runner.cage + (0.06 if circling else 0.14))
                presser.spend(0.3)
                self._entrance(presser, runner)
            else:
                runner.cage = min(1.0, runner.cage + (0.01 if circling else 0.04))
            if runner.cage >= 0.75 and "grade" not in runner.flags:
                runner.flags.add("grade")
                self.emit(f"{presser.name} empurra {runner.name} até a grade.", "info", presser.idx)
        elif self.range > want_far:
            self.range -= 1
            runner.spend(0.25)
        if runner.cage < 0.5:
            runner.flags.discard("grade")

    def _entrance(self, presser: FighterState, defender: FighterState) -> None:
        """Quem entra na distância pode ser recebido com contra-ataque."""
        resp = defender.plan.counters.get("entrada")
        if resp and resp in STRIKES and self.follows(defender) and defender.rock_level < 2:
            if self.chance(0.30 + defender.a("counter") / 500):
                bonus = 0.35 + self._habit_bonus(presser, "entrada", resp)
                self._habit_hint(presser, "entrada")
                self._counter_strike(defender, presser, resp, bonus, "na entrada")
                return
        self._habit_hint(presser, "entrada")

    def _attack_rate(self, fs: FighterState) -> float:
        opp = self.other(fs)
        apm = 0.17 * fs.a("volume") - 1
        rate = apm / 60 / fs.f.style["combo_length"]
        pace = self.slot(fs, "pace")
        rate *= {"alto": 1.3, "poupar": 0.75}.get(pace, 1.0)
        posture = self.slot(fs, "posture")
        rate *= {"pressao": 1.1, "contra": 0.75, "distancia": 0.85, "tudo": 1.35, "seguro": 0.8}.get(posture, 1.0)
        rate *= 0.5 + 0.5 * fs.stamina / 100
        if fs.rock_level:
            rate *= 0.45 if fs.rock_level >= 2 else 0.75
        if opp.rock_level:
            rate *= 1.15 + fs.a("aggression") / 300 + (0.5 if fs.plan.finish else 0)
        rate *= {LONGE: 0.55, MEDIA: 1.0, CURTA: 1.2}[self.range]
        rate *= 1 + fs.motivated * 0.1
        return rate

    def _standing_tick(self) -> None:
        self._movement()
        self._maybe_switch_stance()
        a, b = self.fs
        ra, rb = self._attack_rate(a), self._attack_rate(b)
        acts = [fs for fs, r in ((a, ra), (b, rb)) if self.chance(r)]
        if not acts:
            return
        if len(acts) == 2:
            wa = ra * a.a("hand_speed")
            wb = rb * b.a("hand_speed")
            if not self.chance(wa / (wa + wb)):
                acts.reverse()
            if not self.chance(0.45):
                acts.pop()
        for att in acts:
            if self.finished or self.phase != "em_pe" or self.sub:
                break
            self._standing_action(att, self.other(att))

    def _maybe_switch_stance(self) -> None:
        for fs in self.fs:
            plan_stance = fs.plan.stance
            if plan_stance != AUTO:
                continue
            if self.chance(fs.f.style.get("stance_switching", 0) * 0.025):
                fs.stance = "southpaw" if fs.stance == "orthodox" else "orthodox"
                self.emit(f"{fs.name} troca de base para {'canhoto' if fs.stance == 'southpaw' else 'ortodoxo'}.", "info", fs.idx)
            elif fs.stance != fs.f.stance and self.chance(0.04):
                fs.stance = fs.f.stance

    def _standing_action(self, att: FighterState, d: FighterState) -> None:
        grapple = self.slot(att, "grapple")
        w_td = att.f.style.get("grapple_intent", 0.03)
        w_clinch = 0.02 + (0.025 if self.range == CURTA else 0)
        if grapple == "quedas":
            w_td = 0.18 + att.a("wrestling") / 500
        elif grapple == "clinch":
            w_clinch = 0.3
        elif grapple == "evitar":
            w_td, w_clinch = 0.0, 0.0
        if att.rock_level >= 2 and att.plan.recover:
            w_clinch += 0.6
        if d.rock_level >= 2 and att.a("wrestling") > 75:
            w_td += 0.08
        if d.cage > 0.7:
            w_clinch += 0.05
            w_td *= 1.3
        roll = self.rng.random() * (1 + w_td + w_clinch)
        if roll < w_td:
            self._takedown(att, d)
        elif roll < w_td + w_clinch:
            self._clinch_attempt(att, d)
        else:
            self._strike_sequence(att, d)

    # ---- escolha de golpes
    def _target_for(self, att: FighterState, sid: str) -> str:
        s = STRIKES[sid]
        opts = list(s.targets)
        if len(opts) == 1:
            return opts[0]
        tm = att.f.style["target_mix"]
        w = {"head": tm["head"], "body": tm["body"]}
        tgt = self.slot(att, "target")
        if tgt == "corpo":
            w["body"] *= 3
        elif tgt == "cabeca":
            w["head"] *= 2
        d = self.other(att)
        if d.rock_level:
            w["head"] *= 2
        opts = [o for o in opts if o in w]
        return self.rng.choices(opts, [w[o] for o in opts])[0]

    def _organic_combo(self, att: FighterState) -> list:
        mix = dict(att.f.style["strike_mix"])
        tgt = self.slot(att, "target")
        if tgt == "pernas":
            for k in ("calf_kick", "leg_kick"):
                mix[k] = mix.get(k, 0) * 3 + 4
        elif tgt == "corpo":
            mix["body_kick"] = mix.get("body_kick", 0) * 2 + 2
        if att.legs < 55:
            for k in KICKS:
                if k in mix:
                    mix[k] *= 0.4
        for k in list(mix):
            s = STRIKES[k]
            if s.best_range == CURTA and self.range < MEDIA:
                mix[k] *= 0.4
            if s.kind == "kick" and self.range == CURTA:
                mix[k] *= 0.3
            if k == "knee" and self.range != CURTA:
                mix[k] *= 0.2
        posture = self.slot(att, "posture")
        if posture == "tudo":
            for k in ("overhand", "hook", "cross", "head_kick"):
                if k in mix:
                    mix[k] *= 1.6
        keys = [k for k in mix if mix[k] > 0]
        first = self.rng.choices(keys, [mix[k] for k in keys])[0]
        seq = [(first, self._target_for(att, first))]
        mean = att.f.style["combo_length"] + (0.4 if self.slot(att, "pace") == "alto" else 0)
        p_more = 1 - 1 / mean
        while len(seq) < 5 and self.chance(p_more * att.gas ** 0.5):
            fu = FOLLOW_UPS.get(seq[-1][0], {})
            opts = [k for k in fu if k in STRIKES]
            if not opts:
                break
            weights = [fu[k] * (1 + mix.get(k, 0) / 20) for k in opts]
            nxt = self.rng.choices(opts, weights)[0]
            seq.append((nxt, self._target_for(att, nxt)))
        return seq

    def _choose_combo(self, att: FighterState) -> tuple[list, bool, str | None]:
        """Retorna (sequência, é_foco_do_córner, id_combo)."""
        weapon = att.plan.weapon
        if weapon != AUTO and self.chance(0.65 * self.adherence(att)):
            if weapon in COMBOS:
                return list(COMBOS[weapon][1]), True, weapon
            seq = [(weapon, self._target_for(att, weapon))]
            fu = FOLLOW_UPS.get(weapon, {})
            if fu and self.chance(0.4):
                nxt = self.rng.choices(list(fu), list(fu.values()))[0]
                seq.append((nxt, self._target_for(att, nxt)))
            return seq, True, None
        return self._organic_combo(att), False, None

    # ---- resolução de golpes
    def _hit_chance(self, att: FighterState, d: FighterState, sid: str, target: str, pos: int,
                    focus: bool, bonus: float, where: str) -> float:
        s = STRIKES[sid]
        base_acc = s.targets[target][0]
        x = logit(base_acc)
        skill = att.a(s.skill) * 0.5 + att.a("accuracy") * 0.5
        x += (skill - 83) / 22
        if target == "head":
            dskill = d.a("head_movement")
        elif target == "body":
            dskill = (d.a("head_movement") + d.a("footwork")) / 2
        else:
            dskill = (d.a("footwork") + d.a("fight_iq")) / 2
        x -= (dskill * (0.7 + 0.3 * d.gas) - 80) / 22
        x += (att.a("hand_speed") - d.a("hand_speed")) / 45 if s.kind == "punch" else 0
        ddef = self.slot(d, "defense")
        if ddef == "guarda_alta":
            x += -0.4 if (target == "head" and s.kind == "punch") else (0.15 if target == "body" else 0)
        elif ddef == "cabeca" and target == "head":
            x -= 0.28
            d.spend(0.15)
        elif ddef == "mao_forte" and s.side == "rear" and s.power:
            x -= 0.45
        elif ddef == "checar" and target == "leg":
            x -= 0.3
        if focus:
            x += 0.25
        x += bonus
        x -= 0.12 * pos
        if where == "em_pe":
            mv = self.slot(d, "movement")
            if mv in ("direita", "esquerda") and s.side == "rear":
                x += -0.2 if mv == self.power_side_safe(d, att) else 0.15
            x += 0.18 if d.cage > 0.7 else 0
            if att.stance != d.stance and s.side == "rear" and (sid == "cross" or sid == "body_kick"):
                x += 0.1
            if sid in ("jab", "cross", "teep") and self.range <= MEDIA:
                x += (att.f.reach_cm - d.f.reach_cm) / 10 * 0.12
        x += (att.stamina - 70) / 200 - (d.stamina - 70) / 250
        x += 0.3 * d.rock_level - 0.45 * att.rock_level
        x += d.cut / 250
        return sigmoid(x)

    def _damage(self, att: FighterState, sid: str, target: str, clean: bool, mult: float = 1.0) -> float:
        s = STRIKES[sid]
        base = s.targets[target][1]
        pf = (att.a("power") / 80) ** (1.8 if s.power else 0.7)
        dmg = base * pf * self.rng.lognormvariate(0, 0.33) * (0.75 + 0.25 * att.stamina / 100) * mult
        if clean:
            dmg *= 1.7
        return dmg

    def _land(self, att: FighterState, d: FighterState, sid: str, target: str, dmg: float,
              where: str, clean: bool) -> str | None:
        """Aplica o dano. Retorna 'ko', 'kd', 'rocked' ou None."""
        rs = att.rs
        rs["sig_land"] += 1
        rs["total_land"] += 1
        rs[{"head": "head", "body": "body", "leg": "leg"}[target]] += 1
        rs[{"em_pe": "dist", "clinch": "clinch", "chao": "ground"}[where]] += 1
        weight = {"head": 1.0, "body": 0.8, "leg": 0.65}[target]
        rs["dmg"] += dmg * weight
        if d.rock_level:
            d.ref_meter += dmg * (1 + 0.3 * (d.rock_level - 1)) * (1.2 if where == "chao" else 1.0)
        s = STRIKES[sid]
        if target == "head":
            d.head = max(0.0, d.head - dmg * 0.20 * (1.2 - d.a("chin") / 250))
            cut_p = 0.010 * dmg / 6 * (3.0 if s.kind == "elbow" else 1.0)
            if self.chance(cut_p):
                d.cut = min(100.0, d.cut + self.rng.uniform(15, 35))
                if d.cut > 30 and "corte" not in d.flags:
                    d.flags.add("corte")
                    self.emit(f"Corte! {d.name} sangra no supercílio.", "big", att.idx)
            return self._stun_check(att, d, dmg, sid)
        if target == "body":
            d.body = max(0.0, d.body - dmg * 0.55 * (90 / d.a("body_toughness")))
            d.spend(dmg * 0.45)
            vuln = 1 + (100 - d.body) / 80
            stun = dmg * vuln / (0.35 + d.a("body_toughness") / 100)
            if stun > 19 and self.chance(sigmoid((stun - 25) / 2.5)):
                self.emit(f"NO FÍGADO! {d.name} se dobra de dor!", "big", att.idx)
                return self._hurt(att, d, 3 if self.chance(0.5) else 2)
            return None
        # perna
        d.legs = max(0.0, d.legs - dmg * 0.6 * (85 / d.a("leg_toughness")))
        if d.legs < 45 and "manca" not in d.flags:
            d.flags.add("manca")
            self.emit(f"{d.name} está mancando! A perna de base está comprometida.", "big", att.idx)
        if d.legs < 6:
            self._finish(att.idx, "TKO", f"chutes na perna — {d.name} não consegue ficar de pé")
            return "ko"
        return None

    def _stun_check(self, att: FighterState, d: FighterState, dmg: float, sid: str) -> str | None:
        vuln = 1 + (100 - d.head) / 140 + 0.2 * d.rock_level + (1 - d.stamina / 100) * 0.25
        chin = d.a("chin") / 80
        stun = dmg * vuln / chin
        r = self.rng.random()
        if r < sigmoid((stun - 31) / 1.5):
            label = STRIKES[sid].label(att.stance)
            self.emit(f"NOCAUTE! {att.name} apaga {d.name} com {self._art(label)}!", "big", att.idx)
            self._finish(att.idx, "KO", label)
            return "ko"
        if r < sigmoid((stun - 24) / 1.5):
            return self._hurt(att, d, 3)
        if r < sigmoid((stun - 17) / 1.5):
            return self._hurt(att, d, 2 if stun > 19 else 1)
        return None

    def _hurt(self, att: FighterState, d: FighterState, level: int) -> str:
        if level == 3:
            att.rs["kd"] += 1
            d.rock_level = 3
            d.rocked = max(d.rocked, self.rng.uniform(13, 20))
            self.emit(f"KNOCKDOWN! {d.name} vai ao chão!", "big", att.idx)
            if self.phase != "chao":
                follow = 0.3 + att.a("aggression") / 300 + (0.25 if att.plan.finish else 0) \
                    + (att.a("ground_strikes") - 70) / 200
                if self.chance(follow):
                    self.phase = "chao"
                    self.clinch = None
                    self.ground = {"top": att.idx, "pos": self.rng.choice(["meia-guarda", "guarda", "cem-quilos"]), "idle": 0}
                    self.emit(f"{att.name} pula em cima para o ground and pound!", "ground", att.idx)
                else:
                    self.phase = "em_pe"
                    self.range = MEDIA
                    self.emit(f"{att.name} manda {d.name} levantar. {d.name} se levanta grogue.", "info", att.idx)
            return "kd"
        if level >= d.rock_level:
            d.rock_level = level
            d.rocked = max(d.rocked, self.rng.uniform(5, 10) if level == 2 else self.rng.uniform(3, 6))
        if level == 2:
            self.emit(self.rng.choice([f"{d.name} SENTIU! As pernas balançam!",
                                       f"{d.name} está machucado! Cambaleia para trás!",
                                       f"Balançou! {d.name} está grogue!"]), "big", att.idx)
        else:
            self.emit(f"{d.name} sentiu o golpe e recua.", "hit", att.idx)
        return "rocked"

    def _resolve_strike(self, att: FighterState, d: FighterState, sid: str, target: str, pos: int,
                        focus: bool, bonus: float, where: str, counter: bool = False) -> tuple[str, str | None, bool]:
        """Resolve um golpe. Retorna (resultado 'land'/'block'/'miss', status, limpo)."""
        s = STRIKES[sid]
        att.thrown[sid] = att.thrown.get(sid, 0) + 1
        att.rs["sig_att"] += 1
        att.rs["total_att"] += 1
        att.spend(s.stamina * (1.25 if self.slot(att, "pace") == "alto" else 1.0))
        p = self._hit_chance(att, d, sid, target, pos, focus, bonus, where)
        if self.chance(p):
            clean_p = 0.07 + (0.07 if counter else 0) + 0.04 * d.rock_level + (0.03 if focus else 0)
            clean = self.chance(clean_p)
            mult = 1.15 if counter else 1.0
            if self.range == LONGE and where == "em_pe" and s.best_range == CURTA:
                mult *= 0.8
            if s.kind == "kick" and self.range == CURTA and where == "em_pe":
                mult *= 0.6
            if self.slot(att, "posture") == "tudo":
                mult *= 1.1
            dmg = self._damage(att, sid, target, clean, mult)
            status = self._land(att, d, sid, target, dmg, where, clean)
            return "land", status, clean
        if target == "leg" and self.slot(d, "defense") == "checar" and self.chance(0.6):
            att.legs = max(0.0, att.legs - self.rng.uniform(2, 5) * (85 / att.a("leg_toughness")))
            return "check", None, False
        return ("block" if self.chance(0.55) else "miss"), None, False

    def _strike_sequence(self, att: FighterState, d: FighterState) -> None:
        seq, focus, combo_id = self._choose_combo(att)
        self._mark = self.mark()
        results = []
        setup = 0.0
        if combo_id == "finta-overhand":
            setup = 0.35
        for i, (sid, target) in enumerate(seq):
            s = STRIKES[sid]
            if i == 0 and s.best_range > self.range:
                # precisa entrar: o adversário pode receber na entrada
                self.range = min(CURTA, s.best_range)
                self._habit_hint(att, "entrada")
                resp = d.plan.counters.get("entrada")
                if resp and resp in STRIKES and d.rock_level < 2 and self.follows(d) \
                        and self.chance(0.35 + d.a("counter") / 500):
                    self._counter_strike(d, att, resp, 0.35 + self._habit_bonus(att, "entrada", resp), "na entrada")
                    if self.finished or self.phase != "em_pe":
                        return
                    if self.chance(0.5):
                        self._narrate_combo(att, d, results)
                        return
                setup -= 0.15
            elif i == 0 and self.range == LONGE:
                self.range = MEDIA
                setup -= 0.2
            outcome, status, clean = self._resolve_strike(att, d, sid, target, i, focus, setup, "em_pe")
            results.append((sid, target, outcome, clean))
            if self.finished:
                return
            if status in ("kd", "ko"):
                self._narrate_combo(att, d, results)
                return
            # bônus de preparação: corpo → cabeça, jab → mão de trás
            setup = 0.3 if target == "body" else (0.1 if sid == "jab" else 0.0)
            if focus and combo_id:
                setup += 0.1
            if self._maybe_counter(d, att, sid, outcome):
                self._narrate_combo(att, d, results)
                return
        self._narrate_combo(att, d, results)
        if self.slot(att, "movement") == "entra_sai" and self.chance(0.6):
            self.range = LONGE
        elif self.range == CURTA and self.chance(0.25):
            self.range = MEDIA

    def _trigger_of(self, sid: str) -> list[str]:
        t = []
        if sid == "jab":
            t.append("jab")
        if sid == "hook":
            t.append("hook")
        if sid in ("cross", "hook", "overhand", "uppercut"):
            t.append("power")
        if sid in KICKS:
            t.append("kick")
        return t

    def _habit_bonus(self, att: FighterState, trigger: str, resp: str) -> float:
        for h in att.f.habits:
            if h["trigger"] == trigger and h["exploit"] == resp:
                return h["bonus"]
        return 0.0

    def _habit_hint(self, att: FighterState, trigger: str) -> None:
        """O treinador do adversário pode perceber o vício do lutador."""
        d = self.other(att)
        for h in att.f.habits:
            if h["trigger"] != trigger:
                continue
            if self.coached is not None and self.coached != d.idx:
                return
            last = att.hint_cooldown.get(trigger, -999)
            if self.abs_time() - last > 75 and self.chance(0.15):
                att.hint_cooldown[trigger] = self.abs_time()
                self.emit(f"◆ Leitura: {h['tell']}.", "hint", d.idx)

    def _maybe_counter(self, d: FighterState, att: FighterState, sid: str, outcome: str) -> bool:
        if d.rock_level >= 2 or self.finished:
            return False
        trigs = self._trigger_of(sid)
        for trig in trigs:
            if trig in ("jab", "hook", "kick"):
                self._habit_hint(att, trig)
        for trig in trigs:
            resp = d.plan.counters.get(trig)
            if not resp:
                continue
            if not self.follows(d):
                continue
            p = 0.18 + d.a("counter") / 600
            if outcome == "land":
                p *= 0.5
            if self.chance(p):
                if resp == "catch":
                    if STRIKES[sid].kind == "kick" and sid != "head_kick":
                        self.emit(f"{d.name} agarra o chute de {att.name}!", "ground", d.idx)
                        self._takedown(d, att, bonus=0.9 + self._habit_bonus(att, trig, "catch"), kind="catch")
                        return True
                    continue
                if resp in STRIKES:
                    bonus = 0.25 + self._habit_bonus(att, trig, resp)
                    self._counter_strike(d, att, resp, bonus, "")
                    return True
        # contra-ataque natural
        posture = self.slot(d, "posture")
        base = 0.05 * d.f.style["counter_tendency"] * (d.a("counter") / 80)
        if posture == "contra":
            base *= 2.2
        if outcome == "miss":
            base *= 1.5
        if self.chance(base * d.gas):
            resp = self.rng.choice(["cross", "hook", "hook", "cross", "uppercut"])
            self._counter_strike(d, att, resp, 0.2, "")
            return True
        return False

    def _counter_strike(self, d: FighterState, att: FighterState, sid: str, bonus: float, ctx: str) -> None:
        target = "head" if "head" in STRIKES[sid].targets else list(STRIKES[sid].targets)[0]
        mark = self.mark()
        outcome, status, clean = self._resolve_strike(d, att, sid, target, 0, True, bonus, "em_pe", counter=True)
        label = STRIKES[sid].label(d.stance, target)
        if outcome == "land":
            txt = f"CONTRA-ATAQUE{(' ' + ctx) if ctx else ''}! {d.name} encaixa {self._art(label)}"
            txt += " em cheio!" if clean else "."
            self.emit_at(mark, txt, "hit", d.idx)
        else:
            self.emit(f"{d.name} tenta o contra-ataque com {label}, mas não pega.", "miss", d.idx)

    def _narrate_combo(self, att: FighterState, d: FighterState, results: list) -> None:
        if not results:
            return
        mark = self._mark

        def say(text: str, kind: str = "info", side: int | None = None) -> None:
            self.emit_at(mark, text, kind, side)
        self._narrate_combo_text(att, d, results, say)

    def _narrate_combo_text(self, att: FighterState, d: FighterState, results: list, say) -> None:
        names = [STRIKES[sid].label(att.stance, t) for sid, t, _, _ in results]
        landed = [names[i] for i, r in enumerate(results) if r[2] == "land"]
        clean = any(r[3] for r in results)
        checked = any(r[2] == "check" for r in results)
        if len(results) == 1:
            n = names[0]
            o = results[0][2]
            if o == "land":
                txt = self.rng.choice([f"{att.name} acerta {self._art(n)}.", f"{att.name} conecta {self._art(n)}.",
                                       f"{self._art(n).capitalize()} de {att.name} entra."])
                if clean:
                    txt = f"{att.name} acerta {self._art(n)} EM CHEIO!"
                say(txt, "hit", att.idx)
            elif o == "check":
                say(f"{d.name} checa o {n} de {att.name}! Machucou a canela de {att.name}.", "hit", d.idx)
            elif o == "block":
                say(f"{att.name} solta {self._art(n)}, {d.name} bloqueia.", "miss", att.idx)
            else:
                say(self.rng.choice([f"{att.name} erra {self._art(n)}.", f"{d.name} esquiva {self._art(n)} de {att.name}."]),
                          "miss", att.idx)
            return
        combo = ", ".join(names[:-1]) + " e " + names[-1]
        if not landed:
            say(f"{att.name} solta {combo} — {d.name} " +
                      self.rng.choice(["defende tudo.", "sai da linha.", "bloqueia na guarda.", "se esquiva bem."]),
                      "miss", att.idx)
        else:
            if len(landed) == len(results):
                tail = "tudo entra!" if len(landed) > 1 else "conecta."
            elif len(landed) == 1:
                tail = f"conecta {self._art(landed[0])}."
            else:
                tail = "conectam " + ", ".join(landed[:-1]) + " e " + landed[-1] + "."
            txt = f"{att.name} solta {combo} — {tail}"
            if clean:
                txt += " Pegou em cheio!"
            if checked:
                txt += f" {d.name} checou o chute."
            say(txt, "hit", att.idx)

    @staticmethod
    def _art(n: str) -> str:
        fem = ("joelhada", "cotovelada")
        return ("a " if n.startswith(fem) else "o ") + n

    # ------------------------------------------------------------------ quedas / clinch
    def _takedown(self, att: FighterState, d: FighterState, bonus: float = 0.0, kind: str | None = None) -> None:
        kind = kind or self.slot(att, "takedown")
        if kind == AUTO:
            kind = self.rng.choice(["double", "single", "single", "level"])
        att.rs["td_att"] += 1
        att.spend(3.5)
        d.spend(1.8)
        label = {"double": "double leg", "single": "single leg", "level": "queda trocando de nível",
                 "corpo": "queda pelo corpo", "catch": "queda segurando o chute"}.get(kind, "queda")
        # contra-ataques à queda
        resp = d.plan.counters.get("takedown")
        if resp and d.rock_level < 2 and kind != "catch" and self.follows(d):
            if resp == "knee" and self.chance(0.4 + d.a("counter") / 400):
                self.emit(f"{att.name} baixa para a {label}...", "info", att.idx)
                outcome, status, clean = self._resolve_strike(d, att, "knee", "head", 0, True, 0.5, "em_pe", counter=True)
                if outcome == "land":
                    self.emit(f"JOELHADA NA ENTRADA! {d.name} recebe {att.name} com o joelho!", "big", d.idx)
                    if self.finished or status:
                        return
                    if self.chance(0.6):
                        return
            elif resp == "guillotine" and self.chance(0.25 + d.a("sub_offense") / 300):
                self.emit(f"{att.name} entra na {label} e {d.name} abraça o pescoço!", "sub", d.idx)
                self.phase = "chao"
                self.ground = {"top": att.idx, "pos": "guarda", "idle": 0}
                self._start_sub(d, att, "guillotine", from_top=False, bonus=10)
                return
        x = logit(0.28) + (att.a("wrestling") * att.gas - d.a("takedown_def") * d.gas) / 14
        x += 0.3 if d.cage > 0.7 else 0
        x += 0.45 if kind == "level" else (-0.1 if kind == "single" else 0)
        x += 0.2 if att.plan.takedown == kind else 0
        x -= 0.6 if self.slot(d, "defense") == "sprawl" else 0
        x += 0.45 * d.rock_level + (100 - d.legs) / 120
        x += bonus
        if self.chance(sigmoid(x)):
            att.rs["td_land"] += 1
            r = self.rng.random()
            pos = "guarda" if r < 0.55 else ("meia-guarda" if r < 0.88 else "cem-quilos")
            self.phase = "chao"
            self.clinch = None
            self.ground = {"top": att.idx, "pos": pos, "idle": 0}
            self.emit(f"{att.name} completa a {label}! Cai na {pos} de {d.name}.", "ground", att.idx)
            return
        if self.chance(0.4):
            self.phase = "clinch"
            self.clinch = {"ctrl": att.idx, "cage": d.idx if d.cage > 0.5 else None, "secs": 0}
            self.emit(f"{d.name} defende a {label}; os dois ficam no clinch" +
                      (" contra a grade." if self.clinch["cage"] is not None else "."), "info", d.idx)
        else:
            self.range = MEDIA
            self.emit(f"{d.name} defende a {label} de {att.name} com um sprawl.", "info", d.idx)

    def _clinch_attempt(self, att: FighterState, d: FighterState) -> None:
        att.spend(1.0)
        x = (att.a("clinch_control") - (d.a("footwork") + d.a("clinch_control")) / 2) / 15 + 0.2 + d.cage
        if att.rock_level >= 2:
            x += 0.4
        if self.chance(sigmoid(x)):
            self.phase = "clinch"
            self.clinch = {"ctrl": att.idx, "cage": d.idx if d.cage > 0.5 else None, "secs": 0}
            where = " contra a grade" if self.clinch["cage"] is not None else ""
            if att.rock_level >= 2:
                self.emit(f"{att.name} agarra {d.name} para ganhar tempo{where}.", "info", att.idx)
            else:
                self.emit(f"{att.name} amarra {d.name} no clinch{where}.", "info", att.idx)
        else:
            self.emit(f"{att.name} tenta amarrar, mas {d.name} se afasta e evita o clinch.", "miss", att.idx)

    def _clinch_tick(self) -> None:
        c = self.clinch
        c["secs"] += 1
        ctrl = self.fs[c["ctrl"]]
        other = self.other(ctrl)
        for fs in self.fs:
            fs.spend(0.15)
        actor = None
        if self.chance(0.24 * ctrl.gas):
            actor = ctrl
        elif self.chance(0.17 * other.gas):
            actor = other
        if actor is None:
            if c["secs"] > 22 and self.chance(0.12):
                self.phase = "em_pe"
                self.clinch = None
                self.range = MEDIA
                self.emit("O árbitro separa os lutadores.", "info")
            return
        d = self.other(actor)
        pref = self.slot(actor, "clinch")
        w = {"joelhos": 3.0, "cotovelos": 1.2, "boxe_sujo": 2.0, "queda": 1.0, "separar": 1.0, "grade": 0.6}
        if actor.f.style.get("grapple_intent", 0) < 0.03 and self.slot(actor, "grapple") != "quedas":
            w["queda"] = 0.3
        if actor.a("wrestling") < 65:
            w["queda"] *= 0.4
        if self.slot(actor, "grapple") == "quedas":
            w["queda"] = 4.0
        if self.slot(actor, "grapple") == "evitar" or actor.f.style["preferred_range"] == MEDIA:
            w["separar"] = 2.5
        if actor.rock_level >= 1 and actor.plan.recover:
            w["separar"] = 0.1
            w["grade"] = 2.0
        if pref != AUTO:
            w[pref] = w.get(pref, 1) * 5
        act = self.rng.choices(list(w), list(w.values()))[0]
        if act in ("joelhos", "cotovelos", "boxe_sujo"):
            if act == "joelhos":
                sid = "knee"
                tgt = "body" if self.chance(0.7) else "head"
            elif act == "cotovelos":
                sid, tgt = "elbow", "head"
            else:
                sid = self.rng.choice(["hook", "uppercut", "hook", "cross"])
                tgt = "head" if self.chance(0.65) else "body"
            focus = pref == act
            outcome, status, clean = self._resolve_strike(actor, d, sid, tgt, 0, focus, 0.35, "clinch")
            if self.finished:
                return
            n = STRIKES[sid].label(actor.stance, tgt)
            if outcome == "land":
                self.emit(f"No clinch, {actor.name} acerta {self._art(n)}" + (" em cheio!" if clean else "."), "hit", actor.idx)
            else:
                self.emit(f"No clinch, {actor.name} tenta {self._art(n)}, {d.name} bloqueia.", "miss", actor.idx)
        elif act == "queda":
            self.phase = "em_pe"
            self.clinch = None
            self._takedown(actor, d, bonus=(actor.a("clinch_control") - d.a("clinch_control")) / 30
                           + (0.25 if c.get("cage") == d.idx else 0), kind="corpo")
        elif act == "separar":
            x = ((actor.a("footwork") + actor.a("strength")) - (d.a("clinch_control") + d.a("strength"))) / 25 + 0.3
            if self.chance(sigmoid(x)):
                self.phase = "em_pe"
                self.clinch = None
                self.range = MEDIA
                self.emit(f"{actor.name} se solta do clinch e volta para a distância.", "info", actor.idx)
        elif act == "grade":
            if c.get("cage") != d.idx and self.chance(0.5):
                c["cage"] = d.idx
                c["ctrl"] = actor.idx
                d.cage = 1.0
                self.emit(f"{actor.name} prensa {d.name} contra a grade.", "info", actor.idx)

    # ------------------------------------------------------------------ chão
    def _ground_tick(self) -> None:
        g = self.ground
        top = self.fs[g["top"]]
        bot = self.other(top)
        top.rs["ctrl"] += 1
        g["idle"] += 1
        top.spend(0.1)
        bot.spend(0.25)
        if g["idle"] > 32 and self.chance(0.15):
            self._stand_up("O árbitro manda levantar por falta de ação.")
            return
        bplan = self.slot(bot, "ground_bottom")
        p_top = 0.36 * top.gas * (1.4 if bot.rock_level else 1.0) * (1 + top.motivated * 0.1)
        p_bot = 0.22 * bot.gas * (0.5 if bot.rock_level >= 2 else 1.0)
        if bplan == "levantar":
            p_bot *= 1.3
        if self.chance(p_top):
            self._top_action(top, bot)
        elif self.chance(p_bot):
            self._bottom_action(bot, top)

    def _stand_up(self, msg: str) -> None:
        self.phase = "em_pe"
        self.ground = None
        self.range = MEDIA
        self.emit(msg, "info")

    def _top_action(self, top: FighterState, bot: FighterState) -> None:
        g = self.ground
        pos = g["pos"]
        tplan = self.slot(top, "ground_top")
        style_pref = top.f.style.get("ground_top", "gnp")
        w = {"gnp": 3.0, "cotovelos": 0.8, "passar": 1.5, "finalizar": 0.4, "controlar": 1.2, "levantar": 0.1}
        if style_pref in w:
            w[style_pref] *= 1.6
        if top.a("sub_offense") > 85:
            w["finalizar"] *= 1.8
        if top.f.style["preferred_range"] == MEDIA and top.a("wrestling") < 65:
            w["levantar"] = 0.8
        if bot.rock_level:
            w["gnp"] *= 3 if top.plan.finish or self.chance(0.7) else 1
        if pos == "costas":
            w["finalizar"] *= 3
        if bot.rock_level:
            w["finalizar"] *= 0.4
        if pos in ("montada",):
            w["gnp"] *= 1.5
        if tplan != AUTO:
            w[tplan] = w.get(tplan, 1) * 6
        if top.plan.sub_pref != AUTO and self.follows(top):
            w["finalizar"] *= 2
        act = self.rng.choices(list(w), list(w.values()))[0]
        if act in ("gnp", "cotovelos"):
            self._gnp(top, bot, elbows=(act == "cotovelos"), focus=(tplan == act))
        elif act == "passar":
            self._advance(top, bot, focus=(tplan == "passar"))
        elif act == "finalizar":
            subs = [s for s in SUBMISSIONS.values() if pos in s.top]
            if not subs:
                self._advance(top, bot, focus=False)
                return
            pref = top.plan.sub_pref
            fav = top.f.style.get("favorite_subs", [])
            weights = [(4 if s.id == pref else 1) * (2 if s.id in fav else 1) for s in subs]
            sub = self.rng.choices(subs, weights)[0]
            self._start_sub(top, bot, sub.id, from_top=True, bonus=(8 if sub.id == pref else 0))
        elif act == "controlar":
            top.stamina = min(top.max_stamina, top.stamina + 0.2)
            if self.chance(0.08):
                self.emit(f"{top.name} controla {bot.name} na {pos}, colado no corpo.", "ground", top.idx)
                g["idle"] = max(0, g["idle"] - 3)
        elif act == "levantar":
            self._stand_up(f"{top.name} se levanta e chama {bot.name} para a trocação.")

    def _gnp(self, top: FighterState, bot: FighterState, elbows: bool, focus: bool) -> None:
        g = self.ground
        pos = g["pos"]
        n = self.rng.randint(1, 3) if not bot.rock_level else self.rng.randint(1, 4)
        landed = 0
        biggest = None
        for _ in range(n):
            sid = "elbow" if elbows or self.chance(0.15) else "cross"
            top.rs["sig_att"] += 1
            top.rs["total_att"] += 1
            top.spend(0.6)
            x = logit(GNP_ACC[pos]) + (top.a("ground_strikes") - bot.a("bottom_game")) / 25
            x += 0.25 if focus else 0
            x -= 0.5 if self.slot(bot, "ground_bottom") == "amarrar" else 0
            x += 0.3 * bot.rock_level + (top.stamina - bot.stamina) / 250
            if self.chance(sigmoid(x)):
                landed += 1
                base = 4.6 if sid == "cross" else 5.6
                dmg = base * GNP_MULT[pos] * (top.a("ground_strikes") / 80) ** 1.2 * (top.a("power") / 85) ** 0.6
                dmg *= self.rng.lognormvariate(0, 0.3) * (0.75 + 0.25 * top.stamina / 100)
                clean = self.chance(0.06 + 0.05 * bot.rock_level)
                if clean:
                    dmg *= 1.6
                st = self._land(top, bot, sid, "head", dmg, "chao", clean)
                g["idle"] = 0
                if self.finished:
                    return
                if st:
                    biggest = st
        kind = "cotoveladas" if elbows else "socos"
        if landed == 0:
            self.emit(f"{top.name} tenta {kind} da {pos}, {bot.name} se protege.", "miss", top.idx)
        elif bot.rock_level >= 2:
            self.emit(f"{top.name} despeja {kind}! {bot.name} só se defende! O árbitro olha de perto!", "big", top.idx)
        else:
            qty = f"{landed} {kind}" if landed > 1 else ("uma cotovelada" if elbows else "um soco")
            self.emit(f"Ground and pound: {top.name} acerta {qty} da {pos}.", "hit", top.idx)

    def _advance(self, top: FighterState, bot: FighterState, focus: bool) -> None:
        g = self.ground
        pos = g["pos"]
        idx = GROUND_POSITIONS.index(pos)
        if pos == "costas":
            self._gnp(top, bot, elbows=False, focus=False)
            return
        x = (top.a("top_control") * top.gas - bot.a("bottom_game") * bot.gas) / 14 - 0.7
        x += 0.25 if focus else 0
        x += 0.6 * bot.rock_level
        top.spend(1.2)
        bot.spend(0.8)
        if self.chance(sigmoid(x)):
            new = GROUND_POSITIONS[min(idx + 1, 3)]
            if pos in ("cem-quilos", "montada") and self.chance(0.35):
                new = "costas"
            if new != pos:
                g["pos"] = new
                g["idle"] = 0
                verbs = {"meia-guarda": "passa para a meia-guarda", "cem-quilos": "passa a guarda! Cem-quilos",
                         "montada": "MONTA em", "costas": "pega as COSTAS de"}
                v = verbs[new]
                txt = f"{top.name} {v} {bot.name}!" if new in ("montada", "costas") else f"{top.name} {v}."
                self.emit(txt, "ground", top.idx)
        else:
            if self.chance(0.3):
                self.emit(f"{top.name} tenta passar a guarda, {bot.name} recompõe.", "miss", top.idx)

    def _bottom_action(self, bot: FighterState, top: FighterState) -> None:
        g = self.ground
        pos = g["pos"]
        bplan = self.slot(bot, "ground_bottom")
        w = {"levantar": 3.0, "raspar": 1.0, "finalizar": 0.5, "amarrar": 1.0}
        if bot.a("sub_offense") > 80:
            w["finalizar"] *= 2
        if pos != "guarda":
            w["finalizar"] = 0.0 if pos != "meia-guarda" else 0.0
            w["raspar"] *= 0.5 if pos in ("meia-guarda",) else 0.2
        if bot.rock_level >= 2:
            w["amarrar"] = 4.0 if bot.plan.recover else 2.0
        if bplan != AUTO:
            if bplan == "finalizar" and pos != "guarda":
                w["levantar"] *= 2
            else:
                w[bplan] = w.get(bplan, 1) * 5
        act = self.rng.choices(list(w), list(w.values()))[0]
        if act == "levantar":
            x = (bot.a("bottom_game") * 0.35 + bot.a("wrestling") * 0.3 + bot.a("strength") * 0.35 - top.a("top_control")) / 12
            x += {"guarda": 0.1, "meia-guarda": -0.2, "cem-quilos": -0.6, "montada": -1.3, "costas": -1.1}[pos]
            x += 0.2 if bplan == "levantar" else 0
            x += (bot.stamina - top.stamina) / 150 - 0.5 * bot.rock_level
            bot.spend(2.2)
            top.spend(1.0)
            if self.chance(sigmoid(x - 0.4)):
                if pos in ("cem-quilos", "montada") and self.chance(0.25):
                    g["pos"] = "costas"
                    self.emit(f"{bot.name} vira para levantar e entrega as costas para {top.name}!", "ground", top.idx)
                    return
                if self.chance(0.35):
                    self.phase = "clinch"
                    self.ground = None
                    self.clinch = {"ctrl": top.idx, "cage": bot.idx, "secs": 0}
                    self.emit(f"{bot.name} usa a grade para levantar, mas {top.name} segue agarrado.", "info", bot.idx)
                else:
                    self._stand_up(f"{bot.name} consegue se levantar!")
            else:
                if pos in ("guarda", "meia-guarda") and self.chance(0.35) and self.coached is not None:
                    self.emit(f"{bot.name} tenta se levantar, {top.name} mantém o peso em cima.", "miss", bot.idx)
        elif act == "raspar":
            x = (bot.a("bottom_game") - top.a("top_control")) / 14 - 1.3 + (0.3 if bplan == "raspar" else 0)
            bot.spend(2.0)
            if self.chance(sigmoid(x)):
                bot.rs["rev"] += 1
                g["top"] = bot.idx
                g["pos"] = "guarda"
                g["idle"] = 0
                self.emit(f"RASPAGEM! {bot.name} inverte e fica por cima de {top.name}!", "ground", bot.idx)
        elif act == "finalizar":
            subs = [s for s in SUBMISSIONS.values() if pos in s.bottom]
            if subs:
                sub = self.rng.choice(subs)
                self._start_sub(bot, top, sub.id, from_top=False, bonus=0)
        elif act == "amarrar":
            g["idle"] += 2
            if self.chance(0.15):
                self.emit(f"{bot.name} amarra {top.name} por baixo e neutraliza.", "ground", bot.idx)

    # ------------------------------------------------------------------ finalizações
    def _start_sub(self, att: FighterState, d: FighterState, sub_id: str, from_top: bool, bonus: float) -> None:
        sub = SUBMISSIONS[sub_id]
        att.rs["sub_att"] += 1
        att.spend(3.0)
        depth = 15 + (att.a("sub_offense") - d.a("sub_defense")) / 2 + bonus + self.rng.uniform(-8, 8)
        depth += 8 * d.rock_level
        self.sub = {"att": att.idx, "def": d.idx, "id": sub_id, "depth": depth, "secs": 0,
                    "top": from_top, "near": False}
        self.emit(f"{att.name} parte para {sub_art(sub.name)}!", "sub", att.idx)

    def _sub_tick(self) -> None:
        s = self.sub
        att, d = self.fs[s["att"]], self.fs[s["def"]]
        sub = SUBMISSIONS[s["id"]]
        s["secs"] += 1
        att.spend(1.1)
        d.spend(1.4)
        if self.ground and self.ground["top"] == att.idx:
            att.rs["ctrl"] += 1
        gain = self.rng.uniform(3, 8) * (att.a("sub_offense") / 85) ** 1.5 * sub.ease * att.gas
        gain *= 1.3 if d.rock_level else 1.0
        if att.plan.sub_pref == sub.id:
            gain *= 1.2
        esc = 0.2 * (d.a("sub_defense") / 85) ** 2 * d.gas ** 0.5 * (d.a("strength") / 80) ** 0.3 / sub.ease
        if d.rock_level:
            esc *= 0.6
        if self.slot(d, "defense") == "finalizacao":
            esc *= 1.4
        s["depth"] += gain
        if s["depth"] >= 100:
            if sub.kind == "choke" and self.chance(d.a("heart") / 400):
                self.emit(f"{d.name} se recusa a bater... e APAGA {sub_art(sub.name, 'em')}!", "big", att.idx)
            else:
                self.emit(f"{d.name} BATE! {att.name} finaliza com {sub_art(sub.name)}!", "big", att.idx)
            self.sub = None
            self._finish(att.idx, "SUB", sub.name)
            return
        if s["depth"] > 75 and not s["near"]:
            s["near"] = True
            att.rs["near_sub"] += 1
            self.emit(f"ESTÁ ENCAIXADO! {d.name} em apuros {sub_art(sub.name, 'em')}!", "sub", att.idx)
        elif s["depth"] > 50 and s["secs"] == 2:
            self.emit(f"{att.name} aperta {sub_art(sub.name)}...", "sub", att.idx)
        if self.chance(esc):
            self.sub = None
            self.emit(f"{d.name} escapa {sub_art(sub.name, 'de')}!", "ground", d.idx)
            if self.phase == "chao" and self.ground:
                if s["top"]:
                    r = self.rng.random()
                    if r < 0.3:
                        self._stand_up("Na escapada, os dois voltam a ficar de pé.")
                    elif r < 0.5:
                        self.ground["pos"] = "guarda"
                else:
                    r = self.rng.random()
                    if r < 0.35:
                        self.ground["pos"] = "meia-guarda"
                    elif r < 0.55:
                        self._stand_up(f"{d.name} se levanta depois de escapar.")
            else:
                self.phase = "em_pe"
                self.range = MEDIA

    # ------------------------------------------------------------------ árbitro / fim
    def _check_ref(self) -> None:
        for fs in self.fs:
            if fs.rock_level >= 2:
                thr = 30 + fs.a("composure") / 8 + fs.a("heart") / 12
                if fs.ref_meter > thr:
                    opp = self.other(fs)
                    where = "no chão" if self.phase == "chao" else "em pé"
                    self.emit(f"O ÁRBITRO INTERROMPE! {fs.name} não se defende {where}!", "big", opp.idx)
                    self._finish(opp.idx, "TKO", "socos" if self.phase != "clinch" else "joelhadas e socos")
                    return
            if fs.cut > 88 and self.chance(0.02):
                opp = self.other(fs)
                self.emit(f"O médico é chamado para olhar o corte de {fs.name}... e encerra a luta!", "big", opp.idx)
                self._finish(opp.idx, "TKO", "interrupção médica")
                return

    def _finish(self, winner: int, method: str, detail: str) -> None:
        self.finished = True
        self.sub = None
        self.result = Result(winner, method, detail, self.round, self.clock)
        names = [f.name for f in self.fs]
        self.emit(f"FIM DE LUTA! {self.result.summary(names)}", "result", winner)

    def _end_round(self) -> None:
        self.emit(f"Fim do round {self.round}!", "round")
        self.sub = None
        self._score_round()
        a, b = self.fs
        for fs in self.fs:
            r = fs.rs
            extra = f", {r['td_land']}/{r['td_att']} quedas" if r["td_att"] else ""
            extra += f", {r['kd']} knockdown(s)" if r["kd"] else ""
            extra += f", {r['ctrl'] // 60}:{r['ctrl'] % 60:02d} de controle" if r["ctrl"] >= 20 else ""
            self.emit(f"  {fs.name}: {r['sig_land']}/{r['sig_att']} golpes significativos{extra}.", "round", fs.idx)
        if self.round < self.rounds:
            ja, jb = self.cards[0][-1]
            pick = a.name if ja > jb else b.name
            self.emit(f"  Na avaliação da transmissão, o round foi de {pick}.", "round")
        if self.round >= self.rounds:
            self._decision()
            return
        self.intermission = True
        for fs in self.fs:
            fs.max_stamina = max(40.0, fs.max_stamina - (100 - fs.a("cardio")) * 0.35 - (100 - fs.body) * 0.1)
            fs.stamina = min(fs.max_stamina, fs.stamina + 30 * fs.a("cardio") / 90)
            heal = 5 * fs.a("recovery") / 90
            fs.head = min(100.0, fs.head + heal)
            fs.rocked = 0
            fs.rock_level = 0
            fs.ref_meter = 0
            fs.tactical_round = False
            fs.motivated = 0.0
        self._ai_corners()
        self._corner_stoppage_check()

    def _corner_stoppage_check(self) -> None:
        for fs in self.fs:
            if self.coached == fs.idx:
                continue
            if fs.head < 18 and self.chance(0.55):
                opp = self.other(fs)
                self.emit(f"O córner de {fs.name} joga a toalha! A luta acabou no intervalo.", "big", opp.idx)
                self.intermission = False
                self.clock = ROUND_SECONDS
                self._finish(opp.idx, "TKO", "interrupção do córner")
                return
            if fs.cut > 70 and self.chance(0.4):
                opp = self.other(fs)
                self.emit(f"O médico examina o corte de {fs.name} e não deixa voltar!", "big", opp.idx)
                self.intermission = False
                self.clock = ROUND_SECONDS
                self._finish(opp.idx, "TKO", "interrupção médica")
                return

    def stop_by_corner(self, side: int) -> None:
        opp = self.fs[1 - side]
        self.emit(f"Você joga a toalha por {self.fs[side].name}.", "big", opp.idx)
        self.intermission = False
        self._finish(opp.idx, "TKO", "interrupção do córner")

    def next_round(self) -> None:
        if self.finished:
            return
        self.intermission = False
        self.round += 1
        self.clock = 0
        self.phase = "em_pe"
        self.range = LONGE
        self.ground = None
        self.clinch = None
        for fs in self.fs:
            fs.rounds.append(new_round_stats())
            fs.cage = 0.0
            fs.flags -= {"grade", "surdo", "confuso"}
        self.emit(f"ROUND {self.round}!", "round")

    def _round_score(self, fs: FighterState, judge: int) -> float:
        r = fs.rs
        g = 1 + self.judge_style[judge]
        return (r["dmg"] * 1.0 + r["sig_land"] * 0.25 + r["kd"] * 14 + r["near_sub"] * 6 * g
                + r["td_land"] * 4 * g + r["ctrl"] * 0.06 * g + r["sub_att"] * 1.5 * g + r["sig_att"] * 0.04)

    def _score_round(self) -> None:
        a, b = self.fs
        for j in range(3):
            sa = self._round_score(a, j) * self.rng.gauss(1, 0.08)
            sb = self._round_score(b, j) * self.rng.gauss(1, 0.08)
            diff = sa - sb + self.rng.gauss(0, 2.5)
            lead = abs(diff)
            loser_kd = (b if diff > 0 else a).rs["kd"]
            winner_kd = (a if diff > 0 else b).rs["kd"]
            ten_eight = (lead > 50) or (winner_kd >= 2 and lead > 25 and loser_kd == 0)
            lo = 8 if ten_eight else 9
            self.cards[j].append((10, lo) if diff > 0 else (lo, 10))

    def _decision(self) -> None:
        totals = [(sum(x for x, _ in c), sum(y for _, y in c)) for c in self.cards]
        votes = [0 if t[0] > t[1] else (1 if t[1] > t[0] else None) for t in totals]
        w0, w1 = votes.count(0), votes.count(1)
        cards_txt = ", ".join(f"{x}-{y}" for x, y in totals)
        self.finished = True
        if w0 == w1:
            detail = "majoritário" if votes.count(None) == 1 else "dividido"
            self.result = Result(None, "DRAW", f"empate {detail}: {cards_txt}", self.round, ROUND_SECONDS, totals)
        else:
            win = 0 if w0 > w1 else 1
            n_w = max(w0, w1)
            n_l = min(w0, w1)
            if n_w == 3:
                kind = "unânime"
            elif n_l == 1:
                kind = "dividida"
            else:
                kind = "majoritária"
            ordered = ", ".join(f"{x}-{y}" if win == 0 else f"{y}-{x}" for x, y in totals)
            self.result = Result(win, "DEC", f"{kind} ({ordered})", self.round, ROUND_SECONDS, totals)
        names = [f.name for f in self.fs]
        self.emit(f"FIM DE LUTA! Vamos aos juízes... {self.result.summary(names)}", "result", self.result.winner)

    # ------------------------------------------------------------------ IA de córner
    def _ai_corners(self) -> None:
        for fs in self.fs:
            if self.coached == fs.idx:
                continue
            msg = ai_corner(self, fs)
            if msg:
                self.emit(f"(Córner de {fs.name}: \"{msg}\")", "corner", fs.idx)

    # ------------------------------------------------------------------ ambiente
    def _ambient(self) -> None:
        opts = []
        if self.phase == "em_pe":
            for fs in self.fs:
                opp = self.other(fs)
                p = fs.plan
                n = fs.name
                if fs.rock_level:
                    opts.append(f"{n} ainda tenta recuperar as pernas, andando para trás.")
                    continue
                mv = p.movement
                if mv == "direita":
                    opts.append(f"{n} circula para a direita" + (f", longe da mão forte de {opp.name}." if self.power_side_safe(fs, opp) == "direita" else "."))
                elif mv == "esquerda":
                    opts.append(f"{n} circula para a esquerda" + (f", longe da mão forte de {opp.name}." if self.power_side_safe(fs, opp) == "esquerda" else "."))
                elif mv == "cortar":
                    opts.append(f"{n} corta o octógono e fecha o caminho de {opp.name}.")
                elif mv == "centro":
                    opts.append(f"{n} gira e volta para o centro do octógono.")
                elif mv == "entra_sai":
                    opts.append(f"{n} entra e sai, mudando o ritmo com o trabalho de pernas.")
                posture = p.posture if p.posture != AUTO else None
                if posture == "pressao" or (posture is None and fs.f.style["pressure"] >= 0.7):
                    opts.append(f"{n} anda pra frente, pressionando {opp.name}.")
                elif posture == "contra" or (posture is None and fs.f.style["counter_tendency"] >= 0.6):
                    opts.append(f"{n} espera, mão armada para o contra-ataque.")
                elif posture == "distancia":
                    opts.append(f"{n} mantém {opp.name} na ponta do jab.")
                elif posture == "tudo":
                    opts.append(f"{n} parte para cima carregando os golpes!")
                elif posture == "seguro":
                    opts.append(f"{n} administra, sem se expor.")
                if p.defense == "guarda_alta":
                    opts.append(f"{n} fecha a guarda alta.")
                elif p.defense == "cabeca":
                    opts.append(f"{n} balança o tronco, tirando a cabeça da linha.")
                if p.pace == "alto" or (p.pace == AUTO and fs.a("volume") > 90):
                    opts.append(f"{n} não para de soltar fintas e jabs, ritmo altíssimo.")
                elif p.pace == "poupar":
                    opts.append(f"{n} economiza energia, escolhendo os momentos.")
                if fs.f.id == "holloway":
                    opts.append("Holloway aponta para o chão e chama a trocação!")
                if fs.stamina < 40:
                    opts.append(f"{n} respira pela boca, o cansaço aparece.")
                if fs.cage > 0.7:
                    opts.append(f"{n} está com as costas na grade.")
            opts.append(f"Estudo na {RANGE_NAMES[self.range]}. Fintas dos dois lados.")
        elif self.phase == "clinch":
            opts.append("Briga de mãos no clinch, ninguém cede.")
        else:
            g = self.ground
            top = self.fs[g["top"]]
            opts.append(f"{top.name} trabalha por cima na {g['pos']}.")
        self.emit(self.rng.choice(opts), "info")

    def intent(self, idx: int) -> list[str]:
        """O que o lutador está tentando fazer agora (plano do córner ou natureza dele)."""
        fs = self.fs[idx]
        p = fs.plan
        st = fs.f.style
        out = []
        if fs.rock_level >= 2:
            out.append("Machucado: tentando sobreviver")
        if p.posture != AUTO:
            out.append(POSTURE_TXT[p.posture])
        elif st["pressure"] >= 0.7:
            out.append("Pressionando (natural)")
        elif st["counter_tendency"] >= 0.6:
            out.append("Contra-ataque (natural)")
        else:
            out.append("Volume na média distância (natural)" if st["preferred_range"] == MEDIA else "Trocação (natural)")
        if p.pace == "alto":
            out.append("Ritmo alto")
        elif p.pace == "poupar":
            out.append("Poupando gás")
        if p.movement in MOVE_TXT:
            out.append(MOVE_TXT[p.movement])
        if p.weapon != AUTO:
            out.append("Foco: " + (COMBOS[p.weapon][0] if p.weapon in COMBOS else STRIKES[p.weapon].label(fs.stance)))
        if p.target in TARGET_TXT:
            out.append(TARGET_TXT[p.target])
        if p.defense in DEF_TXT:
            out.append(DEF_TXT[p.defense])
        for trig, resp in p.counters.items():
            r = {"catch": "agarrar o chute", "guillotine": "guilhotina"}.get(resp) or STRIKES[resp].label(fs.stance)
            out.append(f"Contra {trig}: {r}")
        if p.grapple == "quedas":
            out.append("Buscando quedas")
        elif p.grapple == "clinch":
            out.append("Buscando o clinch")
        elif p.grapple == "evitar":
            out.append("Evitando o grappling")
        if p.finish:
            out.append("Pronto para finalizar")
        return out

    # ------------------------------------------------------------------ helpers externos
    def stats_table(self) -> list[tuple[str, str, str]]:
        a, b = self.fs

        def t(fs, k):
            return int(fs.total(k))

        def pct(x, y):
            return f"{x}/{y} ({(x / y * 100) if y else 0:.0f}%)"
        rows = [
            ("Knockdowns", str(t(a, "kd")), str(t(b, "kd"))),
            ("Golpes sig.", pct(t(a, "sig_land"), t(a, "sig_att")), pct(t(b, "sig_land"), t(b, "sig_att"))),
            ("  Cabeça", str(t(a, "head")), str(t(b, "head"))),
            ("  Corpo", str(t(a, "body")), str(t(b, "body"))),
            ("  Pernas", str(t(a, "leg")), str(t(b, "leg"))),
            ("  Distância", str(t(a, "dist")), str(t(b, "dist"))),
            ("  Clinch", str(t(a, "clinch")), str(t(b, "clinch"))),
            ("  Chão", str(t(a, "ground")), str(t(b, "ground"))),
            ("Quedas", pct(t(a, "td_land"), t(a, "td_att")), pct(t(b, "td_land"), t(b, "td_att"))),
            ("Tent. finalização", str(t(a, "sub_att")), str(t(b, "sub_att"))),
            ("Raspagens", str(t(a, "rev")), str(t(b, "rev"))),
            ("Tempo de controle", clock_str(t(a, "ctrl")), clock_str(t(b, "ctrl"))),
        ]
        return rows

    def scorecards_text(self) -> list[str]:
        out = []
        a, b = self.fs
        for j, card in enumerate(self.cards):
            if not card:
                continue
            rounds = "  ".join(f"R{i + 1} {x}-{y}" for i, (x, y) in enumerate(card))
            ta, tb = sum(x for x, _ in card), sum(y for _, y in card)
            out.append(f"Juiz {j + 1}: {rounds}  =  {a.name} {ta} x {tb} {b.name}")
        return out

    def status_line(self, idx: int) -> str:
        fs = self.fs[idx]

        def tag(v):
            return "ok" if v > 70 else ("afetado" if v > 40 else "muito afetado")
        st = f"Gás {fs.stamina:.0f}% · Cabeça {tag(fs.head)} · Corpo {tag(fs.body)} · Pernas {tag(fs.legs)}"
        if fs.rock_level:
            st += " · MACHUCADO"
        if fs.cut > 30:
            st += " · CORTE"
        return st

    def position_text(self) -> str:
        if self.sub:
            s = self.sub
            return f"Finalização: {self.fs[s['att']].name} ataca {SUBMISSIONS[s['id']].name}"
        if self.phase == "em_pe":
            cage = [fs.name for fs in self.fs if fs.cage > 0.7]
            txt = f"Em pé · {RANGE_NAMES[self.range]}"
            if cage:
                txt += f" · {cage[0]} na grade"
            return txt
        if self.phase == "clinch":
            c = self.clinch
            return "Clinch" + (f" · {self.fs[c['cage']].name} na grade" if c.get("cage") is not None else "")
        g = self.ground
        return f"Chão · {self.fs[g['top']].name} por cima ({g['pos']})"


def ai_corner(fight: Fight, fs: FighterState) -> str | None:
    """Ajustes táticos automáticos para lutadores sem treinador humano."""
    opp = fight.other(fs)
    plan = fs.plan
    iq = fs.a("fight_iq")
    rng = fight.rng
    msgs = []
    # estimativa de quem está ganhando (último round nos cartões)
    lead = sum(1 if c[-1][fs.idx] > c[-1][1 - fs.idx] else -1 for c in fight.cards if c)
    if fs.head < 50 and plan.defense == AUTO:
        apply_command(plan, COMMANDS["df_guarda"])
        msgs.append("Mão no queixo!")
    if opp.legs < 65 and fs.f.attributes["kicking"] > 65 and rng.random() < iq / 110:
        apply_command(plan, COMMANDS["tg_pernas"])
        msgs.append("A perna dele tá indo, continua chutando!")
    elif opp.body < 70 and rng.random() < iq / 140:
        apply_command(plan, COMMANDS["tg_corpo"])
        msgs.append("Ele sente no corpo!")
    if fs.legs < 60:
        apply_command(plan, COMMANDS["df_checar"])
        msgs.append("Levanta a perna, checa os chutes!")
    # explorar vícios do adversário
    for h in opp.f.habits:
        if rng.random() < (iq - 60) / 90 and h["trigger"] not in plan.counters:
            resp = h["exploit"]
            plan.counters[h["trigger"]] = resp
            if len(plan.counters) > 2:
                plan.counters.pop(next(iter(plan.counters)))
            msgs.append(f"Ele {h['tell'].split(' ', 1)[1]}. Pune isso!")
            break
    # contra o golpe mais usado pelo adversário
    if opp.thrown and rng.random() < iq / 200 and len(plan.counters) < 2:
        top_strike = max(opp.thrown, key=opp.thrown.get)
        if top_strike == "jab" and "jab" not in plan.counters:
            plan.counters["jab"] = "cross"
            msgs.append("Ele vive do jab. Responde por cima!")
    remaining = fight.rounds - fight.round
    if remaining <= 1 and lead < 0:
        apply_command(plan, COMMANDS["st_tudo"])
        apply_command(plan, COMMANDS["st_finish"])
        msgs.append("Você está perdendo! Precisa do nocaute!")
    elif remaining <= 1 and lead > 0 and iq > 80:
        apply_command(plan, COMMANDS["st_seguro"])
        msgs.append("Round ganho já, luta inteligente!")
    if opp.head < 55:
        plan.finish = True
    plan.recover = True
    if fs.stamina < 45 and fs.a("cardio") < opp.a("cardio"):
        apply_command(plan, COMMANDS["st_poupar"])
        msgs.append("Respira, escolhe os golpes!")
    if fs.a("wrestling") > opp.a("takedown_def") + 5 and fs.total("dmg") < opp.total("dmg") * 0.7:
        apply_command(plan, COMMANDS["gr_quedas"])
        msgs.append("Leva pro chão!")
    return " ".join(msgs[:2]) if msgs else None
