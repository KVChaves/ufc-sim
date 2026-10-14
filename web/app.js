"use strict";

// ------------------------------------------------------------------ utilidades
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const api = {
  get: async (p) => (await fetch(p)).json(),
  post: async (p, body = {}) =>
    (await fetch(p, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) })).json(),
};
const ft = (cm) => { const i = Math.round(cm / 2.54); return `${Math.floor(i / 12)}'${i % 12}"`; };
const money = (n) => "US$ " + Number(n).toLocaleString("pt-BR");

let META = null;
let ROSTER = [];
let current = "home";
let toastTimer = null;

function toast(msg) {
  const t = $("#toast");
  t.textContent = msg;
  t.classList.remove("hidden");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => t.classList.add("hidden"), 1600);
}

function modal(html) {
  $("#modal-card").innerHTML = html;
  $("#modal").classList.remove("hidden");
}
function closeModal() { $("#modal").classList.add("hidden"); }

// ------------------------------------------------------------------ navegação
function show(view) {
  if (current === "fight" && view !== "fight" && F.state && F.state.mode === "live" && !F.state.paused) {
    api.post("/api/fight/pause", { paused: true });
    toast("Luta pausada");
  }
  current = view;
  if (location.hash !== "#" + view) history.replaceState(null, "", "#" + view);
  $$(".view").forEach((v) => v.classList.toggle("on", v.id === "view-" + view));
  $$(".topbar nav a").forEach((a) => a.classList.toggle("on", a.dataset.nav === view));
  window.scrollTo(0, 0);
  if (view === "quick") renderQuick();
  if (view === "fighters") renderRoster();
  if (view === "career") renderCareer();
  if (view === "lab") renderLab();
  if (view === "fight") poll(true);
}

document.addEventListener("click", (e) => {
  const nav = e.target.closest("[data-nav]");
  if (nav) { e.preventDefault(); show(nav.dataset.nav); }
});

document.addEventListener("keydown", (e) => {
  if (current !== "fight" || e.target.matches("input, select, textarea")) return;
  if (e.code === "Space") { e.preventDefault(); togglePause(); }
});

// ------------------------------------------------------------------ luta rápida
const Q = { red: null, blue: null, rounds: 5, coach: "1" };

function pickCard(f, corner) {
  const sel = Q[corner] === f.id;
  const other = Q[corner === "red" ? "blue" : "red"] === f.id;
  return `<button class="pick ${sel ? "on" : ""} ${other ? "disabled" : ""}" data-corner="${corner}" data-id="${f.id}">
    <div class="pick-ovr">${f.overall}</div>
    <div><div class="pick-name">${esc(f.name)}</div>
    <div class="pick-sub">${esc(f.record_str)} · ${esc(f.division)} · ${f.age} anos · ${esc(f.base_style)}</div></div></button>`;
}

function renderQuick() {
  if (!Q.red) Q.red = ROSTER[0]?.id;
  if (!Q.blue) Q.blue = ROSTER.find((f) => f.id !== Q.red)?.id;
  $("#pick-red").innerHTML = ROSTER.map((f) => pickCard(f, "red")).join("");
  $("#pick-blue").innerHTML = ROSTER.map((f) => pickCard(f, "blue")).join("");
  const names = { red: ROSTER.find((f) => f.id === Q.red)?.short, blue: ROSTER.find((f) => f.id === Q.blue)?.short };
  const cb = $$("#opt-coach button");
  cb[0].textContent = `Treinador de ${names.red || "vermelho"}`;
  cb[1].textContent = `Treinador de ${names.blue || "azul"}`;
}

$("#view-quick").addEventListener("click", (e) => {
  const p = e.target.closest(".pick");
  if (p) { Q[p.dataset.corner] = p.dataset.id; renderQuick(); }
  const seg = e.target.closest(".seg button");
  if (seg) {
    $$("button", seg.parentElement).forEach((b) => b.classList.toggle("on", b === seg));
    if (seg.parentElement.id === "opt-rounds") Q.rounds = +seg.dataset.v;
    if (seg.parentElement.id === "opt-coach") Q.coach = seg.dataset.v;
  }
});

