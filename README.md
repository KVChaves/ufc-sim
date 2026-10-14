# UFC SIM

Simulador de MMA com elenco real do UFC e modo treinador estilo Football Manager. A luta corre em tempo real no navegador e você grita as instruções do córner enquanto ela acontece. Só usa a biblioteca padrão do Python (3.10+).

```bash
python3 main.py                          # abre o jogo no navegador (http://127.0.0.1:8765)
python3 main.py --porta 9000             # outra porta
python3 main.py --sem-navegador          # só sobe o servidor
python3 main.py --terminal               # versão antiga em terminal (curses)
python3 main.py --texto -r 5 --seed 7    # narra uma luta inteira em texto puro
python3 main.py --lote 500 -r 5          # 500 lutas, comparadas com as estatísticas reais
python3 tools/coach_test.py 300          # mede o impacto de planos de treinador
```

O motor roda no Python (`ufcsim/engine.py`) e o servidor local (`ufcsim/web.py`) avança o relógio da luta. A interface fica em `web/` (HTML, CSS e JS puros).

## Tela de luta

- **Placar:** relógio, round e posição (em pé e distância, clinch, chão). Para cada lutador mostra gás, cabeça, corpo e pernas, e etiquetas do que ele está fazendo agora: a estratégia que você passou ou a natureza dele.
- **Narração:** em tempo real, com linhas de leitura (◆) e a confirmação quando o lutador recebe a instrução.
- **Painel do córner:** gritos rápidos, instruções por categoria e o plano atual, com limite de instruções e botão × para remover.
- **Controles:** pausa (Espaço) e velocidade de 1× a 16×. O padrão é 4×, ou seja, um round de 5 minutos em 75 segundos.
- **Pré-luta:** você monta a estratégia inicial. Depois o relógio corre sem parar.
- **Intervalo:** 60 segundos para escolher uma ação de córner, ajustar o plano ou jogar a toalha.

## Elenco

Arquivo `ufcsim/data/fighters.json`. Por enquanto só tem **Ilia Topuria** (17-1) e **Max Holloway** (28-9), com dados atualizados em 13/10/2026:

- dados pessoais (nascimento, altura, envergadura, peso, base), cartel completo e estatísticas oficiais do UFC;
- `attributes`: notas de 0 a 100 usadas pelo motor (avaliações do jogo, não dados oficiais);
- `style`: distância preferida, mistura de golpes, pressão, tendência a contra-atacar etc.;
- `habits`: vícios que o treinador adversário pode ler e punir.

Para adicionar um lutador, copie um bloco existente e ajuste os campos.

## O motor

- A luta é simulada segundo a segundo, com fases em pé, no clinch, no chão e em finalização.
- Em pé contam a distância (longa, média, curta), a grade, a lateralidade (circular para o lado da mão forte é perigoso) e a base (ortodoxa ou canhota).
- O dano é separado em cabeça, corpo e pernas, e há gás, cortes, atordoamento em níveis, knockdown, intervenção do árbitro, do médico e do córner.
- Cada round é pontuado por três juízes no sistema de 10 pontos.

Calibração atual, Topuria × Holloway em 500 lutas de 5 rounds:

| | Vitórias | Golpes sig./min | Precisão | KO/TKO | Decisão |
|---|---|---|---|---|---|
| Topuria | ~63% | 4,2 (real 4,82) | 53% (real 50%) | ~37% | ~21% |
| Holloway | ~35% | 6,0 (real 6,92) | 48% (real 48%) | ~15% | ~20% |

Em 3 rounds, Topuria vence ~75%. Em 5 rounds, o cardio do Holloway pesa nos rounds finais.

## Modo treinador

Os comandos montam um plano de jogo em slots: estratégia, alvo, arma, movimentação, defesa, contra-ataques, grappling e chão. São três níveis:

- `·` **genérico**: muda tendências (pressão, ritmo).
- `··` **direcionado**: muda alvo ou área (trabalhar o corpo, andar para a direita).
- `···` **técnico**: técnica exata ou reação a um gatilho ("quando ele entrar → uppercut"). Dá bônus de execução.

Algumas regras:

- O lutador guarda um número limitado de instruções, que depende do QI de luta. Passar do limite ou mudar o plano toda hora reduz a execução.
- Machucado, ele não ouve o córner.
- Linhas `◆ Leitura` no log revelam vícios do adversário. Punir o gatilho certo com a resposta certa dá um bônus grande.
- No intervalo você escolhe uma ação de córner (gelo, cutman, motivação ou ajuste tático) e pode jogar a toalha.

Resultado de `tools/coach_test.py` (Holloway treinado contra Topuria):

| Plano do Holloway | Vitórias |
|---|---|
| Sem comandos (e sem o córner automático da IA) | ~12% |
| Genérico ("pressione", "tudo ou nada") | ~35% |
| Específico (direita, cuidado com a mão forte, uppercut na entrada etc.) | ~56% |

## Carreira

Você escolhe um lutador e, a cada luta:

1. Escolhe o adversário e o formato (3 ou 5 rounds).
2. Escolhe o foco do camp: trocação, wrestling, jiu-jitsu, físico ou estudo do adversário. O estudo revela os vícios dele e deixa o plano 100% claro no R1.
3. Treina o lutador durante a luta.

Depois de cada luta o jogo atualiza cartel, bolsa e bônus, popularidade, evolução dos atributos, declínio por idade (a partir dos 33 anos) e suspensão médica. O save fica em `saves/carreira.json`.
