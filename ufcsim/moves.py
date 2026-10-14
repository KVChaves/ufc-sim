"""Golpes, combinações, finalizações e posições de chão."""
from __future__ import annotations

from dataclasses import dataclass

# Distâncias em pé
LONGE, MEDIA, CURTA = 0, 1, 2
RANGE_NAMES = {LONGE: "longa distância", MEDIA: "média distância", CURTA: "curta distância"}


@dataclass(frozen=True)
class Strike:
    id: str
    name: str              # pode conter {lead}/{rear} (mão/perna da frente e de trás)
    kind: str              # punch | kick | knee | elbow
    side: str              # lead | rear
    targets: dict          # alvo -> (precisão base, dano base)
    best_range: int
    stamina: float
    skill: str             # atributo de técnica
    power: bool            # golpe de força (dispara gatilhos "power")

    def label(self, stance: str, target: str | None = None) -> str:
        lead, rear = ("esquerda", "direita") if stance == "orthodox" else ("direita", "esquerda")
        txt = self.name.format(lead=lead, rear=rear)
        if target == "body" and self.kind in ("punch", "knee"):
            txt += " no corpo"
        return txt


STRIKES: dict[str, Strike] = {s.id: s for s in [
    Strike("jab", "jab", "punch", "lead", {"head": (0.40, 2.2), "body": (0.55, 1.8)}, MEDIA, 0.45, "boxing", False),
    Strike("cross", "direto de {rear}", "punch", "rear", {"head": (0.36, 5.8), "body": (0.52, 4.4)}, MEDIA, 0.9, "boxing", True),
    Strike("hook", "gancho de {lead}", "punch", "lead", {"head": (0.33, 6.3), "body": (0.50, 5.4)}, CURTA, 0.9, "boxing", True),
    Strike("uppercut", "uppercut de {rear}", "punch", "rear", {"head": (0.30, 6.6), "body": (0.48, 4.4)}, CURTA, 0.9, "boxing", True),
    Strike("overhand", "overhand de {rear}", "punch", "rear", {"head": (0.27, 8.2)}, MEDIA, 1.2, "boxing", True),
    Strike("calf_kick", "chute na panturrilha", "kick", "rear", {"leg": (0.62, 4.6)}, MEDIA, 1.1, "kicking", False),
    Strike("leg_kick", "chute baixo de {rear}", "kick", "rear", {"leg": (0.60, 5.0)}, MEDIA, 1.3, "kicking", False),
    Strike("body_kick", "chute de {rear} no corpo", "kick", "rear", {"body": (0.52, 7.0)}, MEDIA, 1.7, "kicking", True),
    Strike("head_kick", "chute alto de {rear}", "kick", "rear", {"head": (0.22, 13.5)}, MEDIA, 2.1, "kicking", True),
    Strike("teep", "chute frontal (teep)", "kick", "lead", {"body": (0.52, 2.0)}, MEDIA, 0.9, "kicking", False),
    Strike("knee", "joelhada", "knee", "rear", {"head": (0.30, 10.0), "body": (0.55, 6.0)}, CURTA, 1.3, "clinch_striking", True),
    Strike("spinning_kick", "chute rodado", "kick", "rear", {"body": (0.32, 9.0), "head": (0.17, 14.0)}, MEDIA, 2.4, "kicking", True),
    Strike("elbow", "cotovelada", "elbow", "rear", {"head": (0.40, 6.5)}, CURTA, 0.8, "clinch_striking", True),
]}

PUNCHES = {"jab", "cross", "hook", "uppercut", "overhand"}
KICKS = {"calf_kick", "leg_kick", "body_kick", "head_kick", "teep", "spinning_kick"}

# Combinações predefinidas: (rótulo, [(golpe, alvo|None)])
COMBOS: dict[str, tuple[str, list]] = {
    "1-2": ("jab-direto", [("jab", "head"), ("cross", "head")]),
    "1-1-2": ("jab duplo e direto", [("jab", "head"), ("jab", "head"), ("cross", "head")]),
    "1-2-3": ("jab-direto-gancho", [("jab", "head"), ("cross", "head"), ("hook", "head")]),
    "1-2-3-2": ("jab-direto-gancho-direto", [("jab", "head"), ("cross", "head"), ("hook", "head"), ("cross", "head")]),
    "corpo-cabeca": ("jab no corpo e direto na cabeça", [("jab", "body"), ("cross", "head")]),
    "gancho-figado": ("direto e gancho no fígado", [("cross", "head"), ("hook", "body")]),
    "3-2": ("gancho e direto", [("hook", "head"), ("cross", "head")]),
    "2-3-up": ("direto-gancho-uppercut", [("cross", "head"), ("hook", "head"), ("uppercut", "head")]),
    "1-2-low": ("jab-direto e chute baixo", [("jab", "head"), ("cross", "head"), ("leg_kick", "leg")]),
    "1-2-body-kick": ("jab-direto e chute no corpo", [("jab", "head"), ("cross", "head"), ("body_kick", "body")]),
    "jab-overhand": ("jab e overhand", [("jab", "head"), ("overhand", "head")]),
    "finta-overhand": ("finta de jab e overhand", [("overhand", "head")]),
}

# Golpes que costumam seguir cada golpe (montagem orgânica de combinações)
FOLLOW_UPS = {
    "jab": {"jab": 3, "cross": 6, "hook": 1, "overhand": 1, "leg_kick": 1},
    "cross": {"hook": 6, "leg_kick": 2, "body_kick": 1, "uppercut": 1, "cross": 1},
    "hook": {"cross": 5, "uppercut": 2, "hook": 1},
    "uppercut": {"hook": 5, "cross": 2},
    "overhand": {"hook": 4, "uppercut": 1},
    "calf_kick": {"cross": 1},
    "leg_kick": {"cross": 1},
    "body_kick": {"cross": 1},
    "teep": {"jab": 1},
    "knee": {"hook": 1, "elbow": 1},
    "spinning_kick": {"cross": 1},
    "head_kick": {"cross": 1},
    "elbow": {"knee": 1, "elbow": 1},
}


@dataclass(frozen=True)
class Submission:
    id: str
    name: str
    kind: str              # choke | joint
    top: tuple             # posições (por cima) de onde sai
    bottom: tuple          # posições (por baixo) de onde sai
    ease: float            # facilidade relativa


SUBMISSIONS: dict[str, Submission] = {s.id: s for s in [
    Submission("rnc", "mata-leão", "choke", ("costas",), (), 1.25),
    Submission("arm_triangle", "katagatame (arm-triangle)", "choke", ("meia-guarda", "cem-quilos", "montada"), (), 1.0),
    Submission("kimura", "kimura", "joint", ("meia-guarda", "cem-quilos"), ("guarda",), 0.85),
    Submission("armbar", "chave de braço", "joint", ("montada",), ("guarda",), 0.9),
    Submission("americana", "americana", "joint", ("cem-quilos", "montada"), (), 0.75),
    Submission("triangle", "triângulo", "choke", (), ("guarda",), 0.9),
    Submission("guillotine", "guilhotina", "choke", (), ("guarda",), 0.9),
]}

# Posições de chão em ordem de domínio do lutador de cima
GROUND_POSITIONS = ["guarda", "meia-guarda", "cem-quilos", "montada", "costas"]
GNP_MULT = {"guarda": 0.55, "meia-guarda": 0.8, "cem-quilos": 0.95, "montada": 1.35, "costas": 1.05}
GNP_ACC = {"guarda": 0.42, "meia-guarda": 0.52, "cem-quilos": 0.55, "montada": 0.62, "costas": 0.55}