async function startQuick() {
  if (!Q.red || !Q.blue || Q.red === Q.blue) return toast("Escolha dois lutadores diferentes");
  const coached = Q.coach === "none" ? null : +Q.coach;
  await api.post("/api/fight/new", { red: Q.red, blue: Q.blue, rounds: Q.rounds, coached });
  F.reset();
  show("fight");
}
$("#btn-start-quick").addEventListener("click", startQuick);

// ------------------------------------------------------------------ tela de luta
const F = {
  state: null, next: 0, id: null, timer: null, cat: 0, tab: "feed",
  tacticsSig: "", bannerSig: "", endShown: false,
  reset() {
    this.state = null; this.next = 0; this.id = null; this.tacticsSig = ""; this.bannerSig = ""; this.endShown = false;
    $("#feed").innerHTML = "";
  },
};

async function poll(immediate = false) {
  clearTimeout(F.timer);
  try {
    const st = await api.get(`/api/state?since=${F.next}`);
    if (st.mode === "none") {
      $("#live-link").classList.add("hidden");
      if (current === "fight") show("home");
      return;
    }
    if (F.id !== null && st.id !== F.id) { F.reset(); return poll(); }
    F.id = st.id;
    F.next = st.next;
    F.state = st;
    $("#live-link").classList.toggle("hidden", st.finished || current === "fight");
    if (current === "fight") renderFight(st);
  } catch (err) {
    console.error(err);
  }
  if (current === "fight") F.timer = setTimeout(poll, 250);
}

function bar(label, v, max, color, cap) {
  const w = Math.max(0, Math.min(100, v));
  const capMark = cap !== undefined && cap < 100 ? `<b style="left:${cap}%"></b>` : "";
  return `<div class="bar-label">${label}</div>
    <div class="bar"><i style="width:${w}%;background:${color}"></i>${capMark}</div>
    <div class="bar-val">${Math.round(v)}</div>`;
}
const healthColor = (v) => (v > 70 ? "#3fbf7f" : v > 40 ? "#e7b73c" : "#e0262b");

function renderFighterCard(f, idx, st) {
  const coached = st.coached === idx;
  const badges = [];
  if (f.rocked >= 2) badges.push(`<span class="badge hurt">Machucado</span>`);
  else if (f.rocked === 1) badges.push(`<span class="badge hurt">Sentiu</span>`);
  if (f.cut > 30) badges.push(`<span class="badge cut">Corte</span>`);
  const chips = f.intent.map((t, i) => `<span class="chip ${i === 0 ? "lead" : ""}">${esc(t)}</span>`).join("");
  const el = $("#sb-" + idx);
  el.classList.toggle("coached", coached);
  el.innerHTML = `
    <div class="sb-name">${esc(f.full)}</div>
    <div class="sb-meta">"${esc(f.nickname)}" · ${esc(f.record)} · ${f.stance === "orthodox" ? "ortodoxo" : "canhoto"}</div>
    <div class="bars">
      ${bar("Gás", f.stamina, 100, "#5aa6ff", f.max_stamina)}
      ${bar("Cabeça", f.head, 100, healthColor(f.head))}
      ${bar("Corpo", f.body, 100, healthColor(f.body))}
      ${bar("Pernas", f.legs, 100, healthColor(f.legs))}
    </div>
    <div class="badges">${badges.join("")}</div>
    <div class="intent">${chips}</div>`;
}

function renderFight(st) {
  // placar
  st.fighters.forEach((f, i) => renderFighterCard(f, i, st));
  const status = $("#sb-status");
  let label = "AO VIVO", cls = "live";
  if (st.mode === "pre") { label = "PRÉ-LUTA"; cls = ""; }
  else if (st.finished) { label = "FIM"; cls = "end"; }
  else if (st.intermission) { label = "INTERVALO"; cls = "inter"; }
  else if (st.paused) { label = "PAUSADO"; cls = ""; }
  status.textContent = label;
  status.className = "sb-status " + cls;
  $("#sb-round").textContent = `ROUND ${st.round} / ${st.rounds}`;
  $("#sb-clock").textContent = st.clock;
  $("#sb-progress-bar").style.width = `${(st.clock_s / st.round_len) * 100}%`;
  $("#sb-position").textContent = st.position;

  // controles
  const pb = $("#btn-pause");
  pb.textContent = st.paused ? "▶" : "❚❚";
  pb.classList.toggle("paused", st.paused);
  $("#speeds").innerHTML = st.speeds.map((s) => `<button data-speed="${s}" class="${s === st.speed ? "on" : ""}">${s}×</button>`).join("");

  appendEvents(st.events);
  renderBanner(st);
  renderTactics(st);
  if (F.tab === "stats") renderStats(st);
  if (F.tab === "rounds") renderRounds(st);
  if (st.finished && !F.endShown) { F.endShown = true; setTimeout(() => showResult(st), 900); }
}

