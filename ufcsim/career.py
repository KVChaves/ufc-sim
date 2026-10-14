"""Modo carreira: você é o treinador principal de um lutador."""
from __future__ import annotations

import json
import random
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

from .engine import Fight, Result
from .models import ATTRIBUTE_LABELS, Fighter, load_roster

SAVE_DIR = Path(__file__).resolve().parent.parent / "saves"

# Focos de camp de treino: atributos que podem evoluir
CAMPS = {
    "trocacao": ("Trocação (boxe e chutes)", ["boxing", "kicking", "accuracy", "head_movement", "counter", "footwork"]),
    "wrestling": ("Wrestling (quedas e defesa)", ["wrestling", "takedown_def", "clinch_control", "top_control", "strength"]),
    "jiujitsu": ("Jiu-jitsu (finalização e jogo por baixo)", ["sub_offense", "sub_defense", "bottom_game", "top_control"]),
    "fisico": ("Preparação física (cardio e força)", ["cardio", "strength", "recovery", "hand_speed"]),
    "estudo": ("Estudo do adversário (revela vícios, plano pronto no R1)", []),
}


@dataclass
class Career:
    fighter: Fighter
    date: str
    money: int = 0
    popularity: int = 50
    fights: list = field(default_factory=list)
    suspended_until: str | None = None
    event_no: int = 1
    camp: str | None = None
    scouted: list = field(default_factory=list)

    # ------------------------------------------------------------------ persistência
    @staticmethod
    def path(slot: str = "carreira") -> Path:
        return SAVE_DIR / f"{slot}.json"

    def save(self, slot: str = "carreira") -> Path:
        SAVE_DIR.mkdir(exist_ok=True)
        data = {
            "fighter": self.fighter.to_dict(), "date": self.date, "money": self.money,
            "popularity": self.popularity, "fights": self.fights, "suspended_until": self.suspended_until,
            "event_no": self.event_no, "camp": self.camp, "scouted": self.scouted,
        }
        p = self.path(slot)
        p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        return p

    @classmethod
    def load(cls, slot: str = "carreira") -> "Career | None":
        p = cls.path(slot)
        if not p.exists():
            return None
        d = json.loads(p.read_text(encoding="utf-8"))
        d["fighter"] = Fighter.from_dict(d["fighter"])
        return cls(**d)

    @classmethod
    def new(cls, fighter_id: str, start: date | None = None) -> "Career":
        roster = load_roster()
        return cls(fighter=roster[fighter_id], date=(start or date.today()).isoformat())

    # ------------------------------------------------------------------ fluxo
    @property
    def today(self) -> date:
        return date.fromisoformat(self.date)

    def available_opponents(self) -> list[Fighter]:
        roster = load_roster()
        return [f for f in roster.values() if f.id != self.fighter.id]

    def can_fight(self) -> tuple[bool, str]:
        if self.suspended_until and date.fromisoformat(self.suspended_until) > self.today:
            return False, f"Suspensão médica até {self.suspended_until}."
        return True, ""

    def set_camp(self, camp: str, opponent: Fighter) -> list[str]:
        """Define o foco do camp. Retorna o que foi descoberto (no caso de estudo)."""
        self.camp = camp
        self.scouted = []
        if camp == "estudo":
            self.scouted = [h["tell"] for h in opponent.habits]
            top = sorted(opponent.style["strike_mix"].items(), key=lambda kv: -kv[1])[:3]
            names = {"jab": "jab", "cross": "direto", "hook": "gancho", "uppercut": "uppercut",
                     "overhand": "overhand", "leg_kick": "chute baixo", "calf_kick": "chute na panturrilha",
                     "body_kick": "chute no corpo", "head_kick": "chute alto", "teep": "teep", "knee": "joelhada"}
            self.scouted.append("Golpes favoritos: " + ", ".join(names.get(k, k) for k, _ in top))
            rng = {0: "longa", 1: "média", 2: "curta"}[opponent.style["preferred_range"]]
            self.scouted.append(f"Gosta de lutar na distância {rng}.")
        return self.scouted

    def make_fight(self, opponent: Fighter, rounds: int, seed: int | None = None) -> Fight:
        fight = Fight(self.fighter, opponent, rounds=rounds, seed=seed, coached=0)
        if self.camp == "estudo":
            fight.fs[0].tactical_round = True
        return fight

    def apply_result(self, fight: Fight, opponent: Fighter, rounds: int) -> list[str]:
        """Atualiza cartel, dinheiro, evolução e calendário. Retorna mensagens."""
        rng = random.Random()
        r: Result = fight.result
        me = fight.fs[0]
        rec = self.fighter.record
        msgs = []
        method_key = {"KO": "ko", "TKO": "ko", "SUB": "sub", "DEC": "dec"}.get(r.method, "dec")
        if r.winner == 0:
            rec.wins += 1
            rec.wins_by[method_key] += 1
            res = "W"
        elif r.winner == 1:
            rec.losses += 1
            rec.losses_by[method_key] += 1
            res = "L"
        else:
            rec.draws += 1
            res = "D"
        method_txt = {"KO": f"KO ({r.detail})", "TKO": f"TKO ({r.detail})", "SUB": f"Finalização ({r.detail})",
                      "DEC": f"Decisão {r.detail.split(' (')[0]}", "DRAW": "Empate"}[r.method]
        event = f"UFC SIM {self.event_no}"
        entry = {"result": res, "opponent": opponent.name, "method": method_txt, "event": event,
                 "date": self.date, "round": r.rnd, "time": f"{r.time // 60}:{r.time % 60:02d}"}
        self.fighter.fight_history.insert(0, entry)
        self.fights.insert(0, entry)
        self.event_no += 1

        # bolsa
        purse = 80_000 + self.popularity * 1_000
        bonus = 0
        if res == "W":
            purse *= 2
            if r.method in ("KO", "TKO", "SUB"):
                bonus = 50_000
                msgs.append("Bônus de Performance da Noite: US$ 50.000!")
            self.popularity = min(100, self.popularity + (6 if bonus else 3))
        elif res == "L":
            self.popularity = max(0, self.popularity - 3)
        self.money += purse + bonus
        msgs.append(f"Bolsa: US$ {purse + bonus:,}".replace(",", "."))

        # evolução: camp e idade
        attrs = self.fighter.attributes
        if self.camp in CAMPS and CAMPS[self.camp][1]:
            for key in rng.sample(CAMPS[self.camp][1], k=min(2, len(CAMPS[self.camp][1]))):
                cap = 99
                if attrs[key] < cap and rng.random() < (0.9 if attrs[key] < 85 else 0.5):
                    attrs[key] += 1
                    msgs.append(f"Evolução no camp: {ATTRIBUTE_LABELS[key]} +1")
        age = self.fighter.age(self.today)
        if age >= 33:
            for key in rng.sample(["hand_speed", "chin", "cardio", "recovery", "footwork"], k=2):
                if rng.random() < 0.35 + (age - 33) * 0.1:
                    attrs[key] = max(40, attrs[key] - 1)
                    msgs.append(f"A idade pesa: {ATTRIBUTE_LABELS[key]} -1")
        if r.winner == 1 and r.method in ("KO", "TKO") and rng.random() < 0.5:
            attrs["chin"] = max(40, attrs["chin"] - 1)
            msgs.append("O nocaute deixou marcas: queixo -1")
        if me.head < 35 or (r.winner == 1 and r.method in ("KO", "TKO")):
            days = 60 if me.head > 20 else 90
            self.suspended_until = (self.today + timedelta(days=days)).isoformat()
            msgs.append(f"Suspensão médica de {days} dias.")

        self.camp = None
        self.scouted = []
        self.date = (self.today + timedelta(days=rng.randint(90, 150))).isoformat()
        return msgs
