"""Plano de jogo, árvore de comandos do treinador e córner da IA.

Cada comando ajusta um "slot" do plano de jogo. Comandos genéricos só mudam
pesos; comandos específicos (técnica exata, contra-ataque a um gatilho, alvo +
arma) também dão bônus de execução, porque o lutador sabe exatamente o que
procurar. Quanto mais específico e coerente o plano, melhor o rendimento —
desde que o lutador tenha QI de luta para guardar tudo (ver `capacity`).
"""
from __future__ import annotations

from dataclasses import dataclass, field

AUTO = "auto"


@dataclass
class GamePlan:
    posture: str = AUTO        # pressao | contra | distancia | equilibrado | tudo | seguro
    pace: str = AUTO           # alto | poupar
    target: str = AUTO         # cabeca | corpo | pernas
    weapon: str = AUTO         # id de golpe ou de combinação
    movement: str = AUTO       # direita | esquerda | cortar | centro | entra_sai
    stance: str = AUTO         # orthodox | southpaw
    defense: str = AUTO        # guarda_alta | cabeca | checar | sprawl | mao_forte
    counters: dict = field(default_factory=dict)   # gatilho -> resposta (máx. 2)
    grapple: str = AUTO        # quedas | clinch | evitar
    takedown: str = AUTO       # double | single | level | corpo
    clinch: str = AUTO         # joelhos | cotovelos | boxe_sujo | queda | separar | grade
    ground_top: str = AUTO     # gnp | cotovelos | passar | finalizar | controlar | levantar
    sub_pref: str = AUTO       # id de finalização
    ground_bottom: str = AUTO  # levantar | raspar | finalizar | amarrar
    finish: bool = False       # "termina a luta" quando o adversário estiver machucado
    recover: bool = False      # "segura e respira" quando estiver machucado

    SLOTS = ("posture", "pace", "target", "weapon", "movement", "stance", "defense", "grapple",
             "takedown", "clinch", "ground_top", "sub_pref", "ground_bottom")

    def specific_count(self) -> int:
        n = sum(1 for s in self.SLOTS if getattr(self, s) != AUTO)
        return n + len(self.counters) + int(self.finish) + int(self.recover)

    def copy(self) -> "GamePlan":
        p = GamePlan(**{k: getattr(self, k) for k in self.SLOTS})
        p.counters = dict(self.counters)
        p.finish, p.recover = self.finish, self.recover
        return p