function appendEvents(events) {
  if (!events.length) return;
  const feed = $("#feed");
  const box = $("#tab-feed");
  const atBottom = box.scrollHeight - box.scrollTop - box.clientHeight < 60;
  const frag = document.createDocumentFragment();
  for (const ev of events) {
    const d = document.createElement("div");
    d.className = `ev new ${ev.kind} ${ev.side === 0 ? "s0" : ev.side === 1 ? "s1" : ""}`;
    d.innerHTML = `<span class="t">R${ev.rnd} ${ev.t}</span><span class="x">${esc(ev.text)}</span>`;
    frag.appendChild(d);
  }
  feed.appendChild(frag);
  while (feed.children.length > 600) feed.removeChild(feed.firstChild);
  if (atBottom) box.scrollTop = box.scrollHeight;
  else $("#jump").classList.remove("hidden");
}

$("#tab-feed").addEventListener("scroll", (e) => {
  const b = e.target;
  if (b.scrollHeight - b.scrollTop - b.clientHeight < 60) $("#jump").classList.add("hidden");
});
$("#jump").addEventListener("click", () => { const b = $("#tab-feed"); b.scrollTop = b.scrollHeight; $("#jump").classList.add("hidden"); });

$("#feed-tabs").addEventListener("click", async (e) => {
  const tab = e.target.closest("button[data-tab]");
  if (tab) {
    F.tab = tab.dataset.tab;
    $$("#feed-tabs > button").forEach((b) => b.classList.toggle("on", b === tab));
    ["feed", "stats", "rounds"].forEach((t) => $("#tab-" + t).classList.toggle("hidden", t !== F.tab));
    if (F.state) { if (F.tab === "stats") renderStats(F.state); if (F.tab === "rounds") renderRounds(F.state); }
  }
  const sp = e.target.closest("[data-speed]");
  if (sp) { await api.post("/api/fight/speed", { speed: +sp.dataset.speed }); poll(); }
});

async function togglePause() {
  if (!F.state || F.state.mode !== "live") return;
  await api.post("/api/fight/pause", { paused: !F.state.paused });
  poll();
}
$("#btn-pause").addEventListener("click", togglePause);

function renderStats(st) {
  const [a, b] = st.fighters;
  $("#tab-stats").innerHTML = `<table class="stats"><tr><th></th><th>${esc(a.name)}</th><th>${esc(b.name)}</th></tr>
    ${st.stats.map(([l, x, y]) => `<tr><td>${esc(l.trim())}</td><td>${esc(x)}</td><td>${esc(y)}</td></tr>`).join("")}</table>`;
}

function renderRounds(st) {
  const [a, b] = st.fighters;
  $("#tab-rounds").innerHTML = `<table class="stats"><tr><th>Round</th><th>${esc(a.name)}</th><th>${esc(b.name)}</th></tr>
    ${st.by_round.map((r, i) => `<tr><td>R${i + 1}</td>
      <td>${r.a[0]}/${r.a[1]} sig.${r.a[2] ? ` · ${r.a[2]} quedas` : ""}${r.a[3] ? ` · ${r.a[3]} KD` : ""}</td>
      <td>${r.b[0]}/${r.b[1]} sig.${r.b[2] ? ` · ${r.b[2]} quedas` : ""}${r.b[3] ? ` · ${r.b[3]} KD` : ""}</td></tr>`).join("")}</table>`;
}

