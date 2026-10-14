"""Modelos de dados estáticos dos lutadores e carregamento do elenco."""
from __future__ import annotations

import copy
import json
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

DATA_FILE = Path(__file__).parent / "data" / "fighters.json"

ATTRIBUTE_GROUPS = {
    "Trocação": ["boxing", "kicking", "clinch_striking", "power", "hand_speed", "accuracy",
                 "head_movement", "footwork", "volume", "counter"],
    "Grappling": ["wrestling", "takedown_def", "clinch_control", "top_control", "bottom_game",
                  "sub_offense", "sub_defense", "ground_strikes"],
    "Físico": ["cardio", "chin", "body_toughness", "leg_toughness", "recovery", "strength"],
    "Mental": ["fight_iq", "composure", "aggression", "heart"],
}

ATTRIBUTE_LABELS = {
    "boxing": "Boxe", "kicking": "Chutes", "clinch_striking": "Golpes no clinch", "power": "Potência",
    "hand_speed": "Velocidade de mão", "accuracy": "Precisão", "head_movement": "Esquiva",
    "footwork": "Movimentação", "volume": "Volume", "counter": "Contra-ataque",
    "wrestling": "Wrestling (quedas)", "takedown_def": "Defesa de queda", "clinch_control": "Controle no clinch",
    "top_control": "Controle por cima", "bottom_game": "Jogo por baixo", "sub_offense": "Finalização",
    "sub_defense": "Defesa de finalização", "ground_strikes": "Ground and pound",
    "cardio": "Cardio", "chin": "Queixo", "body_toughness": "Resistência do corpo",
    "leg_toughness": "Resistência das pernas", "recovery": "Recuperação", "strength": "Força",
    "fight_iq": "QI de luta", "composure": "Frieza", "aggression": "Agressividade", "heart": "Coração",
}


@dataclass
class Record:
    wins: int = 0
    losses: int = 0
    draws: int = 0
    wins_by: dict = field(default_factory=lambda: {"ko": 0, "sub": 0, "dec": 0})
    losses_by: dict = field(default_factory=lambda: {"ko": 0, "sub": 0, "dec": 0})

    def __str__(self) -> str:
        return f"{self.wins}-{self.losses}-{self.draws}"


@dataclass
class Fighter:
    id: str
    name: str
    short: str
    nickname: str
    nationality: str
    hometown: str
    team: str
    birthdate: str
    height_cm: int
    reach_cm: int
    leg_reach_cm: int
    weight_lbs: int
    division: str
    stance: str
    base_style: str
    record: Record
    fight_history: list
    ufc_stats: dict
    attributes: dict
    style: dict
    habits: list

    def attr(self, key: str) -> float:
        return float(self.attributes[key])

    def age(self, on: date | None = None) -> int:
        on = on or date.today()
        b = date.fromisoformat(self.birthdate)
        return on.year - b.year - ((on.month, on.day) < (b.month, b.day))

    @property
    def overall(self) -> int:
        a = self.attributes
        return round(sum(a.values()) / len(a))

    def to_dict(self) -> dict:
        d = copy.deepcopy(self.__dict__)
        d["record"] = copy.deepcopy(self.record.__dict__)
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "Fighter":
        d = copy.deepcopy(d)
        d["record"] = Record(**d["record"])
        return cls(**d)


def load_roster(path: Path = DATA_FILE) -> dict[str, Fighter]:
    with open(path, encoding="utf-8") as fh:
        raw = json.load(fh)
    return {f["id"]: Fighter.from_dict(f) for f in raw["fighters"]}


def cm_to_ft(cm: float) -> str:
    inches = round(cm / 2.54)
    return f"{inches // 12}'{inches % 12}\""