def capacity(fight_iq: float) -> int:
    """Quantas instruções específicas o lutador consegue manter na cabeça."""
    return 4 + int(fight_iq // 22)


@dataclass(frozen=True)
class Command:
    id: str
    label: str
    slot: str
    value: object
    level: int          # 1 = genérico, 2 = direcionado, 3 = técnico/específico
    shout: str          # o que o treinador grita


@dataclass(frozen=True)
class Category:
    key: str
    label: str
    commands: tuple


def _c(id, label, slot, value, level, shout):
    return Command(id, label, slot, value, level, shout)


CATEGORIES: tuple[Category, ...] = (
    Category("1", "Estratégia", (
        _c("st_pressao", "Pressione, ande pra frente", "posture", "pressao", 1, "Pra frente! Pressiona ele!"),
        _c("st_contra", "Lute no contra-ataque", "posture", "contra", 1, "Deixa ele vir! Contra-ataca!"),
        _c("st_distancia", "Mantenha a distância", "posture", "distancia", 1, "Distância! Luta de fora!"),
        _c("st_equil", "Luta equilibrada", "posture", "equilibrado", 1, "Calma, luta o teu jogo!"),
        _c("st_tudo", "Tudo ou nada: busque o nocaute", "posture", "tudo", 1, "Vai com tudo! Precisa do nocaute!"),
        _c("st_seguro", "Lute seguro, administre", "posture", "seguro", 1, "Sem riscos! Administra!"),
        _c("st_ritmo_alto", "Aumente o ritmo / volume", "pace", "alto", 1, "Aumenta o volume! Mais mãos!"),
        _c("st_poupar", "Poupe energia", "pace", "poupar", 1, "Respira, escolhe os golpes!"),
        _c("st_ritmo_auto", "Ritmo normal", "pace", AUTO, 1, "Ritmo normal!"),
        _c("st_finish", "Machucou? Termina a luta!", "finish", True, 2, "Ele sentiu! Termina! Termina!"),
        _c("st_recover", "Se sentir, segura e respira", "recover", True, 2, "Se sentir, amarra e respira!"),
        _c("st_reset", "Esqueça tudo, volte ao básico", "reset", None, 1, "Esquece tudo! Volta pro básico!"),
    )),
    Category("2", "Alvo", (
        _c("tg_cabeca", "Foque na cabeça", "target", "cabeca", 2, "Na cabeça! Procura o queixo!"),
        _c("tg_corpo", "Trabalhe o corpo", "target", "corpo", 2, "No corpo! Mata o gás dele!"),
        _c("tg_pernas", "Destrua as pernas", "target", "pernas", 2, "Na perna! Tira a base dele!"),
        _c("tg_auto", "Varie os alvos", "target", AUTO, 1, "Mistura os alvos!"),
    )),
    Category("3", "Golpes: mãos", (
        _c("w_jab", "Foque no jab", "weapon", "jab", 3, "Jab! Jab! Usa o jab!"),
        _c("w_1-1-2", "Dobre o jab e solte o direto (1-1-2)", "weapon", "1-1-2", 3, "Dobra o jab e solta a direita!"),
        _c("w_1-2", "Jab-direto (1-2)", "weapon", "1-2", 3, "Um-dois! Um-dois!"),
        _c("w_1-2-3", "Jab-direto-gancho (1-2-3)", "weapon", "1-2-3", 3, "Um-dois e o gancho!"),
        _c("w_corpo-cabeca", "Jab no corpo, direto na cabeça", "weapon", "corpo-cabeca", 3, "Desce no corpo e sobe na cabeça!"),
        _c("w_gancho-figado", "Direto e gancho no fígado", "weapon", "gancho-figado", 3, "Gancho no fígado!"),
        _c("w_hook", "Gancho de esquerda", "weapon", "hook", 3, "O gancho! Vai entrar o gancho!"),
        _c("w_uppercut", "Uppercut", "weapon", "uppercut", 3, "Uppercut! Ele tá baixando a cabeça!"),
        _c("w_overhand", "Overhand por cima", "weapon", "overhand", 3, "Por cima! A direita por cima!"),
        _c("w_finta", "Finta o jab e solta o overhand", "weapon", "finta-overhand", 3, "Finta e vai na direita!"),
        _c("w_2-3-up", "Direto-gancho-uppercut no bolso", "weapon", "2-3-up", 3, "Dentro! Direto, gancho, uppercut!"),
        _c("w_auto", "Solte as mãos naturalmente", "weapon", AUTO, 1, "Luta solto!"),
    )),
    Category("4", "Golpes: chutes", (
        _c("w_calf", "Chute na panturrilha", "weapon", "calf_kick", 3, "Panturrilha! Chuta a panturrilha!"),
        _c("w_low", "Chute baixo na coxa", "weapon", "leg_kick", 3, "Chuta a perna!"),
        _c("w_body_kick", "Chute no corpo", "weapon", "body_kick", 3, "Chute no corpo!"),
        _c("w_head_kick", "Chute alto", "weapon", "head_kick", 3, "Chute alto! Ele tá de guarda baixa!"),
        _c("w_teep", "Teep para manter distância", "weapon", "teep", 3, "Teep! Empurra ele!"),
        _c("w_1-2-low", "1-2 e fecha com chute baixo", "weapon", "1-2-low", 3, "Um-dois e chuta!"),
        _c("w_1-2-body", "1-2 e fecha com chute no corpo", "weapon", "1-2-body-kick", 3, "Um-dois e chute no corpo!"),
        _c("w_spin", "Chute rodado", "weapon", "spinning_kick", 3, "Vai no rodado!"),
    )),
    Category("5", "Movimentação", (
        _c("mv_direita", "Ande para a direita", "movement", "direita", 2, "Pra direita! Anda pra direita!"),
        _c("mv_esquerda", "Ande para a esquerda", "movement", "esquerda", 2, "Pra esquerda! Gira pra esquerda!"),
        _c("mv_cortar", "Corte o octógono, prenda na grade", "movement", "cortar", 2, "Corta o caminho! Prende ele na grade!"),
        _c("mv_centro", "Saia da grade, volte ao centro", "movement", "centro", 2, "Sai da grade! Centro!"),
        _c("mv_entra_sai", "Entra e sai (bate e sai)", "movement", "entra_sai", 3, "Bate e sai! Não fica parado!"),
        _c("mv_auto", "Movimentação livre", "movement", AUTO, 1, "Movimenta!"),
        _c("sw_orthodox", "Fique na base ortodoxa", "stance", "orthodox", 3, "Base normal!"),
        _c("sw_southpaw", "Troque para southpaw", "stance", "southpaw", 3, "Troca a base! Canhoto!"),
        _c("sw_auto", "Base livre", "stance", AUTO, 1, "Base livre!"),
    )),
    Category("6", "Defesa", (
        _c("df_guarda", "Guarda alta", "defense", "guarda_alta", 2, "Mão no queixo! Guarda alta!"),
        _c("df_cabeca", "Mexa a cabeça", "defense", "cabeca", 2, "Mexe a cabeça! Não fica na linha!"),
        _c("df_checar", "Cheque os chutes", "defense", "checar", 3, "Levanta a perna! Checa o chute!"),
        _c("df_sprawl", "Cuidado com a queda (sprawl)", "defense", "sprawl", 3, "Olha a queda! Quadril pra trás!"),
        _c("df_mao_forte", "Cuidado com a mão forte dele", "defense", "mao_forte", 3, "Cuidado com a direita dele!"),
        _c("df_auto", "Defesa natural", "defense", AUTO, 1, "Defende natural!"),
    )),
    Category("7", "Contra-ataques", (
        _c("ct_jab_cross", "Ele jabbar → direto por cima", "counter", ("jab", "cross"), 3, "Quando ele jabbar, direita por cima!"),
        _c("ct_jab_overhand", "Ele jabbar → overhand", "counter", ("jab", "overhand"), 3, "Jab dele, overhand por cima!"),
        _c("ct_jab_hook", "Ele jabbar → esquiva e gancho", "counter", ("jab", "hook"), 3, "Sai do jab e volta no gancho!"),
        _c("ct_entra_upper", "Ele entrar → uppercut", "counter", ("entrada", "uppercut"), 3, "Quando ele entrar, uppercut!"),
        _c("ct_entra_knee", "Ele entrar → joelhada", "counter", ("entrada", "knee"), 3, "Ele vai abaixar, joelho!"),
        _c("ct_entra_hook", "Ele entrar → gancho girando", "counter", ("entrada", "hook"), 3, "Gira e solta o gancho quando ele vier!"),
        _c("ct_power_hook", "Ele soltar a mão forte → gancho", "counter", ("power", "hook"), 3, "Bloqueia a direita e volta o gancho!"),
        _c("ct_hook_cross", "Ele soltar o gancho → direto", "counter", ("hook", "cross"), 3, "Ele abre o gancho! Direto no meio!"),
        _c("ct_kick_cross", "Ele chutar → direto", "counter", ("kick", "cross"), 3, "Chutou, devolve o direto!"),
        _c("ct_kick_catch", "Ele chutar → agarra e derruba", "counter", ("kick", "catch"), 3, "Pega o chute e derruba!"),
        _c("ct_td_knee", "Ele tentar queda → joelhada", "counter", ("takedown", "knee"), 3, "Se ele baixar, joelho!"),
        _c("ct_td_guillo", "Ele tentar queda → guilhotina", "counter", ("takedown", "guillotine"), 3, "Se ele entrar na queda, pega o pescoço!"),
        _c("ct_clear", "Limpar contra-ataques", "counter_clear", None, 1, "Esquece os contra-ataques!"),
    )),
    Category("8", "Clinch e quedas", (
        _c("gr_quedas", "Busque as quedas", "grapple", "quedas", 2, "Leva pro chão!"),
        _c("gr_double", "Double leg", "takedown", "double", 3, "Baixa e entra nas duas pernas!"),
        _c("gr_single", "Single leg", "takedown", "single", 3, "Pega uma perna!"),
        _c("gr_level", "Combinação e troca de nível pra queda", "takedown", "level", 3, "Solta a mão e troca de nível!"),
        _c("gr_clinch", "Clinche na grade", "grapple", "clinch", 2, "Amarra ele na grade!"),
        _c("gr_evitar", "Evite o grappling", "grapple", "evitar", 2, "Não deixa ele agarrar!"),
        _c("cl_joelhos", "No clinch: joelhadas", "clinch", "joelhos", 3, "Joelho! Joelho no corpo!"),
        _c("cl_cotovelos", "No clinch: cotoveladas", "clinch", "cotovelos", 3, "Cotovelo curto!"),
        _c("cl_boxe_sujo", "No clinch: boxe sujo", "clinch", "boxe_sujo", 3, "Solta a mão de dentro!"),
        _c("cl_queda", "No clinch: queda por baixo do corpo", "clinch", "queda", 3, "Trava o corpo e derruba!"),
        _c("cl_separar", "No clinch: separe e volte pra distância", "clinch", "separar", 2, "Sai do clinch!"),
        _c("gr_auto", "Grappling livre", "grapple", AUTO, 1, "Luta solto!"),
    )),
    Category("9", "Chão", (
        _c("gt_gnp", "Por cima: ground and pound", "ground_top", "gnp", 2, "Bate! Ground and pound!"),
        _c("gt_cotovelos", "Por cima: cotoveladas", "ground_top", "cotovelos", 3, "Cotovelo! Abre ele!"),
        _c("gt_passar", "Por cima: passe a guarda / pegue a montada", "ground_top", "passar", 3, "Passa a guarda! Monta!"),
        _c("gt_finalizar", "Por cima: busque a finalização", "ground_top", "finalizar", 2, "Procura a finalização!"),
        _c("gt_rnc", "Finalização: mata-leão (pegue as costas)", "sub_pref", "rnc", 3, "Pega as costas! Mata-leão!"),
        _c("gt_arm_tri", "Finalização: katagatame", "sub_pref", "arm_triangle", 3, "Encaixa o katagatame!"),
        _c("gt_kimura", "Finalização: kimura", "sub_pref", "kimura", 3, "Pega a kimura!"),
        _c("gt_controlar", "Por cima: controle e segure", "ground_top", "controlar", 2, "Segura! Controla!"),
        _c("gt_levantar", "Por cima: levante e deixe ele subir", "ground_top", "levantar", 2, "Levanta! Volta pra trocação!"),
        _c("gb_levantar", "Por baixo: levante pela grade", "ground_bottom", "levantar", 2, "Levanta! Usa a grade!"),
        _c("gb_raspar", "Por baixo: raspagem", "ground_bottom", "raspar", 3, "Raspa! Inverte!"),
        _c("gb_finalizar", "Por baixo: finalize da guarda", "ground_bottom", "finalizar", 3, "Ataca da guarda!"),
        _c("gb_amarrar", "Por baixo: amarre e espere o juiz", "ground_bottom", "amarrar", 2, "Amarra! Não deixa ele bater!"),
        _c("gd_sub", "Defenda finalizações (mãos e quadril)", "defense", "finalizacao", 3, "Protege o pescoço! Mão, mão!"),
    )),
)

COMMANDS: dict[str, Command] = {c.id: c for cat in CATEGORIES for c in cat.commands}

# Instruções de intervalo (uma por intervalo)
CORNER_ACTIONS = (
    ("respirar", "Respiração e gelo (recupera mais gás)"),
    ("corte", "Tratar cortes e inchaço (reduz sangramento/dano)"),
    ("motivar", "Discurso motivacional (frieza e coração no próximo round)"),
    ("tatico", "Ajuste tático detalhado (instruções valem 100% no próximo round)"),
)

COUNTER_TRIGGER_LABELS = {"jab": "jab dele", "entrada": "entrada dele", "power": "mão forte dele",
                          "hook": "gancho dele", "kick": "chute dele", "takedown": "queda dele"}


def apply_command(plan: GamePlan, cmd: Command) -> None:
    if cmd.slot == "reset":
        fresh = GamePlan()
        for k in GamePlan.SLOTS:
            setattr(plan, k, getattr(fresh, k))
        plan.counters.clear()
        plan.finish = plan.recover = False
    elif cmd.slot == "counter":
        trig, resp = cmd.value
        plan.counters.pop(trig, None)
        if len(plan.counters) >= 2:
            plan.counters.pop(next(iter(plan.counters)))
        plan.counters[trig] = resp
    elif cmd.slot == "counter_clear":
        plan.counters.clear()
    elif cmd.slot in ("finish", "recover"):
        setattr(plan, cmd.slot, cmd.value)
    else:
        setattr(plan, cmd.slot, cmd.value)
        # alguns comandos puxam o slot "pai" para ficar coerente
        if cmd.slot == "takedown":
            plan.grapple = "quedas"
        elif cmd.slot == "sub_pref":
            plan.ground_top = "finalizar"


def describe_plan(plan: GamePlan) -> list[str]:
    from .moves import COMBOS, STRIKES, SUBMISSIONS
    out = []
    labels = {(c.slot, c.value): c.label for c in COMMANDS.values()}
    for slot, title in (("posture", "Estratégia"), ("pace", "Ritmo"), ("target", "Alvo"), ("weapon", "Arma"),
                        ("movement", "Movimento"), ("stance", "Base"), ("defense", "Defesa"),
                        ("grapple", "Grappling"), ("takedown", "Queda"), ("clinch", "Clinch"),
                        ("ground_top", "Chão (cima)"), ("sub_pref", "Finalização"), ("ground_bottom", "Chão (baixo)")):
        v = getattr(plan, slot)
        if v == AUTO:
            continue
        if slot == "weapon":
            txt = COMBOS[v][0] if v in COMBOS else STRIKES[v].name.format(lead="esq.", rear="dir.")
        elif slot == "sub_pref":
            txt = SUBMISSIONS[v].name
        else:
            txt = labels.get((slot, v), str(v))
        out.append(f"{title}: {txt}")
    for trig, resp in plan.counters.items():
        resp_txt = {"catch": "agarrar chute", "guillotine": "guilhotina"}.get(resp)
        if resp_txt is None:
            resp_txt = STRIKES[resp].name.format(lead="esq.", rear="dir.")
        out.append(f"Contra: {COUNTER_TRIGGER_LABELS[trig]} → {resp_txt}")
    if plan.finish:
        out.append("Finalizar quando machucar")
    if plan.recover:
        out.append("Segurar quando machucado")
    return out