// ---- faixa de pré-luta / intervalo
function renderBanner(st) {
  const el = $("#banner");
  let sig = "";
  if (st.mode === "pre") sig = "pre";
  else if (st.intermission && !st.finished) sig = `inter-${st.round}-${st.corner_done}`;
  if (!sig) { el.classList.add("hidden"); F.bannerSig = ""; return; }
  if (sig !== F.bannerSig) {
    F.bannerSig = sig;
    el.classList.remove("hidden");
    requestAnimationFrame(() => { const b = $("#tab-feed"); b.scrollTop = b.scrollHeight; });
    if (sig === "pre") {
      const me = st.coached;
      const opp = me === null ? null : st.fighters[1 - me];
      el.className = "banner pre";
      el.innerHTML = me === null ? "" : `
        <h4>Pré-luta</h4>
        <div class="muted">Monte a estratégia inicial no painel ao lado (as instruções valem na hora).
        Natureza de ${esc(opp.name)}: <b>${esc(opp.intent.join(" · "))}</b>.</div>
        <div class="row"><button class="btn btn-primary" id="btn-go">Começar a luta</button>
        <span class="muted">Depois o relógio corre sem parar — use <b>Espaço</b> para pausar.</span></div>`;
    } else {
      const coached = st.coached !== null;
      const r = st.by_round[st.round - 1];
      const [a, b] = st.fighters;
      el.className = "banner inter";
      el.innerHTML = `
        <h4>Intervalo — fim do round ${st.round}</h4>
        <div class="round-line">${esc(a.name)}: ${r.a[0]}/${r.a[1]} golpes sig.${r.a[2] ? `, ${r.a[2]} quedas` : ""}${r.a[3] ? `, ${r.a[3]} KD` : ""}</div>
        <div class="round-line">${esc(b.name)}: ${r.b[0]}/${r.b[1]} golpes sig.${r.b[2] ? `, ${r.b[2]} quedas` : ""}${r.b[3] ? `, ${r.b[3]} KD` : ""}</div>
        ${coached ? `<div class="corner-actions">${META.corner.map((c) =>
          `<button class="btn" data-corner="${c.id}" ${st.corner_done ? "disabled" : ""}>${esc(c.label)}</button>`).join("")}</div>` : ""}
        <div class="row">
          <button class="btn btn-primary" id="btn-next">Começar o round ${st.round + 1}</button>
          ${coached ? `<button class="btn btn-ghost" id="btn-towel">Jogar a toalha</button>` : ""}
          <span class="count" id="inter-count"></span>
        </div>`;
    }
  }
  const c = $("#inter-count");
  if (c && st.inter_left !== null) c.textContent = `${Math.floor(st.inter_left / 60)}:${String(st.inter_left % 60).padStart(2, "0")}`;
}

$("#banner").addEventListener("click", async (e) => {
  if (e.target.id === "btn-go") { await api.post("/api/fight/start"); poll(); }
  if (e.target.id === "btn-next") { await api.post("/api/fight/next_round"); poll(); }
  if (e.target.id === "btn-towel") {
    if (confirm("Jogar a toalha e encerrar a luta?")) { await api.post("/api/fight/towel"); poll(); }
  }
  const c = e.target.closest("[data-corner]");
  if (c) { await api.post("/api/fight/corner", { id: c.dataset.corner }); toast("Ação do córner feita"); poll(); }
});

// ---- painel de táticas
function renderTactics(st) {
  const el = $("#tactics");
  const sig = JSON.stringify([st.coached, st.fighters.map((f) => [f.plan, f.intent]), st.active, F.cat, st.finished]);
  if (sig === F.tacticsSig) return;
  F.tacticsSig = sig;
  const scrollTop = $(".tp-scroll", el)?.scrollTop || 0;
  if (st.coached === null) {
    el.innerHTML = `<div class="tp-head"><div class="tp-title">Modo espectador</div>
      <div class="tp-sub">Os dois córneres são da IA. Os lutadores seguem a própria natureza e os ajustes do córner.</div></div>
      <div class="tp-scroll">${st.fighters.map((f) => `<div class="watch-block"><h5>${esc(f.full)}</h5>
        <div class="intent">${f.intent.map((t) => `<span class="chip">${esc(t)}</span>`).join("")}</div></div>`).join("")}</div>`;
    return;
  }
  const me = st.fighters[st.coached];
  const active = new Set(st.active || []);
  const cat = META.categories[F.cat];
  const over = me.instructions > me.capacity;
  el.innerHTML = `
    <div class="tp-head">
      <div class="tp-title"><span style="color:${st.coached === 0 ? "var(--red-soft)" : "var(--blue-soft)"}">●</span> Córner de ${esc(me.name)}</div>
      <div class="tp-sub">Clique para gritar a instrução. Ela chega em 1–3 s (se ele não estiver machucado).</div>
    </div>
    <div class="tp-scroll">
      <div class="section-label">Gritos rápidos</div>
      <div class="shouts">${META.shouts.map((s) => `<button class="shout" data-cmd="${s.id}" title="${esc(s.label)}">${esc(s.shout)}</button>`).join("")}</div>

      <div class="section-label">Instruções</div>
      <div class="cat-tabs">${META.categories.map((c, i) => `<button data-cat="${i}" class="${i === F.cat ? "on" : ""}">${esc(c.label)}</button>`).join("")}</div>
      <div class="cmds">${cat.commands.map((c) => `<button class="cmd ${active.has(c.id) ? "active" : ""}" data-cmd="${c.id}" title="${esc(c.shout)}">
        <span>${esc(c.label)}</span><span class="lvl">${"●".repeat(c.level)}</span></button>`).join("")}</div>

      <div class="section-label"><span>Plano atual</span><span style="color:${over ? "var(--red-soft)" : "var(--muted)"}">${me.instructions}/${me.capacity} instruções</span></div>
      <div class="capacity ${over ? "over" : ""}"><i style="width:${Math.min(100, (me.instructions / me.capacity) * 100)}%"></i></div>
      ${over ? `<div class="warn" style="font-size:12px;margin-bottom:8px">Instruções demais: ${esc(me.name)} executa pior. Remova algumas.</div>` : ""}
      <div class="plan-list">${me.plan.length ? me.plan.map((p) => `<div class="plan-item"><span>${esc(p.text)}</span>
        <button data-clear="${esc(p.slot)}" title="Remover">×</button></div>`).join("")
        : `<div class="empty">Sem instruções: ${esc(me.name)} luta pela própria natureza.</div>`}</div>
      <div class="muted" style="font-size:12px;margin-top:12px">● genérico &nbsp; ●● direcionado &nbsp; ●●● técnico (maior bônus)</div>
    </div>`;
  const sc = $(".tp-scroll", el);
  if (sc) sc.scrollTop = scrollTop;
}

$("#tactics").addEventListener("click", async (e) => {
  const c = e.target.closest("[data-cat]");
  if (c) { F.cat = +c.dataset.cat; F.tacticsSig = ""; renderTactics(F.state); return; }
  const cmd = e.target.closest("[data-cmd]");
  if (cmd) {
    const r = await api.post("/api/fight/command", { id: cmd.dataset.cmd });
    if (r.error) toast(r.error); else toast("Instrução gritada");
    poll();
    return;
  }
  const cl = e.target.closest("[data-clear]");
  if (cl) { await api.post("/api/fight/clear", { slot: cl.dataset.clear }); poll(); }
});

// ---- resultado
function showResult(st) {
  const r = st.result;
  if (!r) return;
  const [a, b] = st.fighters;
  const winName = r.winner === null ? "Empate" : st.fighters[r.winner].full;
  const mine = st.coached !== null && r.winner === st.coached;
  const title = st.coached === null ? "Fim de luta" : r.winner === null ? "Empate" : mine ? "Vitória!" : "Derrota";
  modal(`
    <h2>${title}</h2>
    <div class="result-winner">${esc(r.summary)}</div>
    ${r.cards.length ? `<div class="cards-list">${r.cards.map((c) => `<div>${esc(c)}</div>`).join("")}</div>` : ""}
    <table class="stats"><tr><th></th><th>${esc(a.name)}</th><th>${esc(b.name)}</th></tr>
      ${st.stats.map(([l, x, y]) => `<tr><td>${esc(l.trim())}</td><td>${esc(x)}</td><td>${esc(y)}</td></tr>`).join("")}</table>
    <div class="modal-actions">
      <button class="btn" id="m-close">Ver narração</button>
      ${st.career ? `<button class="btn btn-primary" id="m-career">Concluir e voltar à carreira</button>`
                  : `<button class="btn" id="m-menu">Menu</button><button class="btn btn-primary" id="m-rematch">Revanche</button>`}
    </div>`);
  void winName;
}

$("#modal").addEventListener("click", async (e) => {
  const id = e.target.id;
  if (id === "modal" || id === "m-close") closeModal();
  if (id === "m-menu") { closeModal(); show("home"); }
  if (id === "m-rematch") { closeModal(); startQuick(); }
  if (id === "m-career") {
    const r = await api.post("/api/career/complete");
    modal(`<h2>Pós-luta</h2><div class="cards-list">${(r.messages || [r.error]).map((m) => `<div>${esc(m)}</div>`).join("")}</div>
      <div class="modal-actions"><button class="btn btn-primary" id="m-hub">Voltar à carreira</button></div>`);
  }
  if (id === "m-hub") { closeModal(); await api.post("/api/fight/abandon"); F.reset(); show("career"); }
  if (id === "m-go-fight") { closeModal(); F.reset(); show("fight"); }
});

// ------------------------------------------------------------------ lutadores
function renderRoster() {
  $("#roster-grid").innerHTML = ROSTER.map((f) => `
    <button class="fcard" data-profile="${f.id}">
      <div class="nick">"${esc(f.nickname)}"</div>
      <div class="nm">${esc(f.name)}</div>
      <div class="rec">${esc(f.record_str)}</div>
      <div class="muted">${esc(f.division)} · ${f.age} anos · Geral ${f.overall}</div>
    </button>`).join("");
}

document.addEventListener("click", (e) => {
  const p = e.target.closest("[data-profile]");
  if (p) { renderProfile(ROSTER.find((f) => f.id === p.dataset.profile)); show("profile");
    history.replaceState(null, "", "#profile-" + p.dataset.profile); }
});

function renderProfile(f, back = "fighters") {
  const u = f.ufc_stats;
  const rec = f.record;
  const attrs = Object.entries(META.attr_groups).map(([g, keys]) => `
    <div class="attr-group">${esc(g)}</div>
    ${keys.map((k) => `<div class="attr"><span>${esc(META.attr_labels[k])}</span>
      <div class="bar"><i style="width:${f.attributes[k]}%;background:${healthColor(f.attributes[k] - 5)}"></i></div>
      <span class="bar-val">${f.attributes[k]}</span></div>`).join("")}`).join("");
  $("#profile").innerHTML = `
    <a href="#" data-nav="${back}" class="muted">← voltar</a>
    <div class="profile-head">
      <div><div class="hero-eyebrow">"${esc(f.nickname)}"</div><h2>${esc(f.name)}</h2>
        <div class="muted">${esc(f.nationality)} · ${esc(f.hometown)} · ${esc(f.team)}</div></div>
      <div style="text-align:right"><div class="rec">${esc(f.record_str)}</div>
        <div class="muted">${rec.wins_by.ko} KO/TKO · ${rec.wins_by.sub} fin. · ${rec.wins_by.dec} dec.</div></div>
    </div>
    <div class="facts">
      ${[["Idade", f.age + " anos"], ["Altura", `${f.height_cm} cm (${ft(f.height_cm)})`], ["Envergadura", `${f.reach_cm} cm`],
         ["Peso", `${f.weight_lbs} lb`], ["Divisão", f.division], ["Base", f.stance === "orthodox" ? "Ortodoxa" : "Canhota"],
         ["Estilo", f.base_style], ["Geral", f.overall]]
        .map(([k, v]) => `<div class="fact"><div class="k">${k}</div><div class="v">${esc(v)}</div></div>`).join("")}
    </div>
    <div class="two-col">
      <div>
        <div class="box"><h3>Estatísticas oficiais UFC</h3>
          <table class="stats plain">
            <tr><td>Golpes sig. por minuto</td><td>${u.slpm}</td><td></td></tr>
            <tr><td>Precisão</td><td>${Math.round(u.str_acc * 100)}%</td><td></td></tr>
            <tr><td>Absorvidos por minuto</td><td>${u.sapm}</td><td></td></tr>
            <tr><td>Defesa de golpes</td><td>${Math.round(u.str_def * 100)}%</td><td></td></tr>
            <tr><td>Quedas</td><td>${u.td_landed}/${u.td_attempted} (${Math.round(u.td_acc * 100)}%)</td><td></td></tr>
            <tr><td>Defesa de quedas</td><td>${Math.round(u.td_def * 100)}%</td><td></td></tr>
            <tr><td>Finalizações / 15 min</td><td>${u.sub_avg}</td><td></td></tr>
            <tr><td>Knockdowns / 15 min</td><td>${u.kd_avg}</td><td></td></tr>
            <tr><td>Tempo médio de luta</td><td>${u.avg_fight_time}</td><td></td></tr>
          </table></div>
        <div class="box"><h3>Vícios</h3><div class="muted">Só descobertos estudando o adversário no camp ou lendo a luta (◆ Leitura).</div></div>
      </div>
      <div class="box"><h3>Atributos do jogo</h3>${attrs}</div>
    </div>
    <div class="box"><h3>Cartel</h3><table class="hist">
      <tr><th></th><th>Data</th><th>Adversário</th><th>Método</th><th>R</th><th>Tempo</th><th>Evento</th></tr>
      ${f.fight_history.map((h) => `<tr><td><span class="res ${h.result}">${{ W: "V", L: "D", D: "E" }[h.result]}</span></td>
        <td>${esc(h.date)}</td><td>${esc(h.opponent)}</td><td>${esc(h.method)}</td><td>${h.round}</td><td>${esc(h.time)}</td><td>${esc(h.event)}</td></tr>`).join("")}
    </table></div>`;
}

// ------------------------------------------------------------------ carreira
let CAREER = null;

async function renderCareer() {
  CAREER = await api.get("/api/career");
  const el = $("#career");
  if (!CAREER.exists) {
    el.innerHTML = `<h2 class="page-title">Nova carreira</h2>
      <p class="muted">Escolha o lutador que você vai treinar. Você monta os camps, escolhe as lutas e comanda o córner.</p>
      <div class="roster-grid">${ROSTER.map((f) => `<button class="fcard" data-newcareer="${f.id}">
        <div class="nick">"${esc(f.nickname)}"</div><div class="nm">${esc(f.name)}</div>
        <div class="rec">${esc(f.record_str)}</div><div class="muted">${f.age} anos · Geral ${f.overall}</div></button>`).join("")}</div>`;
    return;
  }
  const c = CAREER;
  const f = c.fighter;
  el.innerHTML = `
    <div class="profile-head">
      <div><div class="hero-eyebrow">Carreira · ${esc(c.date)}</div><h2>${esc(f.name)}</h2>
        <div class="muted">${f.age} anos · ${esc(f.division)} · <a href="#" id="c-profile" style="text-decoration:underline">ver perfil</a></div></div>
      <div style="text-align:right"><div class="rec">${esc(f.record_str)}</div></div>
    </div>
    <div class="kpis">
      <div class="fact"><div class="k">Dinheiro</div><div class="v">${money(c.money)}</div></div>
      <div class="fact"><div class="k">Popularidade</div><div class="v">${c.popularity}/100</div></div>
      <div class="fact"><div class="k">Lutas na carreira</div><div class="v">${c.fights.length}</div></div>
      <div class="fact"><div class="k">Geral</div><div class="v">${f.overall}</div></div>
    </div>
    <div class="career-top">
      <div class="box"><h3>Próxima luta</h3>
        ${c.suspended ? `<p class="warn">${esc(c.suspended)}</p>` : ""}
        <div class="form-row"><label class="opt-label">Adversário</label>
          <select id="c-opp">${c.opponents.map((o) => `<option value="${o.id}">${esc(o.name)} (${esc(o.record)}) · Geral ${o.overall}</option>`).join("")}</select></div>
        <div class="form-row"><label class="opt-label">Formato</label>
          <div class="seg" id="c-rounds"><button data-v="3" class="on">3 rounds</button><button data-v="5">5 rounds (luta principal)</button></div></div>
        <div class="form-row"><label class="opt-label">Camp de treinamento (8 semanas)</label>
          <div class="camp-opts">${META.camps.map((k, i) => `<label><input type="radio" name="camp" value="${k.id}" ${i === 4 ? "checked" : ""}> ${esc(k.label)}</label>`).join("")}</div></div>
        <button class="btn btn-primary btn-lg" id="c-fight">${c.suspended ? "Aguardar liberação e lutar" : "Assinar e ir para o camp"}</button>
      </div>
      <div class="box"><h3>Histórico na carreira</h3>
        ${c.fights.length ? `<table class="hist"><tr><th></th><th>Data</th><th>Adversário</th><th>Método</th><th>R</th></tr>
          ${c.fights.map((h) => `<tr><td><span class="res ${h.result}">${{ W: "V", L: "D", D: "E" }[h.result]}</span></td><td>${esc(h.date)}</td>
          <td>${esc(h.opponent)}</td><td>${esc(h.method)}</td><td>${h.round} · ${esc(h.time)}</td></tr>`).join("")}</table>`
          : `<div class="empty">Nenhuma luta ainda.</div>`}
        <div style="margin-top:16px"><button class="btn btn-ghost" id="c-reset">Recomeçar carreira</button></div>
      </div>
    </div>`;
}

$("#career").addEventListener("click", async (e) => {
  const n = e.target.closest("[data-newcareer]");
  if (n) { await api.post("/api/career/new", { fighter: n.dataset.newcareer }); renderCareer(); return; }
  if (e.target.id === "c-profile") { e.preventDefault(); renderProfile(CAREER.fighter, "career"); show("profile"); return; }
  const seg = e.target.closest(".seg button");
  if (seg) $$("button", seg.parentElement).forEach((b) => b.classList.toggle("on", b === seg));
  if (e.target.id === "c-reset") {
    if (confirm("Apagar a carreira atual e começar outra?")) {
      CAREER.exists = false;
      $("#career").innerHTML = "";
      await api.post("/api/career/new", { fighter: CAREER.fighter.id });
      renderCareer();
    }
  }
  if (e.target.id === "c-fight") {
    const body = {
      opponent: $("#c-opp").value,
      rounds: +$("#c-rounds .on").dataset.v,
      camp: $("input[name=camp]:checked").value,
      wait: !!CAREER.suspended,
    };
    const r = await api.post("/api/career/fight", body);
    if (r.error) return toast(r.error);
    F.reset();
    if (r.scouted && r.scouted.length) {
      modal(`<h2>Relatório do estudo</h2><p class="muted">O que a equipe descobriu sobre o adversário:</p>
        <div class="cards-list">${r.scouted.map((s) => `<div class="hint-dot" style="margin:6px 0">◆ ${esc(s)}</div>`).join("")}</div>
        <p class="muted">Use os contra-ataques para punir esses vícios. Com o estudo, o plano entra 100% claro no round 1.</p>
        <div class="modal-actions"><button class="btn btn-primary" id="m-go-fight">Ir para o octógono</button></div>`);
    } else {
      show("fight");
    }
  }
});

// ------------------------------------------------------------------ validação
function renderLab() {
  const opts = ROSTER.map((f) => `<option value="${f.id}">${esc(f.name)}</option>`).join("");
  if (!$("#lab-red").options.length) {
    $("#lab-red").innerHTML = opts;
    $("#lab-blue").innerHTML = opts;
    if (ROSTER[1]) $("#lab-blue").value = ROSTER[1].id;
  }
}
$("#btn-lab").addEventListener("click", async () => {
  const red = $("#lab-red").value, blue = $("#lab-blue").value;
  if (red === blue) return toast("Escolha dois lutadores diferentes");
  $("#lab-out").textContent = "Simulando...";
  const r = await api.get(`/api/batch?red=${red}&blue=${blue}&n=${$("#lab-n").value}&rounds=${$("#lab-rounds").value}`);
  $("#lab-out").textContent = r.report || r.error;
});

// ------------------------------------------------------------------ início
(async function init() {
  META = await api.get("/api/meta");
  ROSTER = (await api.get("/api/roster")).fighters;
  const st = await api.get("/api/state?since=0");
  const live = st.mode && st.mode !== "none";
  if (live && !st.finished) $("#live-link").classList.remove("hidden");
  const want = location.hash.slice(1);
  const prof = ROSTER.find((f) => "profile-" + f.id === want);
  if (prof) { renderProfile(prof); show("profile"); }
  else if (want === "fight" && !live) show("home");
  else if (["home", "quick", "career", "fighters", "lab", "fight"].includes(want)) show(want);
  else show("home");
})();
