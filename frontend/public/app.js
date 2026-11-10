/* ==========================================================================
   Suivi des congés — SPA vanilla (login, fiches agents, dashboard,
   paramétrage, utilisateurs).
   ========================================================================== */
"use strict";

/* ---------------------------- état global ---------------------------- */
const state = {
  user: null,
  settings: null,
  agents: [],
  fiche: null,        // fiche en cours d'édition
  compute: null,      // dernier résultat de calcul
  saveTimer: null,
  computeTimer: null,
  tabs: [],           // fiches ouvertes [{id, nom}]
  activeTab: null,    // id de la fiche active
  planningMonth: null,   // mois affiché dans le planning (1..12)
  planningFilter: null,  // admin : "all" | "me" | id utilisateur
  dashboardAll: null,    // admin : afficher toutes les fiches par défaut
  year: null,            // année de travail sélectionnée
};

const TABS_KEY = "suivi_tabs";
const YEAR_KEY = "suivi_year";

const ROLE_LABELS = {
  administrateur: "Administrateur",
  dgs: "Valideur DGS",
  dga: "Valideur DGA",
  direction: "Valideur Direction",
  service: "Valideur Service",
  secteur: "Valideur Secteur",
  unite: "Valideur Unité",
  equipe: "Valideur Équipe",
  agent: "Agent",
};
const VALIDATOR_ROLES = ["administrateur", "dgs", "dga", "direction", "service", "secteur", "unite", "equipe"];

function userRole(u) {
  return (u && u.role) || (u && u.admin ? "administrateur" : "secteur");
}

function agentName(a) {
  return [a && a.nom, a && a.prenom].filter(Boolean).join(" ").trim();
}

function canEditFiche(f) {
  if (!f) return false;
  if (typeof f.can_edit === "boolean") return f.can_edit;
  return !!state.user && (f.user_id === state.user.id || !!state.user.admin);
}

const ROLE_ORDER = {
  administrateur: 0, dgs: 1, dga: 2, direction: 3, service: 4,
  secteur: 5, unite: 6, equipe: 7, agent: 8,
};

function byRoleName(a, b) {
  return (ROLE_ORDER[userRole(a)] - ROLE_ORDER[userRole(b)]) ||
    String(a.nom || a.login).localeCompare(String(b.nom || b.login));
}

/* Ordre des sous-niveaux : un secteur rattaché directement à une direction
   passe avant les services de cette direction. */
function sortHierarchyChildren(parent, children) {
  const parentRole = userRole(parent);
  const rank = (u) => {
    const role = userRole(u);
    if (parentRole === "direction") {
      if (role === "secteur") return 0;
      if (role === "service") return 1;
      return 2;
    }
    if (parentRole === "service") {
      return role === "secteur" ? 0 : 1;
    }
    return ROLE_ORDER[role] == null ? 9 : ROLE_ORDER[role];
  };
  return children.slice().sort((a, b) => (rank(a) - rank(b)) || byRoleName(a, b));
}

function canViewTeam() {
  return !!state.user && (state.user.admin || VALIDATOR_ROLES.includes(userRole(state.user)));
}

function canValidateRequests() {
  return !!state.user && (state.user.admin || VALIDATOR_ROLES.includes(userRole(state.user)));
}

function canCreateFiche() {
  return !!state.user && (state.user.admin || VALIDATOR_ROLES.includes(userRole(state.user)));
}

function canManageUsers() {
  return canCreateFiche();
}

function canViewPlanningTeam() {
  return !!state.user && (canViewTeam() || userRole(state.user) === "agent");
}

async function refreshRequestBadge() {
  if (!state.user) return;
  try {
    const counts = await api("/api/requests/counts");
    const n = canValidateRequests()
      ? (counts.to_validate || counts.mine_pending)
      : counts.mine_pending;
    const el = $("#req-badge");
    if (el) {
      el.textContent = n ? String(n) : "";
      el.classList.toggle("hidden", !n);
    }
    const reminders = await api("/api/reminders?days=3").catch(() => null);
    const banner = $("#reminder-banner");
    if (banner) {
      if (reminders && reminders.count) {
        const label = canValidateRequests()
          ? `${reminders.count} demande(s) en attente depuis plus de 3 jours`
          : `${reminders.count} de vos demandes sont en attente depuis plus de 3 jours`;
        banner.innerHTML = `<b>Relance automatique :</b> ${esc(label)}. <a href="#/requests">Voir les demandes</a>`;
        banner.classList.remove("hidden");
      } else {
        banner.classList.add("hidden");
        banner.innerHTML = "";
      }
    }
  } catch (_) { /* badge et relance non bloquants */ }
}

/* ---------------------------- année de travail ---------------------------- */
function defaultYear() {
  return new Date().getFullYear();
}

function renderYearSelect() {
  const sel = $("#year-select");
  if (!sel) return;
  const base = defaultYear();
  const current = state.year || base;
  const min = Math.min(base, current) - 1;
  const max = Math.max(base, current) + 1;
  const years = [];
  for (let y = min; y <= max; y++) years.push(y);
  sel.innerHTML = years.map((y) =>
    `<option value="${y}" ${y === current ? "selected" : ""}>${y}</option>`).join("");
}

function initYear(forceCurrent = false) {
  const raw = localStorage.getItem(YEAR_KEY);
  const stored = raw ? parseInt(raw, 10) : null;
  const base = defaultYear();
  state.year = forceCurrent
    ? base
    : ((stored && stored >= 2000 && stored <= 2100) ? stored : base);
  localStorage.setItem(YEAR_KEY, String(state.year));
  renderYearSelect();
}

function setYear(y, targetHash = "#/dashboard") {
  if (!y) return;
  const changed = y !== state.year;
  state.year = y;
  localStorage.setItem(YEAR_KEY, String(y));
  renderYearSelect();
  if (changed) {
    if (location.hash !== targetHash) location.hash = targetHash;
    else route();
  } else {
    route();
  }
}

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => Array.from(document.querySelectorAll(sel));

/* ---------------------------- utilitaires ---------------------------- */
function api(path, opts = {}) {
  const headers = { "Content-Type": "application/json", ...(opts.headers || {}) };
  return fetch(path, { ...opts, headers }).then(async (r) => {
    let data = null;
    try { data = await r.json(); } catch (_) { /* vide */ }
    if (r.status === 401 && path !== "/api/auth/login") {
      logoutLocal();
      throw new Error("Session expirée");
    }
    if (!r.ok) {
      const msg = (data && (data.error || (data.errors || []).join(" — "))) || ("Erreur " + r.status);
      throw new Error(msg);
    }
    return data;
  });
}

function toast(msg, isErr = false) {
  const el = $("#toast");
  el.textContent = msg;
  el.className = "toast" + (isErr ? " err" : "");
  clearTimeout(el._t);
  el._t = setTimeout(() => el.classList.add("hidden"), 3200);
}

function esc(s) {
  return String(s == null ? "" : s).replace(/[&<>"']/g, (c) => (
    { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]
  ));
}

function fmt(v) {
  if (v == null || v === "") return "—";
  const n = Number(v);
  if (Number.isNaN(n)) return String(v);
  return (Math.round(n * 100) / 100).toString().replace(".", ",");
}

function rchExpiryAlert(calc) {
  const restant = Number((calc && calc.rch_restant) || 0);
  const expiry = calc && calc.rch_next_expiry;
  if (restant <= 0 || !expiry) return "";
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const target = new Date(`${String(expiry).slice(0, 10)}T00:00:00`);
  const days = Math.ceil((target - today) / 86400000);
  if (!Number.isFinite(days) || days < 0 || days > 30) return "";
  const when = days === 0 ? "aujourd'hui" : `dans ${days} jour${days > 1 ? "s" : ""}`;
  return `<div class="rch-alert"><b>Heures de récupération :</b> ${fmtHours(restant)} expirent le ${frDate(expiry)} (${when}). Pensez à les utiliser.</div>`;
}

function fmtHours(v) {
  if (v == null || v === "") return "0 h";
  const n = Number(v);
  if (Number.isNaN(n)) return String(v);
  const totalMinutes = Math.round(n * 60);
  const h = Math.floor(totalMinutes / 60);
  const m = totalMinutes % 60;
  if (!m) return `${h} h`;
  return `${h} h ${String(m).padStart(2, "0")}`;
}

function fmtDaysHours(v) {
  if (v == null || v === "") return "—";
  const n = Number(v);
  if (Number.isNaN(n)) return String(v);
  const sign = n < 0 ? "-" : "";
  const totalMinutes = Math.round(Math.abs(n) * 7 * 60);
  const d = Math.floor(totalMinutes / (7 * 60));
  const rem = totalMinutes % (7 * 60);
  const h = Math.floor(rem / 60);
  const m = rem % 60;
  let out = `${sign}${d} j`;
  if (h) out += ` ${h} h`;
  if (m) out += ` ${String(m).padStart(2, "0")}`;
  return out;
}

function cssColor(hex) {
  // "FFFF00" ou "FFF2F2F2" -> "#ffff00"
  if (!hex) return "#ffffff";
  let h = String(hex).replace("#", "").toUpperCase();
  if (h.length === 8) h = h.slice(2);          // ignore le canal alpha
  return "#" + h.toLowerCase();
}

function textColorFor(hex) {
  const h = cssColor(hex).slice(1);
  const r = parseInt(h.slice(0, 2), 16), g = parseInt(h.slice(2, 4), 16), b = parseInt(h.slice(4, 6), 16);
  return (r * 299 + g * 587 + b * 114) / 1000 > 150 ? "#333" : "#fff";
}

/* Mélange une couleur avec du blanc (ratio = part de la couleur d'origine). */
function mixColor(hex, ratio) {
  const h = cssColor(hex).slice(1);
  const r = parseInt(h.slice(0, 2), 16), g = parseInt(h.slice(2, 4), 16), b = parseInt(h.slice(4, 6), 16);
  const m = (v) => Math.round(v * ratio + 255 * (1 - ratio));
  return `rgb(${m(r)}, ${m(g)}, ${m(b)})`;
}

/* Assombrit une couleur (ratio = part de noir). */
function shadeColor(hex, ratio) {
  const h = cssColor(hex).slice(1);
  const r = parseInt(h.slice(0, 2), 16), g = parseInt(h.slice(2, 4), 16), b = parseInt(h.slice(4, 6), 16);
  const m = (v) => Math.round(v * (1 - ratio));
  return `rgb(${m(r)}, ${m(g)}, ${m(b)})`;
}

const MONTHS = ["Janvier", "Février", "Mars", "Avril", "Mai", "Juin", "Juillet",
  "Août", "Septembre", "Octobre", "Novembre", "Décembre"];

function daysInMonth(m, year) { return new Date(year, m, 0).getDate(); }
function dayOfWeek(m, d, year) { return new Date(year, m - 1, d).getDay(); } // 0=dim

/* Libellé de la période de vacances scolaires contenant la date ISO, ou null. */
function vacancesLabel(iso) {
  const list = (state.settings && state.settings.vacances_scolaires) || [];
  for (const v of list) {
    if (v && v[0] && v[1] && iso >= v[0] && iso <= v[1]) return v[2] || "Vacances scolaires";
  }
  return null;
}

/* identifiant numérique d'une demi-journée : mois*1000 + jour*10 + h */
function cellKey(month, day, half) { return month * 1000 + day * 10 + half; }

/* ---------------------------- authentification ---------------------------- */
function saveSession(user) {
  state.user = user;
  localStorage.setItem("suivi_user", JSON.stringify(user));
}
function logoutLocal() {
  state.user = null;
  renderActAsBanner();
  localStorage.removeItem("suivi_user");
  localStorage.removeItem(TABS_KEY);
  state.tabs = [];
  state.activeTab = null;
  renderTabs();
  showLogin();
}

async function tryRestoreSession() {
  const raw = localStorage.getItem("suivi_user");
  if (!raw) return showLogin();
  try { state.user = JSON.parse(raw); } catch (_) { return showLogin(); }
  try {
    state.settings = await api("/api/settings");
    try {
      const me = await api("/api/me");
      state.user = me.user;
      saveSession(me.user);
    } catch (_) { /* conserve la session locale */ }
    initYear();
    loadTabs();
    showApp();
  } catch (_) { showLogin(); }
}

function showLogin() {
  $("#app").classList.add("hidden");
  $("#view-login").classList.remove("hidden");
  const err = $("#login-error");
  if (err) {
    err.textContent = "";
    err.classList.add("hidden");
  }
  const pass = $("#login-pass");
  if (pass) pass.value = "";
}
function showApp() {
  $("#view-login").classList.add("hidden");
  $("#app").classList.remove("hidden");
  $("#user-badge").textContent = state.user.nom || state.user.login;
  const isAdmin = !!state.user.admin;
  const isAgent = userRole(state.user) === "agent";
  const dashboardLabel = $("#nav-dashboard-label");
  if (dashboardLabel) dashboardLabel.textContent = isAgent ? "Ma synthèse" : "Tableau de bord";
  const requestsLabel = $("#nav-requests-label");
  if (requestsLabel) requestsLabel.textContent = isAgent ? "Mes demandes" : "Demandes";
  const agentsNav = document.querySelector('#main-nav a[data-nav="agents"]');
  if (agentsNav) agentsNav.textContent = isAgent ? "Ma fiche" : "Mes fiches";
  const hrNav = $("#nav-hr");
  if (hrNav) hrNav.classList.toggle("hidden", isAgent);
  if (isAgent) state.planningFilter = "all";
  $("#nav-settings").classList.toggle("hidden", !isAdmin);
  $("#nav-users").classList.toggle("hidden", !canManageUsers() || isAdmin);
  $("#btn-password").classList.toggle("hidden", !!state.user.password_by_ad);
  setupActAs();
  route();
  refreshRequestBadge();
}

$("#login-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const errEl = $("#login-error");
  errEl.classList.add("hidden");
  try {
    const data = await api("/api/auth/login", {
      method: "POST",
      body: JSON.stringify({ login: $("#login-user").value.trim(), password: $("#login-pass").value }),
    });
    saveSession(data.user);
    state.settings = await api("/api/settings");
    initYear(true);
    loadTabs();
    location.hash = "#/dashboard";
    showApp();
  } catch (err) {
    errEl.textContent = err.message;
    errEl.classList.remove("hidden");
  }
});

$("#btn-logout").addEventListener("click", () => {
  api("/api/auth/logout", { method: "POST" }).catch(() => {});
  logoutLocal();
});

function openPasswordModal() {
  const modal = $("#password-modal");
  if (!modal) return;
  $("#password-login").textContent = state.user
    ? (state.user.login || state.user.nom || "")
    : "";
  $("#password-current").value = "";
  $("#password-new").value = "";
  $("#password-confirm").value = "";
  const err = $("#password-error");
  err.textContent = "";
  err.classList.add("hidden");
  modal.classList.remove("hidden");
  $("#password-current").focus();
}

async function submitPasswordChange() {
  const err = $("#password-error");
  err.classList.add("hidden");
  const current = $("#password-current").value;
  const next = $("#password-new").value;
  const confirm = $("#password-confirm").value;
  if (!current || !next || !confirm) {
    err.textContent = "Tous les champs sont obligatoires.";
    err.classList.remove("hidden");
    return;
  }
  if (next !== confirm) {
    err.textContent = "Les deux nouveaux mots de passe ne correspondent pas.";
    err.classList.remove("hidden");
    return;
  }
  if (next.length < 8) {
    err.textContent = "Le nouveau mot de passe doit contenir au moins 8 caractères.";
    err.classList.remove("hidden");
    return;
  }
  try {
    await api("/api/me/password", {
      method: "POST",
      body: JSON.stringify({
        current_password: current,
        new_password: next,
        confirm_password: confirm,
      }),
    });
    $("#password-modal").classList.add("hidden");
    toast("Mot de passe modifié");
  } catch (e) {
    err.textContent = e.message;
    err.classList.remove("hidden");
  }
}

$("#btn-password").addEventListener("click", openPasswordModal);
$("#password-cancel").addEventListener("click", () => $("#password-modal").classList.add("hidden"));
$("#password-submit").addEventListener("click", submitPasswordChange);
$("#password-confirm").addEventListener("keydown", (e) => {
  if (e.key === "Enter") submitPasswordChange();
});
$("#password-modal").addEventListener("mousedown", (e) => {
  if (e.target.id === "password-modal") $("#password-modal").classList.add("hidden");
});

/* ---------------------------- onglets de fiches ---------------------------- */
function loadTabs() {
  try {
    const raw = localStorage.getItem(TABS_KEY);
    if (!raw) return;
    const data = JSON.parse(raw);
    if (Array.isArray(data.tabs)) state.tabs = data.tabs.filter((t) => t && t.id);
    state.activeTab = data.activeTab || null;
  } catch (_) {
    state.tabs = [];
    state.activeTab = null;
  }
}

function persistTabs() {
  try {
    localStorage.setItem(TABS_KEY, JSON.stringify({ tabs: state.tabs, activeTab: state.activeTab }));
  } catch (_) { /* stockage indisponible */ }
}

function renderTabs() {
  const bar = $("#tabbar");
  if (!bar) return;
  if (userRole(state.user) === "agent") {
    bar.classList.add("hidden");
    bar.innerHTML = "";
    return;
  }
  if (!state.tabs.length) {
    bar.classList.add("hidden");
    bar.innerHTML = "";
    return;
  }
  bar.classList.remove("hidden");
  bar.innerHTML = state.tabs.map((t) => `
    <div class="tab${t.id === state.activeTab ? " active" : ""}" data-tab-id="${t.id}" title="${esc(t.nom)}">
      <span class="tab-label">${esc(t.nom)}</span>
      <button class="tab-close" data-close-id="${t.id}" title="Fermer l'onglet">×</button>
    </div>`).join("") + (canCreateFiche()
      ? `<button class="tab tab-new" id="tab-new" title="Nouvelle fiche">+</button>` : "");

  $$("#tabbar .tab[data-tab-id]").forEach((el) => {
    el.addEventListener("click", (e) => {
      if (e.target.closest(".tab-close")) return;
      const id = Number(el.dataset.tabId);
      if (id !== state.activeTab) location.hash = "#/agent/" + id;
    });
  });
  $$("#tabbar .tab-close").forEach((btn) => {
    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      closeTab(Number(btn.dataset.closeId));
    });
  });
  const nb = $("#tab-new");
  if (nb) nb.addEventListener("click", openNewFicheModal);
}

function upsertTab(id, nom) {
  let t = state.tabs.find((x) => x.id === id);
  if (!t) {
    t = { id, nom: nom || "Fiche " + id };
    state.tabs.push(t);
  } else if (nom) {
    t.nom = nom;
  }
  state.activeTab = id;
  persistTabs();
  renderTabs();
}

function dropTab(id) {
  const idx = state.tabs.findIndex((t) => t.id === id);
  if (idx === -1) return;
  state.tabs.splice(idx, 1);
  if (state.activeTab === id) state.activeTab = null;
  persistTabs();
  renderTabs();
}

async function closeTab(id) {
  const idx = state.tabs.findIndex((t) => t.id === id);
  if (idx === -1) return;
  await flushPendingSave();
  state.tabs.splice(idx, 1);
  persistTabs();
  if (state.activeTab === id) {
    const next = state.tabs[Math.min(idx, state.tabs.length - 1)];
    state.activeTab = null;
    if (next) location.hash = "#/agent/" + next.id;
    else location.hash = "#/agents";
  }
  renderTabs();
}

/* Enregistre immédiatement une éventuelle modification en attente. */
async function flushPendingSave() {
  if (state.saveTimer) {
    clearTimeout(state.saveTimer);
    state.saveTimer = null;
    await saveFiche();
  }
}

/* ---------------------------- routage ---------------------------- */
window.addEventListener("hashchange", route);

async function route() {
  if (!state.user) return;
  const hash = location.hash || "#/dashboard";
  $$("#main-nav a").forEach((a) => {
    let active = hash.startsWith(a.getAttribute("href"));
    if (a.dataset.nav === "agents" && userRole(state.user) === "agent" && hash.startsWith("#/agent/")) {
      active = true;
    }
    a.classList.toggle("active", active);
  });
  const m = hash.match(/^#\/agent\/(\d+)/);
  if (m) {
    const id = parseInt(m[1], 10);
    // On change de fiche : sauvegarder les modifications en attente.
    if (state.fiche && state.fiche.id !== id) await flushPendingSave();
    return viewFiche(id);
  }
  // On quitte une fiche : sauvegarder les modifications en attente.
  if (state.fiche) await flushPendingSave();
  state.activeTab = null;
  persistTabs();
  renderTabs();
  if (hash.startsWith("#/agents")) return viewAgents();
  if (hash.startsWith("#/requests")) return viewRequests();
  if (hash.startsWith("#/hr")) return viewHrDashboard();
  if (hash.startsWith("#/planning")) return viewPlanning();
  if (hash.startsWith("#/settings")) return viewAdmin(hash);
  if (hash.startsWith("#/users")) {
    if (state.user.admin) { location.hash = "#/settings/users"; return; }
    return viewUsers();
  }
  if (hash.startsWith("#/apikeys")) { location.hash = "#/settings/apikeys"; return; }
  if (hash.startsWith("#/versions")) return viewVersions();
  return viewDashboard();
}

/* ==========================================================================
   Tableau de bord global
   ========================================================================== */
async function viewAgentDashboard() {
  const c = $("#content");
  c.innerHTML = `<h1>Ma synthèse ${state.year || ""}</h1><p>Chargement.</p>`;
  try {
    const agents = await api("/api/agents?year=" + state.year);
    if (!agents || !agents.length) {
      c.innerHTML = `
        <h1>Ma synthèse ${state.year || ""}</h1>
        <div class="card">
          <p>Aucune fiche n'est disponible pour cette année.</p>
          <a class="btn" href="#/agents">Ouvrir ma fiche</a>
        </div>`;
      return;
    }
    const f = await api("/api/agents/" + agents[0].id);
    const [calc, requests, validators] = await Promise.all([
      api("/api/compute", {
        method: "POST",
        body: JSON.stringify({
          params: f.params,
          periods: f.periods || [],
          cells: f.cells,
          year: f.year,
          cassages: f.cassages || [],
          hourly: f.hourly || [],
          recoveries: f.recoveries || [],
        }),
      }),
      api("/api/requests?scope=mine&year=" + state.year),
      api("/api/validators?agent_id=" + f.id + "&year=" + f.year).catch(() => []),
    ]);
    state.fiche = f;
    state.compute = calc;

    const s = calc.solde || {};
    const p = f.params || {};
    const dayWord = (v) => Math.abs(Number(v)) === 1 ? "jour" : "jours";
    const ca = s.ca || {};
    const rtt = s.rtt || {};
    const js = s.js || {};
    const jb = s.jb || {};
    const cet = s.cet || {};
    const now = new Date();
    const todayLabel = `${String(now.getDate()).padStart(2, "0")}/${String(now.getMonth() + 1).padStart(2, "0")}/${now.getFullYear()}`;
    const validator = (validators || []).find((v) => String(v.id) === String(f.validator_id));
    const validatorAccount = validator
      ? `${validator.nom || validator.login} (${validator.login})`
      : "—";
    const validatorManager = validator && validator.manager_name ? validator.manager_name : "";
    const statusLabels = {
      en_attente: "En attente",
      validee: "Validée",
      refusee: "Refusée",
      annulee: "Annulée",
      annulation_demandee: "Annulation demandée",
    };
    const recent = (requests || []).slice(0, 5);
    const hourRows = [["CAH", s.cah], ["RTTH", s.rth], ["RCH", s.rch]];
    const balanceCard = (title, code, value, negative = false) => {
      const hex = codeColorMap()[code] || "#b4553f";
      const style = `--sb-tint:linear-gradient(180deg, ${mixColor(hex, 0.18)}, ${mixColor(hex, 0.06)}); --sb-line:${cssColor(hex)}; --sb-ink:${shadeColor(hex, 0.55)};`;
      return `<div class="agent-balance-card" style="${style}">
        <div class="agent-balance-label">${title}</div>
        <div class="agent-balance-value${negative ? " neg" : ""}">${value}</div>
      </div>`;
    };

    c.innerHTML = `
      <div class="agent-dashboard-head">
        <h1>Ma synthèse ${f.year || state.year || ""}</h1>
      </div>
      <p class="agent-dashboard-sub">Vue synthétique de vos soldes, de vos demandes récentes et de vos heures.</p>
      ${rchExpiryAlert(calc)}

      <div class="card agent-info-card agent-account-card">
        <h3>Compte agent</h3>
        <div class="agent-account-grid">
          <div>
            <span class="agent-account-label">Agent</span>
            <b class="agent-account-name">${esc(agentName(f))}</b>
          </div>
          <div>
            <span class="agent-account-label">E-mail</span>
            <b>${esc(f.email || "—")}</b>
          </div>
          <div class="agent-validator-callout">
            <span>Vos congés sont validés par</span>
            <b class="agent-validator-account">${esc(validatorAccount)}</b>
            ${validatorManager ? `<span class="agent-validator-person">— ${esc(validatorManager)}</span>` : ""}
          </div>
        </div>
        <div class="agent-account-params">
          <div><span class="agent-account-label">Temps de travail</span><b>${esc(p.duree_hebdo || "—")}</b></div>
          <div><span class="agent-account-label">Jours / semaine</span><b>${esc(p.jours_hebdo || "—")}</b></div>
          <div><span class="agent-account-label">Quotité</span><b>${esc(p.quotite || "—")}</b></div>
          <div><span class="agent-account-label">Pénibilité</span><b>${esc(p.penibilite || "—")}</b></div>
          ${p.date_arrivee ? `<div><span class="agent-account-label">Date d'arrivée</span><b>${esc(frDate(p.date_arrivee))}</b></div>` : ""}
          ${p.date_depart ? `<div><span class="agent-account-label">Date de départ</span><b>${esc(frDate(p.date_depart))}</b></div>` : ""}
        </div>
      </div>

      <h2 class="agent-section-title">Solde des congés au ${todayLabel}</h2>
      <div class="agent-synthesis-layout">
        <div class="agent-synthesis-left">
      <div class="agent-balance-grid">
        ${balanceCard("Congés annuels", "CA", `${fmt(ca.restant)} <small>${dayWord(ca.restant)}</small>`, ca.restant < 0)}
        ${balanceCard("RTT", "RTT", `${fmt(rtt.restant)} <small>${dayWord(rtt.restant)}</small>`, rtt.restant < 0)}
        ${balanceCard("Jours de sujétion", "JS", `${fmt(js.restant)} <small>${dayWord(js.restant)}</small>`, js.restant < 0)}
        ${balanceCard("Bonification", "JB", `${fmt(jb.restant)} <small>${dayWord(jb.restant)}</small>`, jb.restant < 0)}
        ${balanceCard("CET", "CET", `${fmt(cet.restant)} <small>${dayWord(cet.restant)}</small>`, cet.restant < 0)}
      </div>
        </div>

        <div class="agent-synthesis-right">
        <div class="card agent-recent-card">
          <h3>Demandes récentes</h3>
          ${recent.length ? `<div class="requests-wrap"><table class="data">
            <thead><tr><th>Période</th><th>Code</th><th class="num">Quantité</th><th>Statut</th><th>Validateur</th></tr></thead>
            <tbody>${recent.map((r) => `<tr>
              <td>${esc(requestPeriodLabel(r))}</td>
              <td>${esc(r.code || "")}</td>
              <td class="num">${esc(requestQuantityLabel(r))}</td>
              <td><span class="status-badge status-${esc(r.status)}">${esc(statusLabels[r.status] || r.status)}</span></td>
              <td>${esc(r.validator_account_name || r.validator_login || "—")}</td>
            </tr>`).join("")}</tbody>
          </table></div>` : `<p class="muted">Aucune demande récente.</p>`}
          <a class="btn btn-small" href="#/requests">Voir toutes mes demandes</a>
        </div>

        <div class="card agent-hours-card">
          <div class="hours-counter-head">
            <h3>Compteur d'heures</h3>
            <button type="button" class="btn btn-small" id="agent-hours-detail">Voir le détail</button>
          </div>
          <div class="requests-wrap">
            <table class="data">
              <thead><tr><th>Compteur</th><th class="num">Crédit</th><th class="num">Pris</th><th class="num">Restant</th><th>Échéance</th></tr></thead>
              <tbody>${hourRows.map(([label, h]) => `<tr>
                <td><b>${label}</b></td>
                <td class="num">${fmtHours(h && h.credit)}</td>
                <td class="num">${fmtHours(h && h.used_year)}</td>
                <td class="num">${fmtHours(h && h.restant)}</td>
                <td>${h && h.next_expiry ? esc(frDate(h.next_expiry)) : "—"}</td>
              </tr>`).join("")}</tbody>
            </table>
          </div>
          <p class="hours-counter-note">Les heures sont consommées en priorité sur les crédits les plus anciens.</p>
        </div>
        </div>
      </div>
    `;

    const hoursBtn = $("#agent-hours-detail");
    if (hoursBtn) hoursBtn.addEventListener("click", openHoursDetailModal);
  } catch (err) {
    c.innerHTML = `<h1>Ma synthèse ${state.year || ""}</h1><div class="form-error">${esc(err.message)}</div>`;
  }
}


async function viewDashboard() {
  if (userRole(state.user) === "agent") return viewAgentDashboard();
  const c = $("#content");
  c.innerHTML = `<h1>Tableau de bord ${state.year || ""}</h1><p>Chargement…</p>`;
  try {
    if (state.dashboardAll === null) state.dashboardAll = canViewTeam();
    const all = canViewTeam() && state.dashboardAll;
    const rows = await api("/api/dashboard?year=" + state.year + (all ? "&all=1" : ""));
    const allLabel = state.user.admin ? "Toutes les fiches" : "Toutes les fiches de mon périmètre";
    const adminToggle = canViewTeam()
      ? `<label class="inline"><input type="checkbox" id="dash-all" ${all ? "checked" : ""}> ${allLabel}</label>`
      : "";

    let scopeUsers = [];
    try { scopeUsers = await api("/api/scope-users"); } catch (_) { scopeUsers = []; }

    const usersById = {};
    (scopeUsers || []).forEach((u) => { usersById[u.id] = u; });
    if (state.user && !usersById[state.user.id]) usersById[state.user.id] = state.user;
    const children = {};
    Object.values(usersById).forEach((u) => {
      if (u.parent_id != null) (children[u.parent_id] = children[u.parent_id] || []).push(u);
    });
    const rowsByOwner = {};
    rows.forEach((r) => {
      const key = r.owner_id != null ? r.owner_id : null;
      (rowsByOwner[key] = rowsByOwner[key] || []).push(r);
    });
    Object.values(rowsByOwner).forEach((list) => list.sort((a, b) => {
      const ma = a.is_manager ? 1 : 0;
      const mb = b.is_manager ? 1 : 0;
      if (ma !== mb) return mb - ma;
      return String(a.nom || "").localeCompare(String(b.nom || ""), "fr");
    }));
    const scopeIds = new Set(Object.keys(usersById).map(Number));
    let roots = [];
    if (state.user.admin) {
      roots = Object.values(usersById).filter((u) => u.parent_id == null || !scopeIds.has(Number(u.parent_id)));
    } else if (userRole(state.user) === "agent" && state.user.parent_id) {
      roots = [usersById[state.user.parent_id]].filter(Boolean);
      if (!roots.length) roots = [usersById[state.user.id]].filter(Boolean);
    } else {
      roots = [usersById[state.user.id]].filter(Boolean);
      if (!roots.length) roots = Object.values(usersById).filter((u) => rowsByOwner[u.id]);
    }
    roots = roots.filter(Boolean).sort(byRoleName);

    const subtreeHasRows = (u) => {
      if ((rowsByOwner[u.id] || []).length) return true;
      return (children[u.id] || []).some((c) => subtreeHasRows(c));
    };
    const renderedUsers = new Set();
    const renderedRows = new Set();
    const dashRow = (r) => `
      <tr class="dash-row${r.is_manager ? " dash-manager" : ""}">
        <td class="dash-fiche"><a class="dash-fiche-link" href="#/agent/${r.id}"><span>${esc(r.nom || "")}</span>${r.is_manager ? `<span class="manager-tag">(Responsable)</span>` : ""}<span class="dash-arrow">→</span></a></td>
        <td class="dash-owner" title="${esc(r.owner_name || "")}">${esc(r.owner_name || "—")}</td>
        <td class="dash-cycle" title="${esc(r.cycle || "")}">${esc(r.cycle || "—")}</td>
        <td class="num">${fmt(r.ca && r.ca.pris)}</td>
        <td class="num ${r.ca && r.ca.restant < 0 ? "neg" : ""}">${fmt(r.ca && r.ca.restant)}</td>
        <td class="num ${r.rtt && r.rtt.restant < 0 ? "neg" : ""}">${fmt(r.rtt && r.rtt.restant)}</td>
        <td class="num ${r.js && r.js.restant < 0 ? "neg" : ""}">${fmt(r.js && r.js.restant)}</td>
        <td class="num ${r.jb && r.jb.restant < 0 ? "neg" : ""}">${fmt(r.jb && r.jb.restant)}</td>
        <td class="num ${r.cet && r.cet.restant < 0 ? "neg" : ""}">${fmt(r.cet && r.cet.restant)}</td>
        <td class="num dash-total">${fmt(r.total && r.total.pris)}</td>
        <td class="num dash-total ${r.total && r.total.restant < 0 ? "neg" : ""}">${fmt(r.total && r.total.restant)}</td>
      </tr>`;
    let bodyRows = "";
    const renderNode = (u, level) => {
      if (!u || renderedUsers.has(u.id)) return;
      renderedUsers.add(u.id);
      const own = rowsByOwner[u.id] || [];
      const kids = sortHierarchyChildren(u, (children[u.id] || []).filter(Boolean));
      if (!own.length && !kids.some((c) => subtreeHasRows(c))) return;
      const name = u.nom || u.login || "—";
      bodyRows += `<tr class="dash-group level-${Math.min(level, 3)} role-${userRole(u)}"><td colspan="11"><div class="dash-group-inner"><span>${esc(name)}</span><span class="dash-group-count">${own.length} fiche${own.length > 1 ? "s" : ""}</span></div></td></tr>`;
      own.forEach((r) => { bodyRows += dashRow(r); renderedRows.add(r.id); });
      kids.forEach((c) => renderNode(c, level + 1));
    };
    roots.forEach((u) => renderNode(u, 0));
    rows.filter((r) => !renderedRows.has(r.id)).forEach((r) => { bodyRows += dashRow(r); });
    if (!bodyRows) bodyRows = `<tr><td colspan="11" class="dash-empty">Aucune fiche à afficher.</td></tr>`;

    c.innerHTML = `
      <h1>Tableau de bord ${state.year || ""}</h1>
      <div class="dash-filters">
        ${adminToggle}
        <span class="dash-hint">Regroupement par responsable</span>
      </div>
      <div class="dash-table-wrap">
        <table class="data dashboard">
          <thead><tr>
            <th>Fiche</th><th>Propriétaire</th><th>Cycle</th>
            <th class="num">CA pris</th><th class="num">CA restant</th>
            <th class="num">RTT restant</th><th class="num">Sujétion restant</th>
            <th class="num">Bonification restant</th><th class="num">CET restant</th>
            <th class="num">Total pris</th><th class="num">Total restant</th>
          </tr></thead>
          <tbody>${bodyRows}</tbody>
        </table>
      </div>`;
    const cb = $("#dash-all");
    if (cb) cb.addEventListener("change", (e) => { state.dashboardAll = e.target.checked; viewDashboard(); });
  } catch (err) {
    c.innerHTML = `<h1>Tableau de bord ${state.year || ""}</h1><div class="form-error">${esc(err.message)}</div>`;
  }
}

async function viewHrDashboard() {
  if (userRole(state.user) === "agent") {
    location.hash = "#/dashboard";
    return;
  }
  const c = $("#content");
  c.innerHTML = `<h1>Tableau de bord RH ${state.year || ""}</h1><p>Chargement.</p>`;
  try {
    const data = await api("/api/hr-dashboard?year=" + state.year);
    const t = data.totals || {};
    const tree = data.tree || [];
    const late = data.late_items || [];
    const rch = data.rch_items || [];
    const kpi = (label, value, detail = "") =>
      `<div class="hr-kpi"><span>${label}</span><b>${value}</b>${detail ? `<small>${detail}</small>` : ""}</div>`;
    const renderTreeLeaf = (f) => `<div class="hr-tree-leaf role-agent">
      <span class="hr-tree-marker"></span>
      <span class="hr-tree-row">
        <span class="hr-tree-name">${esc(f.label)}</span>
        <span class="num">${fmt(f.agents)}</span>
        <span class="num">${fmt(f.absences)} j</span>
        <span class="num">${fmt(f.rate)} %</span>
      </span>
    </div>`;
    const renderTreeNode = (node, depth = 0) => `<details class="hr-tree-node role-${esc(node.role)}"${depth <= 2 ? " open" : ""}>
      <summary class="hr-tree-summary">
        <span class="hr-tree-marker"></span>
        <span class="hr-tree-row">
          <span class="hr-tree-name">${esc(node.label)}</span>
          <span class="num">${fmt(node.agents)}</span>
          <span class="num">${fmt(node.absences)} j</span>
          <span class="num">${fmt(node.rate)} %</span>
        </span>
      </summary>
      <div class="hr-tree-children">
        ${(node.children || []).map((child) => renderTreeNode(child, depth + 1)).join("")}
        ${(node.fiches || []).map(renderTreeLeaf).join("")}
      </div>
    </details>`;
    c.innerHTML = `
      <h1>Tableau de bord RH ${data.year || state.year || ""}</h1>
      <p class="users-hint">Indicateurs RH sur les fiches de votre périmètre : absences, taux d'absence, demandes en retard et heures de récupération à échéance.</p>
      <div class="hr-kpis">
        ${kpi("Agents", fmt(t.agents || 0), "fiches suivies")}
        ${kpi("Absences", `${fmt(t.absences || 0)} j`, "cumul sur l'année")}
        ${kpi("Taux d'absence", `${fmt(t.rate || 0)} %`, "absences / capacité")}
        ${kpi("Demandes en retard", fmt(t.late_requests || 0), "plus de 3 jours")}
        ${kpi("RCH à échéance", fmt(t.rch_expiring || 0), "dans les 30 jours")}
      </div>

      <div class="card">
        <h3>Absences par direction / service</h3>
        <p class="users-hint">Cliquez sur une direction ou un service pour dérouler le détail jusqu'aux agents.</p>
        ${tree.length ? `<div class="hr-tree-head">
          <span class="hr-tree-marker"></span>
          <span class="hr-tree-row">
            <span>Unité / agent</span><span class="num">Agents</span><span class="num">Absences</span><span class="num">Taux</span>
          </span>
        </div><div class="hr-tree">${tree.map((node) => renderTreeNode(node, 0)).join("")}</div>` : `<p class="muted">Aucune donnée.</p>`}
      </div>

      <div class="hr-grid">
        <div class="card">
          <h3>Demandes en retard</h3>
          ${late.length ? `<div class="requests-wrap"><table class="data">
            <thead><tr><th>Agent</th><th>Code</th><th>Demandée le</th><th>Validateur</th><th class="num">Jours</th></tr></thead>
            <tbody>${late.map((row) => `<tr>
              <td>${esc(row.agent_nom || "")}</td>
              <td>${esc(row.code || "")}</td>
              <td>${esc(frDate(row.soumis_le || row.cree_le))}</td>
              <td>${esc(row.validator_nom || row.validator_login || "—")}</td>
              <td class="num">${fmt(row.jours || 0)}</td>
            </tr>`).join("")}</tbody>
          </table></div>` : `<p class="muted">Aucune demande en retard.</p>`}
        </div>
        <div class="card">
          <h3>Heures RCH à échéance</h3>
          ${rch.length ? `<div class="requests-wrap"><table class="data">
            <thead><tr><th>Agent</th><th class="num">Heures</th><th>Réalisées le</th><th>Échéance</th></tr></thead>
            <tbody>${rch.map((row) => `<tr>
              <td>${esc(row.agent_nom || "")}</td>
              <td class="num">${fmtHours(row.hours)}</td>
              <td>${esc(frDate(row.absence_date))}</td>
              <td>${esc(frDate(row.valid_until))}</td>
            </tr>`).join("")}</tbody>
          </table></div>` : `<p class="muted">Aucune heure à échéance dans les 30 jours.</p>`}
        </div>
      </div>`;
  } catch (err) {
    c.innerHTML = `<h1>Tableau de bord RH</h1><div class="form-error">${esc(err.message)}</div>`;
  }
}

/* ==========================================================================
   Liste des fiches
   ========================================================================== */
async function viewAgents() {
  const c = $("#content");
  if (userRole(state.user) === "agent") {
    try {
      const own = await api("/api/agents?year=" + state.year);
      if (own.length) {
        location.hash = "#/agent/" + own[0].id;
        return;
      }
    } catch (_) { /* on affichera la liste vide plus bas */ }
  }
  const baseTitle = userRole(state.user) === "agent" ? "Ma fiche" : (canViewTeam() ? "Fiches de mon périmètre" : "Mes fiches");
  const title = baseTitle + " — " + state.year;
  c.innerHTML = `<h1>${title}</h1><p>Chargement…</p>`;
  const agents = await api("/api/agents?year=" + state.year);
  state.agents = agents;
  const ownIds = agents
    .filter((a) => canEditFiche(a) && (a.user_id === state.user.id || state.user.admin))
    .map((a) => a.id);

  // Utilisateurs du périmètre pour regrouper les fiches par niveau hiérarchique.
  // Un agent ne voit que sa propre fiche ici ; son planning est traité à part.
  let scopeUsers = [];
  if (userRole(state.user) === "agent") {
    scopeUsers = [{
      id: state.user.id,
      login: state.user.login,
      nom: state.user.nom,
      role: "agent",
      parent_id: state.user.parent_id,
    }];
  } else {
    try { scopeUsers = await api("/api/scope-users"); } catch (_) { scopeUsers = []; }
  }

  const cardHtml = (a) => {
    const own = canEditFiche(a) && (a.user_id === state.user.id || state.user.admin);
    const canEdit = canEditFiche(a);
    return `
      <div class="card agent-card${a.is_manager ? " manager-card" : ""}" data-id="${a.id}" data-year="${a.year}">
        ${own ? `<input type="checkbox" class="agent-select" data-id="${a.id}" title="Sélectionner pour duplication">` : ""}
        <h3>${esc(agentName(a))}</h3>
        <div class="meta">
          Propriétaire : ${esc(a.proprietaire || "–")}<br>
          E-mail : ${esc(a.email || "–")}<br>
          Pénibilité : ${esc(a.params.penibilite || "–")} · Quotité : ${esc(a.params.quotite || "–")}<br>
          Modifiée le ${esc((a.modifie_le || "").slice(0, 16).replace("T", " "))}
          ${a.pending_count ? `<br><span class="pending-note">${a.pending_count} demande(s) en attente</span>` : ""}
        </div>
        <div class="row-actions">
          <button class="btn btn-small" data-act="open">Ouvrir</button>
          ${own ? `<button class="btn btn-small" data-act="clone">Dupliquer en ${a.year + 1}</button>` : ""}
          ${canEdit ? `<button class="btn btn-small btn-danger" data-act="del">Supprimer</button>` : ""}
        </div>
      </div>`;
  };

  const agentsByUser = {};
  const groupKey = (a) => userRole(state.user) === "agent" ? a.agent_user_id : a.user_id;
  agents.forEach((a) => { (agentsByUser[groupKey(a)] = agentsByUser[groupKey(a)] || []).push(a); });
  Object.values(agentsByUser).forEach((list) => list.sort((a, b) => {
    const ma = a.is_manager ? 1 : 0;
    const mb = b.is_manager ? 1 : 0;
    if (ma !== mb) return mb - ma;
    return String(agentName(a) || "").localeCompare(String(agentName(b) || ""), "fr");
  }));
  const kids = {};
  scopeUsers.forEach((u) => {
    if (u.parent_id != null) (kids[u.parent_id] = kids[u.parent_id] || []).push(u);
  });
  const scopeIds = new Set(scopeUsers.map((u) => u.id));
  let roots;
  if (state.user.admin) {
    roots = scopeUsers.filter((u) => u.parent_id == null || !scopeIds.has(u.parent_id));
  } else {
    roots = scopeUsers.filter((u) => u.id === state.user.id);
  }
  roots.sort(byRoleName);

  const subtreeHasAgents = (u) => {
    if ((agentsByUser[u.id] || []).length) return true;
    return (kids[u.id] || []).some((child) => subtreeHasAgents(child));
  };
  const renderedUsers = new Set();
  const renderedAgents = new Set();
  let sections = "";
  const renderNode = (u, level) => {
    if (renderedUsers.has(u.id)) return;
    renderedUsers.add(u.id);
    const own = agentsByUser[u.id] || [];
    const children = sortHierarchyChildren(u, kids[u.id] || []);
    if (!own.length && !children.some((child) => subtreeHasAgents(child))) return;
    const roleLabel = ROLE_LABELS[userRole(u)] || userRole(u);
    const display = (u.nom && u.nom !== roleLabel) ? u.nom : u.login;
    const count = own.length;
    sections += `
      <div class="agent-group" style="margin-left:${Math.min(level, 3) * 20}px">
        <div class="agent-group-head role-${userRole(u)}">
          <span>${esc(display)}</span>
          <span class="agent-group-count">${count} fiche${count > 1 ? "s" : ""}</span>
        </div>
        ${own.length ? `<div class="agents-grid">${own.map(cardHtml).join("")}</div>` : ""}
      </div>`;
    own.forEach((a) => renderedAgents.add(a.id));
    children.forEach((child) => renderNode(child, level + 1));
  };
  roots.forEach((u) => renderNode(u, 0));
  scopeUsers.filter((u) => !renderedUsers.has(u.id)).sort(byRoleName).forEach((u) => renderNode(u, 0));

  const orphans = agents.filter((a) => !renderedAgents.has(a.id)).sort((a, b) => {
    const ma = a.is_manager ? 1 : 0;
    const mb = b.is_manager ? 1 : 0;
    if (ma !== mb) return mb - ma;
    return String(agentName(a) || "").localeCompare(String(agentName(b) || ""), "fr");
  });
  if (orphans.length) {
    sections += `
      <div class="agent-group">
        <div class="agent-group-head">
          <span>Autres fiches</span>
          <span class="agent-group-count">${orphans.length} fiche${orphans.length > 1 ? "s" : ""}</span>
        </div>
        <div class="agents-grid">${orphans.map(cardHtml).join("")}</div>
      </div>`;
  }

  c.innerHTML = `
    <div class="fiche-header">
      <h1 style="flex:1">${title}</h1>
      <label class="inline agent-select-all"><input type="checkbox" id="select-all-agents"> Tout sélectionner</label>
      <button class="btn" id="btn-dup-selected" disabled>Dupliquer la sélection en ${state.year + 1}</button>
      <button class="btn" id="btn-dup-all" ${ownIds.length ? "" : "disabled"}>Dupliquer toutes les fiches en ${state.year + 1}</button>
      ${canCreateFiche() ? `<button class="btn btn-primary" id="btn-new-agent">+ Nouvelle fiche</button>` : ""}
    </div>
    ${sections || "<p>Aucune fiche pour le moment.</p>"}`;

  const newBtn = $("#btn-new-agent");
  if (newBtn) newBtn.addEventListener("click", openNewFicheModal);

  $$(".agent-card").forEach((card) => {
    const id = card.dataset.id;
    const year = Number(card.dataset.year);
    card.addEventListener("click", (e) => {
      if (e.target.closest(".agent-select")) return;
      const act = e.target.dataset && e.target.dataset.act;
      if (act === "clone") {
        e.stopPropagation();
        const target = year + 1;
        api("/api/agents/duplicate", {
          method: "POST",
          body: JSON.stringify({ ids: [Number(id)], year: target }),
        })
          .then((res) => {
            const n = (res.created || []).length;
            toast(n ? `Fiche dupliquée en ${target}` : "Duplication impossible");
            if (n) setYear(target, "#/agents");
          })
          .catch((err) => toast(err.message, true));
      } else if (act === "del") {
        e.stopPropagation();
        if (!confirm("Supprimer définitivement cette fiche ?")) return;
        api(`/api/agents/${id}`, { method: "DELETE" })
          .then(() => { dropTab(Number(id)); toast("Fiche supprimée"); viewAgents(); })
          .catch((err) => toast(err.message, true));
      } else {
        location.hash = "#/agent/" + id;
      }
    });
  });

  // Duplication groupée vers l'année suivante
  const bulkBtn = $("#btn-dup-selected");
  const selectAll = $("#select-all-agents");
  const boxes = $$(".agent-select");
  const updateBulk = () => {
    const n = boxes.filter((b) => b.checked).length;
    bulkBtn.disabled = n === 0;
    bulkBtn.textContent = n
      ? `Dupliquer ${n} fiche(s) en ${state.year + 1}`
      : `Dupliquer la sélection en ${state.year + 1}`;
    if (selectAll) {
      selectAll.checked = boxes.length > 0 && n === boxes.length;
      selectAll.indeterminate = n > 0 && n < boxes.length;
    }
  };
  boxes.forEach((cb) => cb.addEventListener("change", updateBulk));
  if (selectAll) {
    selectAll.addEventListener("change", () => {
      boxes.forEach((cb) => { cb.checked = selectAll.checked; });
      updateBulk();
    });
  }
  updateBulk();

  const duplicate = async (ids) => {
    if (!ids.length) return;
    const target = state.year + 1;
    try {
      const res = await api("/api/agents/duplicate", {
        method: "POST",
        body: JSON.stringify({ ids, year: target }),
      });
      const n = (res.created || []).length;
      toast(`${n} fiche(s) dupliquée(s) en ${target}`);
      if (n) setYear(target, "#/agents");
    } catch (err) {
      toast(err.message, true);
    }
  };

  bulkBtn.addEventListener("click", () => {
    duplicate(boxes.filter((b) => b.checked).map((b) => Number(b.dataset.id)));
  });

  $("#btn-dup-all").addEventListener("click", () => {
    if (!ownIds.length) return;
    if (!confirm(`Dupliquer les ${ownIds.length} fiche(s) de ${state.year} en ${state.year + 1} ?`)) return;
    duplicate(ownIds);
  });
}

/* ==========================================================================
   Demandes de congés
   ========================================================================== */
function requestPeriodLabel(r) {
  if (r.request_type === "cassage") return "Cassage de 1 jour";
  if (r.request_type === "recuperation") return frDate(r.absence_date);
  if (r.request_type === "heures") {
    return `${frDate(r.absence_date)} ${r.start_time || ""}–${r.end_time || ""}`;
  }
  const cells = (r.cells || []).slice().sort((a, b) => a - b);
  if (!cells.length) return "—";
  const short = (k) => {
    const m = Math.floor(k / 1000);
    const d = Math.floor((k % 1000) / 10);
    const h = k % 10;
    return `${String(d).padStart(2, "0")}/${String(m).padStart(2, "0")}${h === 0 ? " matin" : " après-midi"}`;
  };
  const first = short(cells[0]);
  const last = short(cells[cells.length - 1]);
  return first === last ? first : `${first} → ${last}`;
}

function requestQuantityLabel(r) {
  if (r.request_type === "heures" || r.request_type === "recuperation") return fmtHours(r.hours);
  if (r.request_type === "cassage") return "1 j";
  return fmt(r.days) + " j";
}

async function viewRequests() {
  if (!state.user) return;
  const c = $("#content");
  const year = state.year;
  const pageTitle = userRole(state.user) === "agent" ? "Mes demandes" : "Demandes";
  c.innerHTML = `<h1>${pageTitle} — ${year}</h1><p>Chargement…</p>`;
  try {
    const mine = await api(`/api/requests?scope=mine&year=${year}`);
    let toValidate = [];
    let perimeter = [];
    let all = [];
    if (canValidateRequests()) {
      toValidate = await api(`/api/requests?scope=to_validate&year=${year}`);
      if (!state.user.admin) {
        perimeter = await api(`/api/requests?scope=perimeter&year=${year}`);
      }
    }
    if (state.user.admin) {
      all = await api(`/api/requests?scope=all&year=${year}`);
    }
    const statusLabel = {
      en_attente: "En attente",
      validee: "Validée",
      refusee: "Refusée",
      annulee: "Annulée",
      annulation_demandee: "Annulation demandée",
    };
    const reqPeriod = (r) => {
      if (r.request_type === "cassage") return "Cassage de 1 jour";
      if (r.request_type === "recuperation") return frDate(r.absence_date);
      if (r.request_type === "heures") {
        return `${frDate(r.absence_date)} ${r.start_time || ""}–${r.end_time || ""}`;
      }
      const cells = (r.cells || []).slice().sort((a, b) => a - b);
      if (!cells.length) return "—";
      const short = (k) => {
        const m = Math.floor(k / 1000);
        const d = Math.floor((k % 1000) / 10);
        const h = k % 10;
        return `${String(d).padStart(2, "0")}/${String(m).padStart(2, "0")}${h === 0 ? " matin" : " après-midi"}`;
      };
      const first = short(cells[0]);
      const last = short(cells[cells.length - 1]);
      return first === last ? first : `${first} → ${last}`;
    };
    const rowHtml = (r, mode) => {
      const isCancel = r.status === "annulation_demandee";
      const canDecide = mode === "to_validate" && (r.status === "en_attente" || isCancel);
      const canCancel = mode === "mine" && r.status === "en_attente";
      const canCancelRequest = mode === "mine" && r.status === "validee";
      const validatorAccount = r.validator_account_name || r.validator_nom || r.validator_login || "—";
      const validatorManager = r.validator_manager_name || "—";
      const parts = [r.comment, r.decision_comment];
      if (r.cancel_reason) parts.push("Annulation : " + r.cancel_reason);
      if (r.cancel_decision_comment) parts.push("Décision annulation : " + r.cancel_decision_comment);
      const comment = parts.filter(Boolean).join(" · ");
      const attachment = r.attachment_name
        ? `<button class="btn btn-small" data-req-attach="${r.id}" data-attach-name="${esc(r.attachment_name)}">Pièce jointe</button>`
        : "—";
      const submitted = r.soumis_le || r.cree_le || "";
      const submittedTime = submitted.length >= 16 ? submitted.slice(11, 16) : "";
      const quantity = (r.request_type === "heures" || r.request_type === "recuperation")
        ? fmtHours(r.hours)
        : (r.request_type === "cassage" ? "1 j" : fmt(r.days) + " j");
      return `<tr data-code="${esc(r.code)}" data-status="${esc(r.status)}" data-search="${esc([r.agent_nom, r.code, validatorAccount, validatorManager, comment, reqPeriod(r)].filter(Boolean).join(" "))}">
        <td class="req-date">${frDate(submitted)}${submittedTime ? ` <span class="req-time">${submittedTime}</span>` : ""}</td>
        <td>${esc(r.agent_nom || "")}</td>
        <td>${esc(reqPeriod(r))}</td>
        <td><b>${esc(r.code)}</b></td>
        <td class="num">${quantity}</td>
        <td><span class="status-badge status-${esc(r.status)}">${statusLabel[r.status] || esc(r.status)}</span></td>
        <td>${esc(validatorAccount)}</td>
        <td>${esc(validatorManager)}</td>
        <td>${esc(comment)}</td>
        <td>${attachment}</td>
        <td class="req-actions">
          ${canDecide ? `<button class="btn btn-small" data-req-approve="${r.id}" data-req-status="${r.status}">${isCancel ? "Valider l'annulation" : "Valider"}</button>
            <button class="btn btn-small btn-danger" data-req-refuse="${r.id}" data-req-status="${r.status}">${isCancel ? "Refuser l'annulation" : "Refuser"}</button>` : ""}
          ${canCancel ? `<button class="btn btn-small btn-ghost" data-req-cancel="${r.id}">Annuler</button>` : ""}
          ${canCancelRequest ? `<button class="btn btn-small" data-req-cancel-request="${r.id}">Demander l'annulation</button>` : ""}
        </td>
      </tr>`;
    };
    const table = (rows, mode) => rows.length
      ? `<div class="requests-wrap${userRole(state.user) === "agent" ? " requests-rounded" : ""}"><table class="data requests-table">
          <colgroup>
            <col style="width:10%"><col style="width:11%"><col style="width:11%"><col style="width:4%"><col style="width:4%">
            <col style="width:8%"><col style="width:10%"><col style="width:10%"><col style="width:9%"><col style="width:6%"><col style="width:17%">
          </colgroup>
          <thead><tr><th>Date de la demande</th><th>Demandeur</th><th>Période</th><th>Code</th><th class="num">Jours / h</th>
          <th>Statut</th><th>Validateur</th><th>Responsable d'unité</th><th>Commentaire</th><th>Pièce jointe</th><th>Actions</th></tr></thead>
          <tbody>${rows.map((r) => rowHtml(r, mode)).join("")}</tbody>
        </table></div>`
      : `<p class="muted">Aucune demande.</p>`;

    const isPending = (r) => ["en_attente", "annulation_demandee"].includes(r.status);
    const scopeOf = (r) => r.validator_scope
      || (r.validator_id === state.user.id ? "direct" : "subordinate");
    const validatorKey = (r) => (r.validator_group_id ?? r.validator_id) != null
      ? `v:${r.validator_group_id ?? r.validator_id}` : `u:${r.user_id}`;
    const validatorLabel = (r) => r.validator_group_label
      || (r.validator_id != null
        ? (r.validator_nom || r.validator_login || `Valideur #${r.validator_id}`)
        : (r.proprietaire_nom || r.proprietaire || `Créateur #${r.user_id}`));
    const groupsHtml = (rows, mode) => {
      const map = new Map();
      rows.forEach((r) => {
        const key = validatorKey(r);
        if (!map.has(key)) map.set(key, { label: validatorLabel(r), rows: [] });
        map.get(key).rows.push(r);
      });
      const groups = [...map.values()].sort((a, b) => a.label.localeCompare(b.label, "fr"));
      if (!groups.length) return `<p class="muted">Aucune demande.</p>`;
      return groups.map((g) => `<h3 class="req-validator-heading">${esc(g.label)} <span class="muted">(${g.rows.length})</span></h3>${table(g.rows, mode)}`).join("");
    };
    const directToValidate = toValidate.filter((r) => scopeOf(r) === "direct");
    const subordinateToValidate = toValidate.filter((r) => scopeOf(r) === "subordinate");
    const otherToValidate = toValidate.filter((r) => scopeOf(r) === "other");
    const perimeterHistory = perimeter.filter((r) => !isPending(r));
    const directHistory = perimeterHistory.filter((r) => scopeOf(r) === "direct");
    const subordinateHistory = perimeterHistory.filter((r) => scopeOf(r) === "subordinate");
    const otherHistory = perimeterHistory.filter((r) => scopeOf(r) === "other");
    const groupedValidation = canValidateRequests() && !state.user.admin;
    const requestCodeOptions = ((state.settings || {}).codes || [])
      .map((c) => `<option value="${esc(c.code)}">${esc(c.code)} — ${esc(c.libelle || c.code)}</option>`)
      .join("");

    c.innerHTML = `
      <h1>${pageTitle} — ${year}</h1>
      <p class="users-hint">Les demandes sont regroupées par valideur : vos agents directs, puis les valideurs sous votre responsabilité. Le circuit suit le responsable N+1, puis les valideurs hiérarchiques (N+2 et supérieurs).</p>
      <div class="requests-toolbar">
        <input type="search" id="requests-search" placeholder="Rechercher un agent, un code, un valideur ou un commentaire">
        <select id="requests-status-filter">
          <option value="">Tous les statuts</option>
          <option value="en_attente">En attente</option>
          <option value="validee">Validées</option>
          <option value="refusee">Refusées</option>
          <option value="annulee">Annulées</option>
          <option value="annulation_demandee">Annulation demandée</option>
        </select>
        <select id="requests-code-filter">
          <option value="">Tous les codes</option>
          ${requestCodeOptions}
        </select>
        <select id="requests-page-size">
          <option value="20">20 par page</option>
          <option value="50">50 par page</option>
          <option value="100">100 par page</option>
        </select>
      </div>
      ${groupedValidation ? `
        <h2>Agents validés par moi — à valider (${directToValidate.length})</h2>
        ${table(directToValidate, "to_validate")}
        <h2>Valideurs sous ma responsabilité — à valider (${subordinateToValidate.length})</h2>
        ${groupsHtml(subordinateToValidate, "to_validate")}
        ${otherToValidate.length ? `<h2>Autres demandes de mon périmètre — à valider (${otherToValidate.length})</h2>${groupsHtml(otherToValidate, "to_validate")}` : ""}
      ` : (canValidateRequests() ? `<h2>À valider (${toValidate.length})</h2>${table(toValidate, "to_validate")}` : "")}
      <h2>Mes demandes (${mine.length})</h2>
      ${table(mine, "mine")}
      ${groupedValidation ? `
        <h2>Historique — agents validés par moi (${directHistory.length})</h2>
        ${table(directHistory, "perimeter")}
        <h2>Historique — valideurs sous ma responsabilité (${subordinateHistory.length})</h2>
        ${groupsHtml(subordinateHistory, "perimeter")}
        ${otherHistory.length ? `<h2>Historique — autres demandes de mon périmètre (${otherHistory.length})</h2>${groupsHtml(otherHistory, "perimeter")}` : ""}
      ` : ""}
      ${state.user.admin ? `<h2>Toutes les demandes par valideur (${all.length})</h2>${groupsHtml(all, "all")}` : ""}
    `;

    const applyRequestFilters = () => {
      const q = ($("#requests-search").value || "").trim().toLowerCase();
      const status = $("#requests-status-filter").value;
      const code = $("#requests-code-filter").value;
      const pageSize = Number($("#requests-page-size").value) || 20;
      document.querySelectorAll(".requests-table").forEach((table) => {
        const rows = [...table.querySelectorAll("tbody tr")];
        const filtered = rows.filter((row) => {
          if (status && row.dataset.status !== status) return false;
          if (code && row.dataset.code !== code) return false;
          if (!q) return true;
          return String(row.dataset.search || "").toLowerCase().includes(q);
        });
        const wrapper = table.closest(".requests-wrap");
        let page = Number(table.dataset.page || 1);
        const maxPage = Math.max(1, Math.ceil(filtered.length / pageSize));
        page = Math.min(Math.max(1, page), maxPage);
        table.dataset.page = String(page);
        const start = (page - 1) * pageSize;
        const visible = new Set(filtered.slice(start, start + pageSize));
        rows.forEach((row) => { row.style.display = visible.has(row) ? "" : "none"; });
        if (wrapper) wrapper.style.display = filtered.length ? "" : "none";
        let pager = wrapper ? wrapper.nextElementSibling : null;
        if (!pager || !pager.classList.contains("requests-pager")) {
          pager = document.createElement("div");
          pager.className = "requests-pager";
          if (wrapper) wrapper.after(pager);
        }
        const from = filtered.length ? start + 1 : 0;
        const to = Math.min(start + pageSize, filtered.length);
        pager.innerHTML = `
          <span>${filtered.length ? `${from}–${to} sur ${filtered.length}` : "0 résultat"}</span>
          <div class="requests-pager-buttons">
            <button type="button" class="btn btn-small" data-req-prev ${page <= 1 ? "disabled" : ""}>‹</button>
            <span>${page}/${maxPage}</span>
            <button type="button" class="btn btn-small" data-req-next ${page >= maxPage ? "disabled" : ""}>›</button>
          </div>`;
        const prev = pager.querySelector("[data-req-prev]");
        const next = pager.querySelector("[data-req-next]");
        if (prev) prev.addEventListener("click", () => {
          table.dataset.page = String(Math.max(1, page - 1));
          applyRequestFilters();
        });
        if (next) next.addEventListener("click", () => {
          table.dataset.page = String(Math.min(maxPage, page + 1));
          applyRequestFilters();
        });
      });
    };
    const resetRequestPages = () => {
      document.querySelectorAll(".requests-table").forEach((table) => { table.dataset.page = "1"; });
      applyRequestFilters();
    };
    $("#requests-search").addEventListener("input", resetRequestPages);
    $("#requests-status-filter").addEventListener("change", resetRequestPages);
    $("#requests-code-filter").addEventListener("change", resetRequestPages);
    $("#requests-page-size").addEventListener("change", resetRequestPages);
    applyRequestFilters();

    const rowsById = new Map();
    [mine, toValidate, perimeter, all].forEach((list) => {
      (list || []).forEach((r) => rowsById.set(r.id, r));
    });

    const cancelDecision = async (id, action) => {
      let comment = "";
      if (action === "cancel") {
        if (!confirm("Annuler cette demande ?")) return;
      } else if (action === "cancel-request") {
        const value = prompt("Motif de la demande d'annulation :", "");
        if (value === null) return;
        comment = value;
      }
      try {
        await api(`/api/requests/${id}/${action}`, {
          method: "POST",
          body: JSON.stringify({ comment }),
        });
        toast(action === "cancel-request"
          ? "Demande d'annulation envoyée"
          : "Demande annulée");
        refreshRequestBadge();
        viewRequests();
      } catch (err) {
        toast(err.message, true);
      }
    };

    $$("[data-req-approve]").forEach((b) => b.addEventListener("click", () => openDecisionModal(rowsById.get(Number(b.dataset.reqApprove)), "approve", b.dataset.reqStatus)));
    $$("[data-req-refuse]").forEach((b) => b.addEventListener("click", () => openDecisionModal(rowsById.get(Number(b.dataset.reqRefuse)), "refuse", b.dataset.reqStatus)));
    $$("[data-req-cancel]").forEach((b) => b.addEventListener("click", () => cancelDecision(Number(b.dataset.reqCancel), "cancel")));
    $$("[data-req-cancel-request]").forEach((b) => b.addEventListener("click", () => cancelDecision(Number(b.dataset.reqCancelRequest), "cancel-request")));
    $$("[data-req-attach]").forEach((b) => b.addEventListener("click", () => downloadAttachment(Number(b.dataset.reqAttach), b.dataset.attachName)));
    refreshRequestBadge();
  } catch (err) {
    c.innerHTML = `<h1>${pageTitle} — ${year}</h1><div class="form-error">${esc(err.message)}</div>`;
  }
}

async function downloadAttachment(id, name) {
  try {
    const headers = {};
    const res = await fetch(`/api/requests/${id}/attachment`, { headers });
    if (!res.ok) {
      let data = null;
      try { data = await res.json(); } catch (_) { data = null; }
      throw new Error((data && data.error) || "Téléchargement impossible");
    }
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = name || "piece-jointe";
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  } catch (err) {
    toast(err.message, true);
  }
}

let pendingDecision = null;

function openDecisionModal(row, action, status) {
  if (!row) return;
  const isCancel = status === "annulation_demandee";
  const isApprove = action === "approve";
  $("#decision-title").textContent = isApprove
    ? (isCancel ? "Valider l'annulation" : "Valider la demande")
    : (isCancel ? "Refuser l'annulation" : "Refuser la demande");
  $("#decision-summary").innerHTML = `
    <div class="decision-line"><span>Agent</span><b>${esc(row.agent_nom || "")}</b></div>
    <div class="decision-line"><span>Code</span><b>${esc(row.code || "")}</b></div>
    <div class="decision-line"><span>Période</span><b>${esc(requestPeriodLabel(row))}</b></div>
    <div class="decision-line"><span>Quantité</span><b>${esc(requestQuantityLabel(row))}</b></div>
    <div class="decision-line"><span>Statut</span><b>${isCancel ? "Annulation demandée" : "En attente"}</b></div>
  `;
  const commentLabel = $("#decision-comment-label");
  commentLabel.firstChild.textContent = isApprove
    ? "Commentaire (facultatif)"
    : "Motif du refus (facultatif)";
  $("#decision-comment").value = "";
  const err = $("#decision-error");
  err.textContent = "";
  err.classList.add("hidden");
  const submit = $("#decision-submit");
  submit.textContent = isApprove ? "Valider" : "Refuser";
  submit.classList.toggle("btn-primary", isApprove);
  submit.classList.toggle("btn-danger", !isApprove);
  pendingDecision = {
    id: row.id,
    endpoint: isCancel ? (isApprove ? "cancel-approve" : "cancel-refuse") : action,
    isCancel,
    action,
  };
  $("#decision-modal").classList.remove("hidden");
  $("#decision-comment").focus();
}

async function submitDecision() {
  if (!pendingDecision) return;
  const decision = pendingDecision;
  const comment = $("#decision-comment").value.trim();
  try {
    await api(`/api/requests/${decision.id}/${decision.endpoint}`, {
      method: "POST",
      body: JSON.stringify({ comment }),
    });
    $("#decision-modal").classList.add("hidden");
    pendingDecision = null;
    const message = decision.action === "approve"
      ? (decision.isCancel ? "Annulation validée" : "Demande validée")
      : (decision.isCancel ? "Annulation refusée" : "Demande refusée");
    toast(message);
    refreshRequestBadge();
    viewRequests();
  } catch (err) {
    const el = $("#decision-error");
    el.textContent = err.message;
    el.classList.remove("hidden");
  }
}

$("#decision-cancel").addEventListener("click", () => {
  $("#decision-modal").classList.add("hidden");
  pendingDecision = null;
});
$("#decision-submit").addEventListener("click", submitDecision);
$("#decision-modal").addEventListener("mousedown", (e) => {
  if (e.target.id === "decision-modal") {
    $("#decision-modal").classList.add("hidden");
    pendingDecision = null;
  }
});

function openOwnerModal() {
  const f = state.fiche;
  if (!f || !f.can_change_owner) return;
  const options = (f.owner_options || []).map((u) =>
    `<option value="${u.id}" ${String(u.id) === String(f.user_id) ? "selected" : ""}>${esc(u.nom || u.login)} (${esc(u.login)}) — ${esc(ROLE_LABELS[u.role] || u.role)}</option>`
  ).join("");
  if (!options) return;
  $("#owner-fiche-name").textContent = agentName(f);
  $("#owner-select").innerHTML = options;
  $("#owner-select").value = String(f.user_id);
  const err = $("#owner-error");
  err.textContent = "";
  err.classList.add("hidden");
  $("#owner-modal").classList.remove("hidden");
  $("#owner-select").focus();
}

async function submitOwnerChange() {
  const f = state.fiche;
  if (!f) return;
  const newOwner = Number($("#owner-select").value);
  if (!newOwner || newOwner === f.user_id) {
    $("#owner-modal").classList.add("hidden");
    return;
  }
  try {
    clearTimeout(state.saveTimer);
    state.saveTimer = null;
    await saveFiche();
    await api("/api/agents/" + f.id, {
      method: "PUT",
      body: JSON.stringify({ owner_id: newOwner }),
    });
    $("#owner-modal").classList.add("hidden");
    toast("Propriétaire de la fiche modifié");
    viewFiche(f.id);
  } catch (err) {
    const el = $("#owner-error");
    el.textContent = err.message;
    el.classList.remove("hidden");
  }
}

$("#owner-cancel").addEventListener("click", () => $("#owner-modal").classList.add("hidden"));
$("#owner-submit").addEventListener("click", submitOwnerChange);
$("#owner-modal").addEventListener("mousedown", (e) => {
  if (e.target.id === "owner-modal") $("#owner-modal").classList.add("hidden");
});

/* ==========================================================================
   Planning mensuel (absences de toutes les fiches)
   ========================================================================== */
const DOW_SHORT = ["Dim", "Lun", "Mar", "Mer", "Jeu", "Ven", "Sam"];

async function viewPlanning() {
  if (!state.user) return;
  const year = state.year || defaultYear();
  if (!state.planningMonth) {
    const now = new Date();
    state.planningMonth = year === now.getFullYear() ? now.getMonth() + 1 : 1;
  }
  if (state.planningFilter === null) state.planningFilter = canViewPlanningTeam() ? "all" : "me";

  // Liste des utilisateurs du périmètre pour le filtre
  let users = [];
  if (canViewPlanningTeam()) {
    try { users = await api("/api/scope-users"); } catch (_) { users = []; }
  }
  state.planningUsers = users;

  const c = $("#content");
  const allLabel = state.user.admin
    ? "Toutes les fiches"
    : (userRole(state.user) === "agent" ? "Toutes les fiches de mon service" : "Toutes les fiches de mon périmètre");
  const filterSelect = canViewPlanningTeam() ? `
      <label class="inline plan-filter">Utilisateur
        <select id="plan-user">
          <option value="all" ${state.planningFilter === "all" ? "selected" : ""}>${allLabel}</option>
          <option value="me" ${state.planningFilter === "me" ? "selected" : ""}>Mes fiches</option>
          ${users.filter((u) => u.id !== state.user.id && userRole(state.user) !== "agent").map((u) => {
            const nom = u.nom || u.login;
            const label = u.nom && u.nom !== u.login ? `${esc(u.nom)} (${esc(u.login)})` : esc(nom);
            return `<option value="${u.id}" ${String(state.planningFilter) === String(u.id) ? "selected" : ""}>${label}</option>`;
          }).join("")}
        </select>
      </label>` : "";

  c.innerHTML = `
    <h1>Planning mensuel</h1>
    <div class="planning-toolbar">
      <button class="btn btn-small" id="plan-prev" title="Mois précédent">‹</button>
      <select id="plan-month">${MONTHS.map((m, i) => `<option value="${i + 1}" ${i + 1 === state.planningMonth ? "selected" : ""}>${m}</option>`).join("")}</select>
      <button class="btn btn-small" id="plan-next" title="Mois suivant">›</button>
      <span class="plan-year">${year}</span>
      ${filterSelect}
      <button class="btn" id="plan-print">Imprimer</button>
      <div class="plan-summary-line" id="plan-summary-line"></div>
    </div>
    <div id="plan-body"><p>Chargement…</p></div>`;

  $("#plan-prev").addEventListener("click", () => {
    state.planningMonth = state.planningMonth > 1 ? state.planningMonth - 1 : 12;
    const sel = $("#plan-month");
    if (sel) sel.value = String(state.planningMonth);
    loadPlanning();
  });
  $("#plan-next").addEventListener("click", () => {
    state.planningMonth = state.planningMonth < 12 ? state.planningMonth + 1 : 1;
    const sel = $("#plan-month");
    if (sel) sel.value = String(state.planningMonth);
    loadPlanning();
  });
  $("#plan-month").addEventListener("change", (e) => {
    state.planningMonth = Number(e.target.value);
    loadPlanning();
  });
  const userSel = $("#plan-user");
  if (userSel) userSel.addEventListener("change", (e) => {
    const v = e.target.value;
    state.planningFilter = (v === "all" || v === "me") ? v : Number(v);
    loadPlanning();
  });

  $("#plan-print").addEventListener("click", () => window.print());

  loadPlanning();
}

let planningReq = 0;
async function loadPlanning() {
  const req = ++planningReq;
  const body = $("#plan-body");
  if (!body) return;
  body.innerHTML = "<p>Chargement…</p>";
  try {
    const year = state.year || defaultYear();
    let qs = `year=${year}&month=${state.planningMonth}`;
    if (canViewPlanningTeam()) {
      if (state.planningFilter === "all") qs += "&all=1";
      else if (state.planningFilter !== "me") qs += `&user_id=${state.planningFilter}`;
    }
    const data = await api(`/api/planning?${qs}`);
    if (req !== planningReq) return; // une requête plus récente a pris le relais
    renderPlanning(data);
  } catch (err) {
    if (req !== planningReq) return;
    body.innerHTML = `<div class="form-error">${esc(err.message)}</div>`;
  }
}

function renderPlanning(data) {
  const body = $("#plan-body");
  if (!body) return;
  const s = state.settings;
  const year = data.year;
  const month = data.month;
  const agents = data.agents || [];
  const nd = daysInMonth(month, year);
  const feries = new Set((s.jours_feries || []).map((x) => String(x[0])));
  const colors = codeColorMap();

  if (!agents.length) {
    body.innerHTML = `<p>Aucune fiche à afficher pour ce mois.</p>`;
    const line = $("#plan-summary-line");
    if (line) line.textContent = "";
    return;
  }

  const dayCls = (d) => {
    const iso = `${year}-${String(month).padStart(2, "0")}-${String(d).padStart(2, "0")}`;
    const dow = dayOfWeek(month, d, year);
    const base = feries.has(iso) ? "ferie" : (dow === 0 || dow === 6 ? "we" : "");
    return { cls: base, vac: vacancesLabel(iso) };
  };

  let head = `<th class="plan-agent">Agent</th>`;
  for (let d = 1; d <= nd; d++) {
    const dow = dayOfWeek(month, d, year);
    const dc = dayCls(d);
    const classes = (dc.cls + (dc.vac ? " vacances" : "")).trim();
    head += `<th class="plan-day ${classes}"${dc.vac ? ` title="${esc(dc.vac)}"` : ""}><span class="dow">${DOW_SHORT[dow]}</span><span class="num">${d}</span></th>`;
  }
  head += `<th class="plan-total">Total</th>`;

  const styleFor = (code) => {
    if (!code) return "";
    const hex = colors[code] || "F2F2F2";
    return `background:${cssColor(hex)};color:${textColorFor(hex)}`;
  };
  const shadeCls = (d) => {
    const dc = dayCls(d);
    return dc.cls ? "shade-" + dc.cls : "";
  };

  let grandHalves = 0;
  const agentRow = (a) => {
    const cells = a.cells || {};
    const pending = a.pending || {};
    const hourly = a.hourly || {};
    const hourNote = (key) => {
      const items = hourly[String(key)] || [];
      if (!items.length) return "";
      const total = items.reduce((sum, it) => sum + Number(it.hours || 0), 0);
      const codes = [...new Set(items.map((it) => it.code))].join("/");
      const title = items.map((it) => `${it.start_time}-${it.end_time} ${it.code} (${fmtHours(it.hours)})`).join("\n");
      return `<div class="plan-hour-note" title="${esc(title)}">${esc(codes)} ${fmtHours(total)}</div>`;
    };
    let totalHalves = 0;
    let tds = "";
    for (let d = 1; d <= nd; d++) {
      const base = month * 1000 + d * 10;
      const c0 = cells[String(base)] || "";
      const c1 = cells[String(base + 1)] || "";
      const p0 = pending[String(base)] || "";
      const p1 = pending[String(base + 1)] || "";
      const n0 = hourNote(base);
      const n1 = hourNote(base + 1);
      if (c0) totalHalves++;
      if (c1) totalHalves++;
      const shade = shadeCls(d);
      if (c0 && c0 === c1) {
        tds += `<td class="plan-cell"><div class="full" style="${styleFor(c0)}">${esc(c0)}</div></td>`;
      } else if (p0 && p0 === p1) {
        tds += `<td class="plan-cell"><div class="full pending" style="${styleFor(p0)}">${esc(p0)}</div></td>`;
      } else if (!c0 && !c1 && !p0 && !p1 && !n0 && !n1) {
        tds += `<td class="plan-cell"><div class="full ${shade}"></div></td>`;
      } else if (!c0 && !c1 && !p0 && !p1) {
        const h0 = n0 ? `<div class="half">${n0}</div>` : `<div class="half ${shade}"></div>`;
        const h1 = n1 ? `<div class="half">${n1}</div>` : `<div class="half ${shade}"></div>`;
        tds += `<td class="plan-cell">${h0}${h1}</td>`;
      } else {
        const h0 = c0 ? `<div class="half" style="${styleFor(c0)}">${esc(c0)}</div>`
          : (p0 ? `<div class="half pending" style="${styleFor(p0)}">${esc(p0)}</div>`
            : (n0 ? `<div class="half">${n0}</div>` : `<div class="half ${shade}"></div>`));
        const h1 = c1 ? `<div class="half" style="${styleFor(c1)}">${esc(c1)}</div>`
          : (p1 ? `<div class="half pending" style="${styleFor(p1)}">${esc(p1)}</div>`
            : (n1 ? `<div class="half">${n1}</div>` : `<div class="half ${shade}"></div>`));
        tds += `<td class="plan-cell">${h0}${h1}</td>`;
      }
    }
    grandHalves += totalHalves;
    const hourlyDays = Object.values(hourly).flat()
      .reduce((sum, it) => sum + Number(it.hours || 0), 0) / 7;
    const label = `${esc(agentName(a))}${a.is_manager ? ` <span class="manager-tag">(Responsable)</span>` : ""}`;
    return `<tr class="${a.is_manager ? "plan-manager" : ""}">
      <th class="plan-agent">${userRole(state.user) === "agent" && a.agent_user_id !== state.user.id
        ? label
        : `<a href="#/agent/${a.id}">${label}</a>`}</th>
      ${tds}
      <td class="plan-total">${fmt(totalHalves / 2 + hourlyDays)}</td>
    </tr>`;
  };

  // Regroupement hiérarchique (uniquement pour « toutes les fiches de mon périmètre »)
  const grouped = canViewPlanningTeam() && state.planningFilter === "all";
  let rows = "";
  if (grouped) {
    const scopeUsers = state.planningUsers || [];
    const scopeIds = new Set(scopeUsers.map((u) => u.id));
    const agentsByUser = {};
    agents.forEach((a) => { (agentsByUser[a.user_id] = agentsByUser[a.user_id] || []).push(a); });
    Object.values(agentsByUser).forEach((list) => list.sort((a, b) => {
      const ma = a.is_manager ? 1 : 0;
      const mb = b.is_manager ? 1 : 0;
      if (ma !== mb) return mb - ma;
      return String(agentName(a) || "").localeCompare(String(agentName(b) || ""), "fr");
    }));
    const kids = {};
    scopeUsers.forEach((u) => {
      if (u.parent_id != null) (kids[u.parent_id] = kids[u.parent_id] || []).push(u);
    });
    let roots;
    if (state.user.admin) {
      roots = scopeUsers.filter((u) => u.parent_id == null || !scopeIds.has(u.parent_id));
    } else if (userRole(state.user) === "agent") {
      roots = scopeUsers.filter((u) => u.parent_id == null || !scopeIds.has(u.parent_id));
      if (!roots.length) roots = scopeUsers.filter((u) => u.id === state.user.parent_id);
      if (!roots.length) roots = scopeUsers.filter((u) => u.id === state.user.id);
    } else {
      roots = scopeUsers.filter((u) => u.id === state.user.id);
    }
    roots.sort(byRoleName);
    const subtreeHasAgents = (u) => {
      if ((agentsByUser[u.id] || []).length) return true;
      return (kids[u.id] || []).some((c) => subtreeHasAgents(c));
    };
    const rendered = new Set();
    const renderNode = (u, level) => {
      if (rendered.has(u.id)) return;
      rendered.add(u.id);
      const own = agentsByUser[u.id] || [];
      const children = sortHierarchyChildren(u, kids[u.id] || []);
      if (own.length || children.some((c) => subtreeHasAgents(c))) {
        const roleLabel = ROLE_LABELS[userRole(u)] || userRole(u);
        const display = (u.nom && u.nom !== roleLabel) ? u.nom : u.login;
        const label = esc(display);
        rows += `<tr class="plan-group level-${Math.min(level, 3)} role-${userRole(u)}"><td colspan="${nd + 2}">${label}</td></tr>`;
        own.forEach((a) => { rows += agentRow(a); });
        children.forEach((c) => renderNode(c, level + 1));
      }
    };
    roots.forEach((u) => renderNode(u, 0));
    // Utilisateurs du périmètre non atteints (orphelins) : affichés à la racine.
    scopeUsers.filter((u) => !rendered.has(u.id)).sort(byRoleName).forEach((u) => renderNode(u, 0));
  } else {
    agents.forEach((a) => { rows += agentRow(a); });
  }

  const printHead = `
    <div class="print-head">
      <div class="print-title">Planning ${MONTHS[month - 1]} ${year}</div>
      <div class="print-sub">${agents.length} fiche(s) · ${fmt(grandHalves / 2)} jour(s) d'absence</div>
    </div>`;
  body.innerHTML = `${printHead}
    <div class="planning-wrap">
      <table class="planning-table">
        <thead><tr>${head}</tr></thead>
        <tbody>${rows}</tbody>
      </table>
    </div>
    <div class="plan-legend">
      <span><i class="sw-we"></i>Week-end</span>
      <span><i class="sw-ferie"></i>Jour férié</span>
      <span><i class="sw-vac"></i>Vacances scolaires (zone C)</span>
    </div>`;

  const line = $("#plan-summary-line");
  if (line) line.textContent = `${agents.length} fiche(s) · ${fmt(grandHalves / 2)} jour(s) d'absence`;
}

/* ==========================================================================
   Fiche agent
   ========================================================================== */
async function viewFiche(id) {
  const c = $("#content");
  c.innerHTML = "<p>Chargement…</p>";
  try {
    state.fiche = await api("/api/agents/" + id);
  } catch (err) {
    c.innerHTML = `<div class="form-error">${esc(err.message)}</div>`;
    if (/introuvable/i.test(err.message)) dropTab(id);
    return;
  }
  try {
    state.ficheValidators = await api("/api/validators?agent_id=" + id);
  } catch (_) {
    state.ficheValidators = [];
  }
  upsertTab(id, agentName(state.fiche));
  state.readOnly = !canEditFiche(state.fiche);
  state.requestMode = !!(state.fiche.can_request && !state.fiche.can_edit_cells);
  state.specialRequestMode = !!state.fiche.can_special_request;
  renderFiche();
  scheduleCompute();
}

function optionList(values, current, allowEmpty) {
  const opts = (values || []).map((v) =>
    `<option value="${esc(v)}" ${String(v) === String(current) ? "selected" : ""}>${esc(v)}</option>`);
  if (allowEmpty) {
    const empty = (current === "" || current === null || current === undefined) ? " selected" : "";
    return `<option value=""${empty}></option>` + opts.join("");
  }
  return opts.join("");
}

function frDate(iso) {
  if (!iso) return "—";
  const parts = String(iso).slice(0, 10).split("-");
  return parts.length === 3 ? `${parts[2]}/${parts[1]}/${parts[0]}` : String(iso);
}

function addDays(iso, days) {
  const parts = String(iso).slice(0, 10).split("-").map(Number);
  const d = new Date(parts[0], parts[1] - 1, parts[2]);
  d.setDate(d.getDate() + Number(days));
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

function renderFiche() {
  const f = state.fiche;
  const p = f.params;
  const s = state.settings;
  const c = $("#content");

  const validators = state.ficheValidators || [];
  const validatorOptions = validators.map((v) =>
    `<option value="${v.id}" ${String(v.id) === String(f.validator_id) ? "selected" : ""}>${esc(v.nom || v.login)} (${esc(v.login)}) — ${esc(ROLE_LABELS[v.role] || v.role)}</option>`
  ).join("");
  const ro = !!state.readOnly;
  const dis = ro ? " disabled" : "";
  const hasRequestActions = !!(state.requestMode || state.specialRequestMode);
  const isAgentView = userRole(state.user) === "agent";
  const year = f.year || (s.general ? s.general.year : new Date().getFullYear());
  const yearStart = `${year}-01-01`;
  const yearEnd = `${year}-12-31`;

  const displayPeriods = () => {
    if (f.periods && f.periods.length) return f.periods;
    return [{
      start: p.date_arrivee || yearStart,
      end: p.date_depart || yearEnd,
      penibilite: p.penibilite || "",
      duree_hebdo: p.duree_hebdo || "",
      quotite: p.quotite || "",
      jours_hebdo: p.jours_hebdo,
    }];
  };
  const materializePeriods = () => {
    if (!f.periods || !f.periods.length) {
      f.periods = displayPeriods().map((x) => ({ ...x }));
    }
    return f.periods;
  };
  const renderPeriodsEditor = () => {
    const el = $("#periods-editor");
    if (!el) return;
    const periods = displayPeriods();
    const disPeriod = ro ? " disabled" : "";
    const rows = periods.map((per, i) => {
      const dureesPer = (s.penibilites_durees && s.penibilites_durees[per.penibilite]) || s.durees || [];
      return `<tr data-period-index="${i}">
        <td>${frDate(per.start)}</td>
        <td>${frDate(per.end)}</td>
        <td><select data-pf="penibilite"${disPeriod}>${optionList((s.penibilites || []).map((x) => x.name), per.penibilite, true)}</select></td>
        <td><select data-pf="duree_hebdo"${disPeriod}>${optionList(dureesPer, per.duree_hebdo, true)}</select></td>
        <td><select data-pf="quotite"${disPeriod}>${optionList(s.quotites, per.quotite, true)}</select></td>
        <td><select data-pf="jours_hebdo"${disPeriod}>${optionList(s.jours_hebdo, per.jours_hebdo, true)}</select></td>
        <td>${i > 0 && !ro ? `<button class="btn btn-small btn-danger" data-period-del="${i}">Supprimer</button>` : ""}</td>
      </tr>`;
    }).join("");
    const minAdd = periods.length ? addDays(periods[0].start, 1) : "";
    const maxAdd = periods.length ? periods[periods.length - 1].end : "";
    el.innerHTML = `
      ${ro ? "" : `<div class="period-add">
        <label>Date d'effet du changement
          <input type="date" id="period-add-date" min="${minAdd}" max="${maxAdd}">
        </label>
        <button class="btn btn-small" id="period-add">+ Ajouter un changement</button>
        <span id="period-error" class="form-error hidden"></span>
      </div>`}
      <div class="table-wrap">
        <table class="data periods-table">
          <thead><tr>
            <th>Début</th><th>Fin</th><th>Pénibilité</th><th>Durée</th>
            <th>Quotité</th><th>Jours/sem.</th><th></th>
          </tr></thead>
          <tbody>${rows}</tbody>
        </table>
      </div>`;
    if (ro) return;

    $$("#periods-editor tr[data-period-index]").forEach((tr) => {
      const index = Number(tr.dataset.periodIndex);
      tr.querySelectorAll("[data-pf]").forEach((input) => {
        input.addEventListener("change", () => {
          const list = materializePeriods();
          const field = input.dataset.pf;
          let value = input.value;
          if (field === "jours_hebdo") value = value === "" ? null : Number(value);
          list[index][field] = value;
          if (field === "penibilite") {
            const options = (s.penibilites_durees && s.penibilites_durees[value]) || s.durees || [];
            if (!options.includes(list[index].duree_hebdo)) {
              list[index].duree_hebdo = options.length ? options[0] : "";
            }
          }
          renderPeriodsEditor();
          scheduleSave();
          scheduleCompute();
        });
      });
    });

    $$("#periods-editor [data-period-del]").forEach((btn) => {
      btn.addEventListener("click", () => {
        const index = Number(btn.dataset.periodDel);
        const list = materializePeriods();
        if (index <= 0 || index >= list.length) return;
        list[index - 1].end = list[index].end;
        list.splice(index, 1);
        renderPeriodsEditor();
        scheduleSave();
        scheduleCompute();
      });
    });

    const addBtn = $("#period-add");
    if (addBtn) {
      addBtn.addEventListener("click", () => {
        const dateInput = $("#period-add-date");
        const err = $("#period-error");
        err.classList.add("hidden");
        err.textContent = "";
        const value = dateInput.value;
        if (!value) {
          err.textContent = "Saisissez une date d'effet.";
          err.classList.remove("hidden");
          return;
        }
        const list = materializePeriods();
        const index = list.findIndex((per) => per.start < value && value <= per.end);
        if (index === -1) {
          err.textContent = "La date doit être comprise dans une période existante, après son début.";
          err.classList.remove("hidden");
          return;
        }
        const old = list[index];
        const next = {
          start: value,
          end: old.end,
          penibilite: old.penibilite,
          duree_hebdo: old.duree_hebdo,
          quotite: old.quotite,
          jours_hebdo: old.jours_hebdo,
        };
        old.end = addDays(value, -1);
        list.splice(index + 1, 0, next);
        renderPeriodsEditor();
        scheduleSave();
        scheduleCompute();
      });
    }
  };

  c.innerHTML = `
    <div class="fiche-header${isAgentView ? " agent-fiche-header" : ""}">
      <a href="${isAgentView ? "#/dashboard" : "#/agents"}" class="btn btn-ghost">← Retour</a>
      <label class="fiche-name-field">Nom
        <input type="text" id="f-nom" value="${esc(f.nom)}"${dis}></label>
      <label class="fiche-name-field">Prénom
        <input type="text" id="f-prenom" value="${esc(f.prenom || "")}"${dis}></label>
      <span class="fiche-year">${f.year || ""}</span>
      ${f.user_id !== state.user.id ? `<span class="fiche-owner">Propriétaire : ${esc(f.proprietaire || "—")}</span>` : ""}
      <span id="save-ind" style="color:var(--muted);font-size:12px"></span>
      <button class="btn" id="f-print">Imprimer</button>
      ${ro ? "" : `<button class="btn btn-danger" id="f-del">Supprimer</button>`}
      ${f.can_change_owner && (f.owner_options || []).length ? `<button class="btn btn-ghost btn-small owner-change-btn" id="btn-change-owner" title="Changer le propriétaire de la fiche">Changer le propriétaire</button>` : ""}
    </div>
    ${ro && !state.requestMode ? `<div class="readonly-banner">Fiche en lecture seule — propriétaire : <b>${esc(f.proprietaire || "—")}</b></div>` : ""}
    <div id="f-errors"></div>
    <div id="rch-alert" class="no-print"></div>

    <div class="fiche-meta-row no-print${hasRequestActions ? " has-request-actions" : ""}${isAgentView ? " agent-only-actions" : ""}">
      <div class="card agent-info-card">
        <h3>Compte agent</h3>
        ${!f.email ? `<div class="agent-warning">E-mail à renseigner : il est obligatoire pour cette fiche.</div>` : ""}
        <div class="params-grid">
          <label>E-mail de l'agent
            <input type="email" id="p-email" value="${esc(f.email || "")}"${dis}></label>
          <label>Matricule
            <input type="text" id="p-matricule" maxlength="20" value="${esc(f.matricule || "")}"${dis}></label>
          <label>Compte valideur
            <select id="p-validator"${dis}>${validatorOptions}</select></label>
        </div>
        <label class="inline manager-check">
          <input type="checkbox" id="p-manager" ${f.is_manager ? "checked" : ""}${dis}> Responsable de l'unité
        </label>
      </div>

      <div class="card reports-card">
        <h3>Reports annuels</h3>
        <div class="params-grid">
          <label><span>Reliquat (jours)</span>
            <input type="number" step="0.5" min="0" max="100" id="p-rel" value="${esc(p.reliquat)}"${dis}></label>
          <label><span>Solde CET (jours)</span>
            <input type="number" step="0.5" min="0" max="70" id="p-cet" value="${esc(p.solde_cet)}"${dis}></label>
        </div>
      </div>

      ${hasRequestActions ? `<div class="card request-actions-card">
        <h3>Gestion des heures</h3>
        <div class="request-banner-actions hour-actions">
          <button type="button" class="btn btn-small hour-action hour-action-cassage" id="req-cassage-btn">Casser un CA / RTT en heures</button>
          <button type="button" class="btn btn-small hour-action hour-action-heures" id="req-heures-btn">Poser des heures (CAH / RTTH / RCH)</button>
          <button type="button" class="btn btn-small hour-action hour-action-recup" id="req-recup-btn">Déclarer des heures de récupération (RCH)</button>
          <button type="button" class="btn btn-small btn-ghost hour-action-solde" id="req-hours-detail-btn">Mon solde d'heures</button>
        </div>
      </div>` : ""}
    </div>

    <div class="fiche-layout">
      <div class="card">
        <h3>Calendrier ${f.year || (s.general ? s.general.year : "")}<span class="no-print"> — ${state.requestMode ? "sélectionnez les demi-journées puis choisissez le code pour envoyer une demande" : (ro ? "lecture seule" : "cliquez ou glissez pour sélectionner une ou plusieurs demi-journées")}</span></h3>
          <div class="calendar-wrap"><div class="calendar" id="calendar"></div></div>
          <div class="legend" id="legend"></div>
      </div>

      <div class="soldes-panel" id="soldes">
        <div class="card"><p>Calcul en cours…</p></div>
      </div>
    </div>

    ${isAgentView ? `<div id="agent-actions-slot" class="agent-actions-slot no-print"></div>` : ""}

    <div class="card periods-card no-print${isAgentView ? " agent-hidden" : ""}">
      <h3>Paramètres et périodes</h3>
      <div class="periods-layout">
        <div>
          <h4>Arrivée et/ou départ</h4>
          <p class="muted"><b>À renseigner uniquement en cas d'arrivée et/ou de départ en cours d'année.</b></p>
          <div class="period-dates">
            <label>Date d'arrivée
              <input type="date" id="p-arr" value="${esc(p.date_arrivee || "")}"${dis}></label>
            <label>Date de départ
              <input type="date" id="p-dep" value="${esc(p.date_depart || "")}"${dis}></label>
          </div>
        </div>
        <div>
          <h4>Périodes de paramètres</h4>
          <p class="muted">Les droits sont calculés période par période. Le reliquat et le solde CET restent annuels.</p>
          <div id="periods-editor"></div>
        </div>
      </div>
    </div>`;

  if (isAgentView && hasRequestActions) {
    const slot = $("#agent-actions-slot");
    const requestCard = document.querySelector(".fiche-meta-row .request-actions-card");
    if (slot && requestCard) slot.appendChild(requestCard);
  }

  // --- liaisons des champs (uniquement si la fiche est modifiable) ---
  if (!ro) {
  const updateTabName = () => {
    const t = state.tabs.find((x) => x.id === f.id);
    if (t) {
      t.nom = agentName(f) || "Fiche " + f.id;
      persistTabs();
      renderTabs();
    }
  };
  const upperInput = (e) => {
    const pos = e.target.selectionStart;
    e.target.value = e.target.value.toUpperCase();
    e.target.setSelectionRange(pos, pos);
  };
  $("#f-nom").addEventListener("input", (e) => {
    upperInput(e);
    f.nom = e.target.value;
    updateTabName();
    scheduleSave();
  });
  $("#f-prenom").addEventListener("input", (e) => {
    upperInput(e);
    f.prenom = e.target.value;
    updateTabName();
    scheduleSave();
  });
  $("#p-email").addEventListener("input", (e) => {
    f.email = e.target.value.trim();
    scheduleSave();
  });
  $("#p-matricule").addEventListener("input", (e) => {
    f.matricule = e.target.value.trim();
    scheduleSave();
  });
  const ownerBtn = $("#btn-change-owner");
  if (ownerBtn) ownerBtn.addEventListener("click", openOwnerModal);
  $("#p-validator").addEventListener("change", (e) => {
    f.validator_id = e.target.value ? Number(e.target.value) : null;
    scheduleSave();
  });
  $("#p-manager").addEventListener("change", (e) => {
    f.is_manager = e.target.checked ? 1 : 0;
    scheduleSave();
  });
  $("#f-del").addEventListener("click", async () => {
    if (!confirm("Supprimer définitivement cette fiche ?")) return;
    await api("/api/agents/" + f.id, { method: "DELETE" });
    dropTab(f.id);
    toast("Fiche supprimée");
    location.hash = "#/agents";
  });

  const bind = (sel, key, transform) => {
    $(sel).addEventListener("change", (e) => {
      p[key] = transform ? transform(e.target.value) : e.target.value;
      scheduleSave();
      scheduleCompute();
    });
  };
  bind("#p-rel", "reliquat", (v) => (v === "" ? "" : Number(v)));
  bind("#p-cet", "solde_cet", (v) => (v === "" ? "" : Number(v)));

  $("#p-arr").addEventListener("change", (e) => {
    p.date_arrivee = e.target.value;
    if (f.periods && f.periods.length) {
      f.periods[0].start = p.date_arrivee || yearStart;
    }
    renderPeriodsEditor();
    scheduleSave();
    scheduleCompute();
  });
  $("#p-dep").addEventListener("change", (e) => {
    p.date_depart = e.target.value;
    if (f.periods && f.periods.length) {
      f.periods[f.periods.length - 1].end = p.date_depart || yearEnd;
    }
    renderPeriodsEditor();
    scheduleSave();
    scheduleCompute();
  });
  }

  renderPeriodsEditor();

  $("#f-print").addEventListener("click", () => window.print());

  const cassageBtn = $("#req-cassage-btn");
  if (cassageBtn) cassageBtn.addEventListener("click", openCassageModal);
  const heuresBtn = $("#req-heures-btn");
  if (heuresBtn) heuresBtn.addEventListener("click", openHeuresModal);
  const recupBtn = $("#req-recup-btn");
  if (recupBtn) recupBtn.addEventListener("click", openRecupModal);
  const hoursDetailBtn = $("#req-hours-detail-btn");
  if (hoursDetailBtn) hoursDetailBtn.addEventListener("click", openHoursDetailModal);

  renderCalendar();
  renderLegend();
}

/* ---------------------------- calendrier ---------------------------- */
function renderCalendar() {
  const f = state.fiche;
  const s = state.settings;
  const year = f.year || (s.general ? s.general.year : 2027);
  const feries = new Set((s.jours_feries || []).map((x) => String(x[0])));
  const cal = $("#calendar");
  if (!cal) return;

  const pad2 = (n) => String(n).padStart(2, "0");
  const dayClass = (m, d) => {
    const iso = `${year}-${pad2(m)}-${pad2(d)}`;
    const dow = dayOfWeek(m, d, year);
    const base = feries.has(iso) ? "ferie" : (dow === 0 || dow === 6 ? "we" : "");
    const vac = vacancesLabel(iso);
    return { cls: (base + (vac ? " vacances" : "")).trim(), vac };
  };

  // En-tête unique des jours 01..31 (ligne 4 du classeur Excel)
  let head = `<tr><th class="cal-year">${year}</th><th class="cal-half-head"></th>`;
  for (let d = 1; d <= 31; d++) head += `<th class="cal-day">${pad2(d)}</th>`;
  head += `</tr>`;

  // Un mois par paire de lignes (Matin / Après-midi), empilés verticalement.
  // Le nom du mois est fusionné sur ses 2 lignes (rowspan), comme B5:B6...
  let body = "";
  MONTHS.forEach((name, mi) => {
    const m = mi + 1;
    const nd = daysInMonth(m, year);
    for (let h = 0; h < 2; h++) {
      body += (h === 0 && mi > 0) ? '<tr class="month-start">' : "<tr>";
      if (h === 0) body += `<th class="cal-month" rowspan="2">${name}</th>`;
      body += `<th class="cal-half">${h === 0 ? "Matin" : "Après-midi"}</th>`;
      // On ne rend que les jours qui existent réellement dans le mois :
      // les 29-31 février, le 31 avril, etc. n'apparaissent pas du tout.
      for (let d = 1; d <= nd; d++) {
        const dc = dayClass(m, d);
        const lineCls = (dc.vac && h === 0) ? " vc-line" : "";
        body += `<td class="cal-cell ${dc.cls}${lineCls}" data-k="${cellKey(m, d, h)}"${dc.vac ? ` title="${esc(dc.vac)}"` : ""}></td>`;
      }
      // Case-fantôme (sans bordure ni fond) uniquement sur la ligne Matin :
      // elle permet à la ligne de séparation de se prolonger jusqu'au 31
      // sans faire apparaître les jours inexistants.
      if (h === 0 && nd < 31) {
        body += `<td class="cal-spacer" colspan="${31 - nd}"></td>`;
      }
      body += "</tr>";
    }
  });

  cal.innerHTML = `<table class="cal-table">
    <thead>${head}</thead>
    <tbody>${body}</tbody>
  </table>`;
  cal.addEventListener("mousedown", onCellMouseDown);
  cal.addEventListener("mouseover", onCellMouseOver);
  paintCalendar();
}

function paintCalendar() {
  const f = state.fiche;
  const codes = codeColorMap();
  const pending = f.pending_cells || {};
  $$("#calendar .cal-cell").forEach((el) => {
    const k = el.dataset.k;
    const code = f.cells[k] || "";
    const pendingCode = pending[k] || "";
    el.classList.remove("pending");
    el.removeAttribute("title");
    if (code) {
      const hex = codes[code] || "F2F2F2";
      el.textContent = code;
      el.style.background = cssColor(hex);
      el.style.color = textColorFor(hex);
    } else if (pendingCode) {
      el.textContent = pendingCode;
      el.style.background = mixColor(codes[pendingCode] || "F2F2F2", 0.22);
      el.style.color = "#4a2118";
      el.classList.add("pending");
      el.title = "Demande en attente : " + pendingCode;
    } else {
      el.textContent = "";
      el.style.background = "";
      el.style.color = "";
    }
  });
  paintHourlyAnnotations();
}

function timeToMinutes(value) {
  if (!value) return null;
  const parts = String(value).split(":");
  if (parts.length < 2) return null;
  const h = Number(parts[0]);
  const m = Number(parts[1]);
  if (!Number.isFinite(h) || !Number.isFinite(m)) return null;
  return h * 60 + m;
}

function paintHourlyAnnotations() {
  const f = state.fiche;
  if (!f) return;
  const map = {};
  (f.hourly || []).forEach((h) => {
    if (String(h.absence_date || "").slice(0, 4) !== String(f.year)) return;
    const start = timeToMinutes(h.start_time);
    const end = timeToMinutes(h.end_time);
    if (start == null || end == null || end <= start) return;
    const noon = 12 * 60;
    const parts = [];
    if (start < noon && Math.min(end, noon) > start) {
      parts.push({ half: 0, hours: (Math.min(end, noon) - start) / 60 });
    }
    if (end > noon && end > Math.max(start, noon)) {
      parts.push({ half: 1, hours: (end - Math.max(start, noon)) / 60 });
    }
    const [y, m, d] = String(h.absence_date).slice(0, 10).split("-").map(Number);
    if (!y || !m || !d) return;
    const base = m * 1000 + d * 10;
    parts.forEach((part) => {
      const key = String(base + part.half);
      const entry = map[key] || (map[key] = { byCode: {}, details: [] });
      entry.byCode[h.code] = (entry.byCode[h.code] || 0) + part.hours;
      entry.details.push(`${h.start_time}–${h.end_time} ${h.code} (${fmtHours(h.hours)})`);
    });
  });
  Object.entries(map).forEach(([key, entry]) => {
    const cell = document.querySelector(`#calendar .cal-cell[data-k="${key}"]`);
    if (!cell) return;
    const label = Object.entries(entry.byCode)
      .map(([code, hours]) => `${code} ${fmtHours(hours)}`)
      .join(" / ");
    const note = document.createElement("span");
    note.className = "cal-hour-note";
    note.textContent = label;
    note.title = entry.details.join("\n");
    cell.appendChild(note);
  });
}

function codeColorMap() {
  const map = {};
  ((state.settings || {}).codes || []).forEach((c) => { map[c.code] = c.color; });
  ((state.compute && state.compute.code_list) || []).forEach((c) => {
    if (!map[c.code]) map[c.code] = c.color;
  });
  const caPrev = state.compute && state.compute.ca26_code;
  if (caPrev && !map[caPrev]) map[caPrev] = "FFFFFF00";
  return map;
}

function codeLibelleMap() {
  const map = {};
  ((state.settings || {}).codes || []).forEach((c) => { map[c.code] = c.libelle; });
  ((state.compute && state.compute.code_list) || []).forEach((c) => {
    if (!map[c.code]) map[c.code] = c.libelle;
  });
  const caPrev = state.compute && state.compute.ca26_code;
  if (caPrev && !map[caPrev]) map[caPrev] = "Report CA année N-1";
  return map;
}

function renderLegend() {
  const el = $("#legend");
  if (!el) return;
  const libs = codeLibelleMap();
  const colors = codeColorMap();
  const codes = currentCodeList().slice();
  // Ajoute les codes déjà utilisés dans la fiche (ex. CA n-1 d'une année
  // précédente) même s'ils ne sont plus disponibles à la demande.
  const used = new Set(Object.values((state.fiche && state.fiche.cells) || {}));
  Object.values((state.fiche && state.fiche.pending_cells) || {}).forEach((c) => used.add(c));
  ((state.fiche && state.fiche.hourly) || []).forEach((h) => used.add(h.code));
  used.forEach((code) => { if (code && !codes.includes(code)) codes.push(code); });
  // Pastilles colorées avec la couleur exacte du classeur Excel (fond plein),
  // comme les cellules du calendrier.
  el.innerHTML = codes.map((code) => {
    const hex = colors[code] || "F2F2F2";
    return `<div class="item" style="background:${cssColor(hex)};border-color:${cssColor(hex)};color:${textColorFor(hex)}">
      <b>${esc(code)}</b> <span>${esc(libs[code] || "")}</span>
    </div>`;
  }).join("") + `
    <div class="item" style="background:var(--weekend);border-color:var(--weekend);color:#6b564b">
      <b>WE</b> <span>Week-end</span></div>
    <div class="item item-ferie">
      <b>Férié</b> <span>Jour férié</span></div>
    <div class="item item-vacances">
      <b>Vac.</b> <span>Vacances scolaires (zone C)</span></div>`;
}

/* Codes proposés : liste S + CA26 si reliquat encore dispo (calcul serveur) */
function currentCodeList() {
  const calc = state.compute;
  if (calc && calc.code_list) return calc.code_list.map((c) => c.code);
  return ((state.settings || {}).codes || []).filter((c) => c.in_s).map((c) => c.code);
}

/* Tous les codes sont demandables (demandes de congés). */
function requestCodeList() {
  const calc = state.compute || {};
  const configured = new Set(((state.settings || {}).codes || []).map((c) => c.code).filter(Boolean));
  const caPrev = calc.ca26_code || null;
  const ordered = ["CA", caPrev, "RTT", "JB", "JS", "MD", "AS", "CET"].filter(Boolean);
  const reliquatDispo = (calc.reliquat_initial || 0) > 0
    && ((calc.counts && calc.counts.ca26) || 0) < (calc.reliquat_initial || 0);
  return ordered.filter((code) => code === caPrev ? reliquatDispo : configured.has(code));
}

/* ---------------------------- pop-up de saisie ---------------------------- */
/* Sélection multiple : un clic ouvre une case, un glisser sélectionne une
   plage de demi-journées. Le code choisi s'applique à toute la sélection. */
let pickerTargets = [];
let selectedCellKeys = [];
let dragStartCell = null;
let dragLastCell = null;
let isDraggingCells = false;

function cellLabel(k) {
  const key = Number(k);
  const month = Math.floor(key / 1000);
  const day = Math.floor((key % 1000) / 10);
  const half = key % 10;
  return `${MONTHS[month - 1]} ${day} — ${half === 0 ? "matin" : "après-midi"}`;
}

function clearSelection() {
  $$("#calendar .cal-cell.selected").forEach((el) => el.classList.remove("selected"));
  selectedCellKeys = [];
}

function selectCells(cells) {
  $$("#calendar .cal-cell.selected").forEach((el) => el.classList.remove("selected"));
  selectedCellKeys = cells.map((el) => String(el.dataset.k));
  cells.forEach((el) => el.classList.add("selected"));
}

function cellsBetween(a, b) {
  const ka = Number(a.dataset.k);
  const kb = Number(b.dataset.k);
  const lo = Math.min(ka, kb);
  const hi = Math.max(ka, kb);
  return $$("#calendar .cal-cell")
    .filter((el) => {
      const k = Number(el.dataset.k);
      return k >= lo && k <= hi;
    })
    .sort((x, y) => Number(x.dataset.k) - Number(y.dataset.k));
}

function onCellMouseDown(e) {
  if ((state.readOnly && !state.requestMode) || e.button !== 0) return;
  const el = e.target.closest(".cal-cell");
  if (!el) return;
  if (state.requestMode && (el.textContent || el.classList.contains("pending"))) return;
  if (!state.requestMode && el.querySelector(".cal-hour-note")) {
    toast("Cette demi-journée contient une absence en heures.", true);
    return;
  }
  e.preventDefault();
  dragStartCell = el;
  dragLastCell = el;
  isDraggingCells = true;
  document.body.classList.add("selecting-cells");
  selectCells([el]);
}

function onCellMouseOver(e) {
  if (!isDraggingCells || !dragStartCell) return;
  const el = e.target.closest(".cal-cell");
  if (!el || el === dragLastCell) return;
  dragLastCell = el;
  selectCells(cellsBetween(dragStartCell, el));
}

function onCellMouseUp() {
  if (!isDraggingCells) return;
  isDraggingCells = false;
  document.body.classList.remove("selecting-cells");
  const anchor = dragLastCell;
  const cells = selectedCellKeys
    .map((k) => document.querySelector(`#calendar .cal-cell[data-k="${k}"]`))
    .filter(Boolean);
  dragStartCell = null;
  dragLastCell = null;
  if (cells.length) openPickerForCells(cells, anchor);
}

function openPickerForCells(cells, anchor) {
  if (!cells.length) return;
  pickerTargets = cells.map((el) => String(el.dataset.k));
  const first = pickerTargets[0];
  const last = pickerTargets[pickerTargets.length - 1];
  const picker = $("#code-picker");
  $("#code-picker-title").textContent = (state.requestMode ? "Demander — " : "") + (pickerTargets.length === 1
    ? cellLabel(first)
    : `${cellLabel(first)} → ${cellLabel(last)} · ${pickerTargets.length} demi-journée(s)`);
  const colors = codeColorMap();
  const codes = state.requestMode ? requestCodeList() : currentCodeList();
  $("#code-picker-list").innerHTML = codes.map((code) =>
    `<button class="code-btn" data-code="${esc(code)}" style="background:${cssColor(colors[code] || "F2F2F2")};color:${textColorFor(colors[code] || "F2F2F2")}">${esc(code)}</button>`
  ).join("");
  $("#code-picker-clear").classList.toggle("hidden", !!state.requestMode);

  picker.classList.remove("hidden");
  const el = anchor || cells[cells.length - 1];
  const rect = el.getBoundingClientRect();
  let left = rect.left + window.scrollX + 10;
  let top = rect.bottom + window.scrollY + 6;
  if (left + 260 > window.innerWidth) left = window.innerWidth - 270;
  if (top + 220 > window.innerHeight + window.scrollY) top = rect.top + window.scrollY - 226;
  picker.style.left = left + "px";
  picker.style.top = Math.max(4, top) + "px";
}

function closePicker(keepSelection = false) {
  $("#code-picker").classList.add("hidden");
  pickerTargets = [];
  if (!keepSelection) clearSelection();
}

$("#code-picker-list").addEventListener("click", (e) => {
  const btn = e.target.closest(".code-btn");
  if (!btn || !pickerTargets.length) return;
  if (state.requestMode) {
    submitLeaveRequest(btn.dataset.code);
    return;
  }
  setCells(pickerTargets, btn.dataset.code);
  closePicker();
});

let pendingRequestCode = null;
let pendingRequestCells = [];

function requestSummary(cells, code) {
  const sorted = cells.slice().sort((a, b) => a - b);
  const first = cellLabel(sorted[0]);
  const last = cellLabel(sorted[sorted.length - 1]);
  return `${first === last ? first : first + " → " + last} · ${code} · ${sorted.length} demi-journée(s)`;
}

function submitLeaveRequest(code) {
  if (!state.requestMode || !state.fiche) return;
  const cells = pickerTargets.slice();
  if (!cells.length) return;
  pendingRequestCode = code;
  pendingRequestCells = cells;
  $("#request-modal-summary").textContent = requestSummary(cells, code);
  $("#request-comment").value = "";
  $("#request-file").value = "";
  $("#request-error").classList.add("hidden");
  $("#request-error").textContent = "";
  closePicker(true);
  $("#request-modal").classList.remove("hidden");
  $("#request-comment").focus();
}

async function sendLeaveRequest() {
  if (!pendingRequestCode || !state.fiche) return;
  const cells = pendingRequestCells.slice();
  if (!cells.length) return;
  const form = new FormData();
  form.append("agent_id", String(state.fiche.id));
  form.append("code", pendingRequestCode);
  form.append("cells", JSON.stringify(cells));
  form.append("comment", $("#request-comment").value.trim());
  const file = $("#request-file").files[0];
  if (file) form.append("attachment", file);
  const headers = {};
  try {
    const res = await fetch("/api/requests", { method: "POST", body: form, headers });
    let data = null;
    try { data = await res.json(); } catch (_) { data = null; }
    if (!res.ok) throw new Error((data && data.error) || "Envoi impossible");
    $("#request-modal").classList.add("hidden");
    pendingRequestCode = null;
    pendingRequestCells = [];
    closePicker();
    toast(data.auto
      ? "Demande validée automatiquement"
      : `Demande envoyée à ${data.validator_nom || data.validator_login || "votre responsable"}`);
    refreshRequestBadge();
    viewFiche(state.fiche.id);
  } catch (err) {
    const el = $("#request-error");
    el.textContent = err.message;
    el.classList.remove("hidden");
  }
}

$("#request-cancel").addEventListener("click", () => {
  $("#request-modal").classList.add("hidden");
  pendingRequestCode = null;
  pendingRequestCells = [];
  closePicker();
});
$("#request-submit").addEventListener("click", sendLeaveRequest);
$("#request-modal").addEventListener("mousedown", (e) => {
  if (e.target.id === "request-modal") {
    $("#request-modal").classList.add("hidden");
    pendingRequestCode = null;
    pendingRequestCells = [];
    closePicker();
  }
});

/* ---------------------------- cassage / absences en heures ---------------------------- */
function openCassageModal() {
  if (!(state.requestMode || state.specialRequestMode) || !state.fiche) return;
  const calc = state.compute || {};
  const ca = Number(calc.ca_current_dispo ?? (calc.solde && calc.solde.ca && calc.solde.ca.current_dispo) ?? 0);
  const rtt = Number(calc.rtt_current_dispo ?? (calc.solde && calc.solde.rtt && calc.solde.rtt.current_dispo) ?? 0);
  const options = [];
  if (ca >= 1) options.push(`<option value="CA">CA — ${fmt(ca)} j de droits disponibles</option>`);
  if (rtt >= 1) options.push(`<option value="RTT">RTT — ${fmt(rtt)} j générés disponibles</option>`);
  if (!options.length) {
    toast("Aucun jour de CA ou de RTT disponible à casser.", true);
    return;
  }
  $("#cassage-code").innerHTML = options.join("");
  $("#cassage-info").textContent = "Seuls les droits de l'année sont cassables (le reliquat reporté ne l'est pas). 1 jour cassé = 7 heures créditées sur le compteur.";
  $("#cassage-comment").value = "";
  $("#cassage-error").classList.add("hidden");
  $("#cassage-error").textContent = "";
  $("#cassage-modal").classList.remove("hidden");
}

async function sendSpecialRequest(payload, modal, errorEl) {
  const headers = { "Content-Type": "application/json" };
  try {
    const res = await fetch("/api/requests", {
      method: "POST",
      headers,
      body: JSON.stringify(payload),
    });
    let data = null;
    try { data = await res.json(); } catch (_) { data = null; }
    if (!res.ok) throw new Error((data && data.error) || "Envoi impossible");
    $(modal).classList.add("hidden");
    toast(data.auto
      ? "Demande validée automatiquement"
      : `Demande envoyée à ${data.validator_nom || data.validator_login || "votre responsable"}`);
    refreshRequestBadge();
    viewFiche(state.fiche.id);
  } catch (err) {
    const el = $(errorEl);
    el.textContent = err.message;
    el.classList.remove("hidden");
  }
}

$("#cassage-cancel").addEventListener("click", () => $("#cassage-modal").classList.add("hidden"));
$("#cassage-modal").addEventListener("mousedown", (e) => {
  if (e.target.id === "cassage-modal") $("#cassage-modal").classList.add("hidden");
});
$("#cassage-submit").addEventListener("click", () => {
  if (!state.fiche) return;
  sendSpecialRequest({
    agent_id: state.fiche.id,
    request_type: "cassage",
    code: $("#cassage-code").value,
    days: 1,
    comment: $("#cassage-comment").value.trim(),
  }, "#cassage-modal", "#cassage-error");
});

function heuresDuration() {
  const start = $("#heures-start").value;
  const end = $("#heures-end").value;
  if (!start || !end) return null;
  const [sh, sm] = start.split(":").map(Number);
  const [eh, em] = end.split(":").map(Number);
  const minutes = (eh * 60 + em) - (sh * 60 + sm);
  if (!Number.isFinite(minutes) || minutes <= 0) return null;
  return Math.round((minutes / 60) * 10000) / 10000;
}

function updateHeuresDuration() {
  const h = heuresDuration();
  $("#heures-duration").textContent = h ? `Durée : ${fmtHours(h)} (${fmt(h / 7)} j)` : "Durée : —";
}

function openHeuresModal() {
  if (!(state.requestMode || state.specialRequestMode) || !state.fiche) return;
  const calc = state.compute || {};
  const cah = Number((calc.solde && calc.solde.cah && calc.solde.cah.restant) || 0);
  const rth = Number((calc.solde && calc.solde.rth && calc.solde.rth.restant) || 0);
  const rch = Number((calc.solde && calc.solde.rch && calc.solde.rch.restant) || 0);
  const options = [];
  if (cah > 0) options.push(`<option value="CAH">CAH — ${fmtHours(cah)} disponible(s)</option>`);
  if (rth > 0) options.push(`<option value="RTTH">RTTH — ${fmtHours(rth)} disponible(s)</option>`);
  if (rch > 0) options.push(`<option value="RCH">RCH — ${fmtHours(rch)} disponible(s)</option>`);
  if (!options.length) {
    toast("Aucune heure disponible : cassez un CA/RTT ou déclarez des heures de récupération.", true);
    return;
  }
  $("#heures-code").innerHTML = options.join("");
  const year = Number(state.fiche.year || state.year || new Date().getFullYear());
  const now = new Date();
  const today = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-${String(now.getDate()).padStart(2, "0")}`;
  const dateEl = $("#heures-date");
  dateEl.min = `${year}-01-01`;
  dateEl.max = `${year}-12-31`;
  dateEl.value = now.getFullYear() === year ? today : `${year}-01-01`;
  $("#heures-start").value = "09:00";
  $("#heures-end").value = "10:00";
  $("#heures-comment").value = "";
  $("#heures-error").classList.add("hidden");
  $("#heures-error").textContent = "";
  updateHeuresDuration();
  $("#heures-modal").classList.remove("hidden");
}

$("#heures-start").addEventListener("input", updateHeuresDuration);
$("#heures-end").addEventListener("input", updateHeuresDuration);
$("#heures-cancel").addEventListener("click", () => $("#heures-modal").classList.add("hidden"));
$("#heures-modal").addEventListener("mousedown", (e) => {
  if (e.target.id === "heures-modal") $("#heures-modal").classList.add("hidden");
});
$("#heures-submit").addEventListener("click", () => {
  if (!state.fiche) return;
  const hours = heuresDuration();
  const err = $("#heures-error");
  err.classList.add("hidden");
  if (!hours) {
    err.textContent = "Les horaires sont invalides : l'heure de fin doit suivre l'heure de début.";
    err.classList.remove("hidden");
    return;
  }
  sendSpecialRequest({
    agent_id: state.fiche.id,
    request_type: "heures",
    code: $("#heures-code").value,
    absence_date: $("#heures-date").value,
    start_time: $("#heures-start").value,
    end_time: $("#heures-end").value,
    hours,
    comment: $("#heures-comment").value.trim(),
  }, "#heures-modal", "#heures-error");
});

/* ---------------------------- heures de récupération ---------------------------- */
function openRecupModal() {
  if (!(state.requestMode || state.specialRequestMode) || !state.fiche) return;
  const year = Number(state.fiche.year || state.year || new Date().getFullYear());
  const now = new Date();
  const today = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-${String(now.getDate()).padStart(2, "0")}`;
  const dateEl = $("#recup-date");
  dateEl.min = `${year}-01-01`;
  dateEl.max = `${year}-12-31`;
  dateEl.value = now.getFullYear() === year ? today : `${year}-01-01`;
  $("#recup-hours").value = "1";
  $("#recup-comment").value = "";
  $("#recup-error").textContent = "";
  $("#recup-error").classList.add("hidden");
  $("#recup-modal").classList.remove("hidden");
  $("#recup-hours").focus();
}

$("#recup-cancel").addEventListener("click", () => $("#recup-modal").classList.add("hidden"));
$("#recup-modal").addEventListener("mousedown", (e) => {
  if (e.target.id === "recup-modal") $("#recup-modal").classList.add("hidden");
});
$("#recup-submit").addEventListener("click", () => {
  if (!state.fiche) return;
  const err = $("#recup-error");
  err.classList.add("hidden");
  const hours = Number($("#recup-hours").value);
  const date = $("#recup-date").value;
  if (!date) {
    err.textContent = "La date de réalisation est obligatoire.";
    err.classList.remove("hidden");
    return;
  }
  if (!hours || hours <= 0) {
    err.textContent = "Le nombre d'heures doit être supérieur à zéro.";
    err.classList.remove("hidden");
    return;
  }
  sendSpecialRequest({
    agent_id: state.fiche.id,
    request_type: "recuperation",
    code: "RCH",
    absence_date: date,
    hours,
    comment: $("#recup-comment").value.trim(),
  }, "#recup-modal", "#recup-error");
});

function openHoursDetailModal() {
  const f = state.fiche;
  if (!f) return;
  const calc = state.compute || {};
  const canEdit = !!(f.can_edit || (state.user && state.user.admin));
  const rows = [];
  (f.cassages || []).forEach((c) => {
    rows.push({
      date: c.decide_le || c.cree_le || "",
      counter: c.code === "CA" ? "CAH" : "RTTH",
      type: "Cassage",
      hours: 7 * Number(c.days || 1),
      expiry: c.valid_until || "",
      sign: "+",
    });
  });
  (f.recoveries || []).forEach((r) => {
    rows.push({
      date: r.absence_date || "",
      counter: "RCH",
      type: "Déclaration",
      hours: Number(r.hours || 0),
      expiry: r.valid_until || "",
      sign: "+",
    });
  });
  (f.hourly || []).forEach((h) => {
    rows.push({
      date: h.absence_date || "",
      counter: h.code || "",
      type: "Prise",
      hours: Number(h.hours || 0),
      expiry: "",
      sign: "-",
      hourlyId: h.id,
      requestId: h.request_id,
      startTime: h.start_time || "",
      endTime: h.end_time || "",
    });
  });
  rows.sort((a, b) => String(b.date || "").localeCompare(String(a.date || "")));
  const counterKeys = [
    ["cah", "CAH"], ["rth", "RTTH"], ["rch", "RCH"],
  ];
  $("#hours-detail-summary").innerHTML = counterKeys.map(([key, label]) => {
    const s = (calc.solde || {})[key] || {};
    return `<span><b>${label}</b> : crédit ${fmtHours(s.credit)} · pris ${fmtHours(s.used_year)} · restant ${fmtHours(s.restant)}</span>`;
  }).join("");

  const thead = document.querySelector(".hours-detail-table thead tr");
  if (thead) {
    let th = thead.querySelector(".hours-actions-head");
    if (!th) {
      th = document.createElement("th");
      th.className = "hours-actions-head";
      th.textContent = "Actions";
      thead.appendChild(th);
    }
    th.classList.toggle("hidden", !canEdit);
  }

  const actionCell = (r) => {
    if (!canEdit) return "";
    if (r.type !== "Prise") return `<td class="hours-actions-col"></td>`;
    return `<td class="hours-actions-col">
      <button type="button" class="btn btn-small" data-hourly-edit="${r.hourlyId}">Modifier</button>
      <button type="button" class="btn btn-small btn-danger" data-hourly-delete="${r.hourlyId}">Supprimer</button>
    </td>`;
  };

  $("#hours-detail-body").innerHTML = rows.length
    ? rows.map((r) => `<tr>
        <td>${esc(frDate(r.date))}</td>
        <td>${esc(r.counter)}</td>
        <td>${esc(r.type)}</td>
        <td class="num">${r.sign}${esc(fmtHours(r.hours))}</td>
        <td>${r.expiry ? esc(frDate(r.expiry)) : "—"}</td>
        ${actionCell(r)}
      </tr>`).join("")
    : `<tr><td colspan="${canEdit ? 6 : 5}" class="muted">Aucune heure enregistrée.</td></tr>`;
  $("#hours-detail-modal").classList.remove("hidden");

  $$("[data-hourly-edit]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const h = (f.hourly || []).find((x) => String(x.id) === String(btn.dataset.hourlyEdit));
      if (!h) return;
      $("#hours-detail-modal").classList.add("hidden");
      openHourlyEditModal(h);
    });
  });
  $$("[data-hourly-delete]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const id = Number(btn.dataset.hourlyDelete);
      if (!id || !confirm("Supprimer ces heures posées ?")) return;
      try {
        await api("/api/hourly/" + id, { method: "DELETE" });
        $("#hours-detail-modal").classList.add("hidden");
        toast("Heures supprimées");
        viewFiche(f.id);
      } catch (err) {
        toast("Suppression impossible : " + err.message, true);
      }
    });
  });
}

let editingHourlyId = null;

function hourlyEditDuration() {
  const start = $("#hourly-edit-start").value;
  const end = $("#hourly-edit-end").value;
  if (!start || !end) return null;
  const [sh, sm] = start.split(":").map(Number);
  const [eh, em] = end.split(":").map(Number);
  const minutes = (eh * 60 + em) - (sh * 60 + sm);
  if (!Number.isFinite(minutes) || minutes <= 0) return null;
  return Math.round((minutes / 60) * 10000) / 10000;
}

function updateHourlyEditDuration() {
  const h = hourlyEditDuration();
  $("#hourly-edit-duration").textContent = h
    ? `Durée : ${fmtHours(h)} (${fmt(h / 7)} j)`
    : "Durée : —";
}

function openHourlyEditModal(h) {
  if (!state.fiche || !(state.fiche.can_edit || (state.user && state.user.admin))) return;
  editingHourlyId = h.id;
  $("#hourly-edit-code").value = h.code || "CAH";
  const year = Number(state.fiche.year || state.year || new Date().getFullYear());
  const dateEl = $("#hourly-edit-date");
  dateEl.min = `${year}-01-01`;
  dateEl.max = `${year}-12-31`;
  dateEl.value = h.absence_date || "";
  $("#hourly-edit-start").value = h.start_time || "";
  $("#hourly-edit-end").value = h.end_time || "";
  $("#hourly-edit-error").textContent = "";
  $("#hourly-edit-error").classList.add("hidden");
  updateHourlyEditDuration();
  $("#hourly-edit-modal").classList.remove("hidden");
}

$("#hourly-edit-start").addEventListener("input", updateHourlyEditDuration);
$("#hourly-edit-end").addEventListener("input", updateHourlyEditDuration);
$("#hourly-edit-cancel").addEventListener("click", () => $("#hourly-edit-modal").classList.add("hidden"));
$("#hourly-edit-modal").addEventListener("mousedown", (e) => {
  if (e.target.id === "hourly-edit-modal") $("#hourly-edit-modal").classList.add("hidden");
});
$("#hourly-edit-submit").addEventListener("click", async () => {
  if (!editingHourlyId || !state.fiche) return;
  const err = $("#hourly-edit-error");
  err.classList.add("hidden");
  err.textContent = "";
  const date = $("#hourly-edit-date").value;
  const start = $("#hourly-edit-start").value;
  const end = $("#hourly-edit-end").value;
  const hours = hourlyEditDuration();
  if (!date) {
    err.textContent = "La date est obligatoire.";
    err.classList.remove("hidden");
    return;
  }
  if (!hours) {
    err.textContent = "Les horaires sont invalides : l'heure de fin doit suivre l'heure de début.";
    err.classList.remove("hidden");
    return;
  }
  try {
    await api("/api/hourly/" + editingHourlyId, {
      method: "PUT",
      body: JSON.stringify({
        code: $("#hourly-edit-code").value,
        absence_date: date,
        start_time: start,
        end_time: end,
        hours,
      }),
    });
    $("#hourly-edit-modal").classList.add("hidden");
    toast("Heures modifiées");
    viewFiche(state.fiche.id);
  } catch (e) {
    err.textContent = e.message;
    err.classList.remove("hidden");
  }
});

$("#hours-detail-close").addEventListener("click", () => $("#hours-detail-modal").classList.add("hidden"));
$("#hours-detail-modal").addEventListener("mousedown", (e) => {
  if (e.target.id === "hours-detail-modal") $("#hours-detail-modal").classList.add("hidden");
});

/* ---------------------------- nouvelle fiche + compte agent ---------------------------- */
function forceUpper(e) {
  const pos = e.target.selectionStart;
  e.target.value = e.target.value.toUpperCase();
  e.target.setSelectionRange(pos, pos);
}

let newFicheId = null;

async function openNewFicheModal() {
  if (!canCreateFiche()) return;
  const modal = $("#new-fiche-modal");
  if (!modal) return;
  const errEl = $("#new-fiche-error");
  errEl.classList.add("hidden");
  errEl.textContent = "";
  $("#new-fiche-form").classList.remove("hidden");
  $("#new-fiche-success").classList.add("hidden");
  $("#nf-nom").value = "";
  $("#nf-prenom").value = "";
  $("#nf-email").value = "";
  $("#nf-matricule").value = "";
  $("#new-fiche-year").textContent = "Année de la fiche : " + state.year;
  let scopeUsers = [];
  try {
    scopeUsers = await api("/api/scope-users");
  } catch (_) { scopeUsers = []; }
  const ownerRoles = VALIDATOR_ROLES;
  let owners = (scopeUsers || []).filter(
    (u) => ownerRoles.includes(userRole(u)) && u.actif !== 0
  );
  if (!owners.some((u) => u.id === state.user.id) && ownerRoles.includes(userRole(state.user))) {
    owners.unshift(state.user);
  }
  owners.sort((a, b) =>
    String(a.nom || a.login || "").localeCompare(String(b.nom || b.login || ""), "fr")
  );
  $("#nf-owner").innerHTML = owners.map((u) =>
    `<option value="${u.id}">${esc(u.nom || u.login)} (${esc(u.login)}) — ${esc(ROLE_LABELS[userRole(u)] || userRole(u))}</option>`
  ).join("");
  const defaultOwner = owners.some((u) => u.id === state.user.id)
    ? state.user.id
    : (owners[0] ? owners[0].id : state.user.id);
  $("#nf-owner").value = String(defaultOwner);

  const loadValidators = async (ownerId) => {
    let validators = [];
    try {
      validators = await api("/api/validators?owner_id=" + ownerId);
    } catch (_) { validators = []; }
    state.validators = validators;
    $("#nf-validator").innerHTML = validators.map((v) =>
      `<option value="${v.id}" ${v.id === state.user.id ? "selected" : ""}>${esc(v.nom || v.login)} (${esc(v.login)}) — ${esc(ROLE_LABELS[v.role] || v.role)}</option>`
    ).join("");
    if (!validators.some((v) => v.id === state.user.id) && validators.length) {
      $("#nf-validator").value = String(validators[0].id);
    }
  };
  $("#nf-owner").onchange = () => loadValidators(Number($("#nf-owner").value));
  await loadValidators(defaultOwner);
  modal.classList.remove("hidden");
  $("#nf-nom").focus();
}

$("#nf-nom").addEventListener("input", forceUpper);
$("#nf-prenom").addEventListener("input", forceUpper);
$("#nf-cancel").addEventListener("click", () => $("#new-fiche-modal").classList.add("hidden"));
$("#new-fiche-modal").addEventListener("mousedown", (e) => {
  if (e.target.id === "new-fiche-modal") $("#new-fiche-modal").classList.add("hidden");
});
$("#nf-open").addEventListener("click", () => {
  $("#new-fiche-modal").classList.add("hidden");
  if (newFicheId) location.hash = "#/agent/" + newFicheId;
});
$("#nf-submit").addEventListener("click", async () => {
  const nom = $("#nf-nom").value.trim().toUpperCase();
  const prenom = $("#nf-prenom").value.trim().toUpperCase();
  const email = $("#nf-email").value.trim();
  const validatorId = $("#nf-validator").value ? Number($("#nf-validator").value) : null;
  const ownerId = $("#nf-owner").value ? Number($("#nf-owner").value) : null;
  const errEl = $("#new-fiche-error");
  errEl.classList.add("hidden");
  if (!nom || !prenom) {
    errEl.textContent = "Le nom et le prénom sont obligatoires.";
    errEl.classList.remove("hidden");
    return;
  }
  if (!email || !/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email)) {
    errEl.textContent = "L'adresse e-mail de l'agent est obligatoire et doit être valide.";
    errEl.classList.remove("hidden");
    return;
  }
  if (!ownerId) {
    errEl.textContent = "Le propriétaire de la fiche est obligatoire.";
    errEl.classList.remove("hidden");
    return;
  }
  if (!validatorId) {
    errEl.textContent = "Le compte valideur est obligatoire.";
    errEl.classList.remove("hidden");
    return;
  }
  try {
    const res = await api("/api/agents", {
      method: "POST",
      body: JSON.stringify({
        nom, prenom, email, matricule: $("#nf-matricule").value.trim(), owner_id: ownerId, validator_id: validatorId, year: state.year,
      }),
    });
    newFicheId = res.id;
    $("#nf-login").textContent = res.agent_login || "";
    $("#nf-password").textContent = res.agent_password || "";
    const byAd = state.user.auth_mode === "ad";
    $("#nf-password-line").classList.toggle("hidden", byAd);
    $("#nf-hint").textContent = byAd
      ? "L'agent se connecte avec son compte Ville (Active Directory) : renseignez son « Identifiant AD » dans Paramétrage > Utilisateurs si son identifiant Ville diffère de celui-ci."
      : "Communiquez ces informations à l'agent. Le valideur peut réinitialiser le mot de passe dans Utilisateurs.";
    $("#new-fiche-form").classList.add("hidden");
    $("#new-fiche-success").classList.remove("hidden");
    toast("Fiche et compte agent créés");
    refreshRequestBadge();
  } catch (err) {
    errEl.textContent = err.message;
    errEl.classList.remove("hidden");
  }
});

$("#code-picker-clear").addEventListener("click", () => {
  if (pickerTargets.length) setCells(pickerTargets, "");
  closePicker();
});

document.addEventListener("mousedown", (e) => {
  const picker = $("#code-picker");
  if (!picker.classList.contains("hidden") &&
      !picker.contains(e.target) && !e.target.closest(".cal-cell")) {
    closePicker();
  }
});
document.addEventListener("mouseup", onCellMouseUp);
document.addEventListener("keydown", (e) => { if (e.key === "Escape") closePicker(); });

function setCells(keys, code) {
  if (state.readOnly) return;
  keys.forEach((k) => {
    if (code) state.fiche.cells[k] = code;
    else delete state.fiche.cells[k];
  });
  paintCalendar();
  scheduleCompute();
  scheduleSave();
}

function setCell(k, code) {
  setCells([k], code);
}

/* ---------------------------- calcul / sauvegarde ---------------------------- */
function scheduleCompute() {
  clearTimeout(state.computeTimer);
  state.computeTimer = setTimeout(runCompute, 250);
}

async function runCompute() {
  const f = state.fiche;
  if (!f) return;
  try {
    const res = await api("/api/compute", {
      method: "POST",
      body: JSON.stringify({
        params: f.params,
        periods: f.periods || [],
        cells: f.cells,
        year: f.year,
        cassages: f.cassages || [],
        hourly: f.hourly || [],
        recoveries: f.recoveries || [],
      }),
    });
    if (state.fiche !== f) return;
    state.compute = res;
    const rchAlertEl = $("#rch-alert");
    if (rchAlertEl) rchAlertEl.innerHTML = rchExpiryAlert(res);
    renderSoldes(res);
    renderLegend();
    paintCalendar();
    const errEl = $("#f-errors");
    if (errEl) errEl.innerHTML = "";
  } catch (err) {
    const errEl = $("#f-errors");
    if (errEl) errEl.innerHTML = `<div class="form-error">${esc(err.message)}</div>`;
  }
}

function scheduleSave() {
  clearTimeout(state.saveTimer);
  state.saveTimer = setTimeout(saveFiche, 800);
}

async function saveFiche() {
  const f = state.fiche;
  if (!f) return;
  const ind = $("#save-ind");
  if (ind) ind.textContent = "Enregistrement…";
  try {
    const res = await api("/api/agents/" + f.id, {
      method: "PUT",
      body: JSON.stringify({
        nom: f.nom,
        prenom: f.prenom || "",
        email: f.email || "",
        matricule: f.matricule || "",
        validator_id: f.validator_id == null ? null : f.validator_id,
        params: f.params,
        periods: f.periods || [],
        is_manager: f.is_manager ? 1 : 0,
        cells: f.cells,
      }),
    });
    // IMPORTANT : ne pas remplacer `state.fiche` par `res`. Les gestionnaires
    // de champs détiennent une référence à l'objet params ; substituer l'objet
    // les « détacherait » et les saisies suivantes seraient perdues (le calcul
    // et la sauvegarde utiliseraient l'ancien objet -> synthèse figée).
    Object.assign(f.params, res.params || {});
    if (res.periods !== undefined) f.periods = res.periods;
    if (res.is_manager !== undefined) f.is_manager = res.is_manager;
    if (res.nom !== undefined) f.nom = res.nom;
    if (res.prenom !== undefined) f.prenom = res.prenom;
    if (res.email !== undefined) f.email = res.email;
    if (res.validator_id !== undefined) f.validator_id = res.validator_id;
    if (res.pending_cells) f.pending_cells = res.pending_cells;
    if (res.pending_count !== undefined) f.pending_count = res.pending_count;
    if (res.can_edit_cells !== undefined) f.can_edit_cells = res.can_edit_cells;
    if (res.cassages !== undefined) f.cassages = res.cassages;
    if (res.hourly !== undefined) f.hourly = res.hourly;
    if (res.recoveries !== undefined) f.recoveries = res.recoveries;
    if (res.can_request !== undefined) f.can_request = res.can_request;
    if (res.cells) f.cells = res.cells;
    if (res.modifie_le !== undefined) f.modifie_le = res.modifie_le;
    if (ind) ind.textContent = "Enregistré ✓";
    setTimeout(() => { if (ind) ind.textContent = ""; }, 2000);
  } catch (err) {
    if (ind) ind.textContent = "";
    toast("Sauvegarde impossible : " + err.message, true);
  }
}

/* ---------------------------- panneau soldes ---------------------------- */
function renderSoldes(r) {
  const el = $("#soldes");
  if (!el) return;

  const KINDS = {
    "Congés annuels restants": "ca", "Congés en heures restants": "cah",
    "RTT restants": "rtt", "RTT en heures restants": "rth",
    "Heures de récupération restantes": "rch",
    "Jours de sujétion": "js", "Bonification": "bonif", "CET": "cet",
  };
  const CODES_BY_TITLE = {
    "Congés annuels restants": "CA", "Congés en heures restants": "CAH",
    "RTT restants": "RTT", "RTT en heures restants": "RTTH",
    "Heures de récupération restantes": "RCH",
    "Jours de sujétion": "JS", "Bonification": "JB", "CET": "CET",
  };
  const block = (title, right, rows, extra = "") => {
    const kind = KINDS[title];
    const code = CODES_BY_TITLE[title];
    const hex = code ? codeColorMap()[code] : null;
    // Fond = couleur d'absence du classeur, fortement atténuée avec du blanc.
    const vars = hex
      ? ` style="--sb-tint:linear-gradient(180deg, ${mixColor(hex, 0.18)}, ${mixColor(hex, 0.06)}); --sb-ink:${shadeColor(hex, 0.55)}; --sb-line:${cssColor(hex)};"`
      : "";
    return `
    <div class="solde-block${kind ? " sb-" + kind : ""}"${vars}>
      <h4><span>${title}</span><span>${right}</span></h4>
      ${rows.map(([l, v, cls]) => `<div class="vals"><span class="lbl">${l}</span><span class="v ${cls || ""}">${v}</span></div>`).join("")}
      ${extra}
    </div>`;
  };

  const cls = (v) => (v < 0 ? "restant neg" : "restant");
  const s = r.solde;
  const bonif = r.bonif || {};
  const cet = r.cet_info || {};

  el.innerHTML = `
    <div class="card" style="padding:12px">
      <h3 style="margin-top:0">Synthèse</h3>
      <div class="vals" style="display:flex;justify-content:space-between;font-size:12px;color:var(--muted);margin-bottom:8px">
        <span>Prorata : <b style="color:var(--text)">${fmt(r.prorata * 100)} %</b></span>
        <span>Cycle : <b style="color:var(--text)">${r.cycle_ok ? "✓" : "—"}</b></span>
      </div>

      <div class="solde-list">
      ${block("Congés annuels restants", `<span class="${cls(s.ca.restant)}">${fmt(s.ca.restant)} j</span>`, [
        ["Droits (année)", `<span title="Droit initial ${fmt(r.ca_droit)} j − ${fmt(s.ca.casse || 0)} j cassés">${fmt(r.ca_droit - (s.ca.casse || 0))} j</span>`],
        ["Reliquat reporté", fmt(r.reliquat_restant) + " j" + (r.reliquat_mode ? " (" + r.reliquat_mode + ")" : "")],
        ["CA pris", fmt(s.ca.pris_ca ?? s.ca.pris) + " j"],
      ].concat((s.ca.casse || 0) > 0 ? [["Cassé en heures", fmt(s.ca.casse) + " j"]] : []))}

      ${(r.cah_credit > 0 || r.cah_used > 0) ? block("Congés en heures restants", `<span class="${cls(s.cah.restant)}">${fmtHours(s.cah.restant)}</span>`, [
        ["Congés en heures pris", fmtHours(s.cah.used_year)],
      ], `<div class="cet-hint">Heures valides jusqu'au : <b>${s.cah.next_expiry ? frDate(s.cah.next_expiry) : "—"}</b></div>`) : ""}

      ${block("RTT restants", `<span class="${cls(s.rtt.restant)}">${fmt(s.rtt.restant)} j</span>`, [
        ["Généré à ce jour", fmt(r.rtt_genere - (s.rtt.casse || 0)) + " j / " + fmt(r.rtt_total - (s.rtt.casse || 0)) + " j"],
        ["RTT Pris", fmt(s.rtt.pris_rtt ?? s.rtt.pris) + " j"],
        ["Déduction (absences)", fmt(s.rtt.deduction) + " j"],
      ].concat((s.rtt.casse || 0) > 0 ? [["Cassé en heures", fmt(s.rtt.casse) + " j"]] : []))}

      ${(r.rth_credit > 0 || r.rth_used > 0) ? block("RTT en heures restants", `<span class="${cls(s.rth.restant)}">${fmtHours(s.rth.restant)}</span>`, [
        ["RTT en heures pris", fmtHours(s.rth.used_year)],
      ], `<div class="cet-hint">Heures valides jusqu'au : <b>${s.rth.next_expiry ? frDate(s.rth.next_expiry) : "—"}</b></div>`) : ""}

      ${(r.rch_credit > 0 || r.rch_used > 0) ? block("Heures de récupération restantes", `<span class="${cls(s.rch.restant)}">${fmtHours(s.rch.restant)}</span>`, [
        ["Heures de récupération prises", fmtHours(s.rch.used_year)],
      ], `<div class="cet-hint">Heures valides jusqu'au : <b>${s.rch.next_expiry ? frDate(s.rch.next_expiry) : "—"}</b></div>`) : ""}

      ${block("Jours de sujétion", `<span class="${cls(s.js.restant)}">${fmt(s.js.restant)} j</span>`, [
        ["Généré à ce jour", fmt(r.js_genere) + " j / " + fmt(r.js_total) + " j"],
        ["Pris", fmt(s.js.pris) + " j"],
        ["Déduction (absences)", fmt(s.js.deduction) + " j"],
      ], r.suj_interval ? `<div class="cet-hint">1 jour généré tous les <b>${fmt(r.suj_interval)}</b> jours</div>` : "")}

      ${block("Bonification", `<span class="${cls(s.jb.restant)}">${fmt(s.jb.restant)} j</span>`, [
        ["Généré", fmt(r.jb_genere) + " j"],
        ["Pris", fmt(s.jb.pris) + " j"],
      ], `<div class="cet-hint">CA pics (Jan–Avr, Nov–Déc) : <b>${fmt(bonif.peak)}</b> j dont <b>${fmt(bonif.peak_ca)}</b> j de CA</div>`)}

      ${block("CET", `<span class="${cls(s.cet.restant)}">${fmt(s.cet.restant)} j</span>`, [
        ["Solde initial", fmt(s.cet.initial) + " j"],
        ["Utilisé", fmt(s.cet.pris) + " j"],
      ], `<div class="cet-hint">Dépôt possible : <b>${typeof cet.ca_eligible === "number" ? fmt(cet.ca_eligible) + " j de CA" : cet.ca_eligible}</b> · <b>${typeof cet.rtt_eligible === "number" ? fmt(cet.rtt_eligible) + " j de RTT" : cet.rtt_eligible}</b></div>`)}

      <div class="solde-block total">
        <h4><span>TOTAL</span></h4>
        <div class="vals"><span class="lbl">Pris</span><span class="v">${fmt(s.total.pris)} j</span></div>
        <div class="vals"><span class="lbl">Restant</span><span class="v ${cls(s.total.restant)}">${fmt(s.total.restant)} j</span></div>
      </div>
      </div>
    </div>`;
}

/* ==========================================================================
   Paramétrage (admin)
   ========================================================================== */
function viewSettings() {
  if (!state.user.admin) { location.hash = "#/dashboard"; return; }
  const embedded = !!$("#admin-body");
  // Copie de travail : l'état global n'est modifié qu'après enregistrement.
  const s = JSON.parse(JSON.stringify(state.settings));
  if (!Array.isArray(s.vacances_scolaires)) s.vacances_scolaires = [];
  const c = contentEl();

  const cell = (coll, i, f, value, type = "text", extra = "") =>
    `<input type="${type}" ${extra} data-coll="${coll}" data-i="${i}" data-f="${f}" value="${esc(value)}">`;
  const numCell = (coll, i, f, value, extra = "") =>
    cell(coll, i, f, value, "number", `step="0.5" min="0" ${extra}`);
  const delBtn = (coll, i) =>
    `<button type="button" class="btn btn-small btn-danger" data-remove="${coll}" data-i="${i}" title="Supprimer cette ligne">×</button>`;

  const simpleTable = (coll, label, arr, opts = {}) => {
    const extra = opts.extra || "";
    return `
      <table class="settings-table">
        <thead><tr><th>${label}</th><th class="col-act"></th></tr></thead>
        <tbody>
          ${arr.map((v, i) => `<tr>
            <td>${cell(coll, i, "value", v, opts.type || "text", extra)}</td>
            <td class="col-act">${delBtn(coll, i)}</td>
          </tr>`).join("")}
        </tbody>
      </table>
      <button type="button" class="btn btn-small settings-add" data-add="${coll}">+ Ajouter</button>`;
  };

  const build = () => {
    const penRows = s.penibilites.map((p, i) => `<tr>
      <td>${cell("penibilites", i, "name", p.name)}</td>
      <td>${numCell("penibilites", i, "sujections", p.sujections)}</td>
      <td class="col-act">${delBtn("penibilites", i)}</td>
    </tr>`).join("");

    const ttRows = s.temps_travail.map((t, i) => `<tr>
      <td>${cell("temps_travail", i, "name", t.name)}</td>
      <td>${numCell("temps_travail", i, "rtt", t.rtt)}</td>
      <td class="col-act">${delBtn("temps_travail", i)}</td>
    </tr>`).join("");

    const codeRows = s.codes.map((x, i) => `<tr>
      <td class="col-code">${cell("codes", i, "code", x.code)}</td>
      <td>${cell("codes", i, "libelle", x.libelle)}</td>
      <td class="col-color">
        <input type="color" data-coll="codes" data-i="${i}" data-f="colorPick" value="${cssColor(x.color)}">
        <input type="text" class="hex-input" maxlength="6" spellcheck="false"
               data-coll="codes" data-i="${i}" data-f="color" value="${esc(String(x.color || "").toUpperCase())}">
      </td>
      <td class="col-check"><input type="checkbox" data-coll="codes" data-i="${i}" data-f="in_n" ${x.in_n ? "checked" : ""}></td>
      <td class="col-check"><input type="checkbox" data-coll="codes" data-i="${i}" data-f="in_s" ${x.in_s ? "checked" : ""}></td>
      <td class="col-act">${delBtn("codes", i)}</td>
    </tr>`).join("");

    const ferieRows = s.jours_feries.map((x, i) => `<tr>
      <td><input type="date" data-coll="jours_feries" data-i="${i}" data-f="0" value="${esc(x[0])}"></td>
      <td>${cell("jours_feries", i, "1", x[1])}</td>
      <td class="col-act">${delBtn("jours_feries", i)}</td>
    </tr>`).join("");

    const vacRows = s.vacances_scolaires.map((x, i) => `<tr>
      <td><input type="date" data-coll="vacances_scolaires" data-i="${i}" data-f="0" value="${esc(x[0])}"></td>
      <td><input type="date" data-coll="vacances_scolaires" data-i="${i}" data-f="1" value="${esc(x[1])}"></td>
      <td>${cell("vacances_scolaires", i, "2", x[2])}</td>
      <td class="col-act">${delBtn("vacances_scolaires", i)}</td>
    </tr>`).join("");

    c.innerHTML = `
      ${embedded ? "<h2>Calcul et calendrier</h2>" : "<h1>Paramétrage</h1>"}
      <div id="set-msg"></div>
      <div class="settings-grid" id="settings-root">

        <div class="card">
          <h3>Pénibilités et sujétions</h3>
          <table class="settings-table">
            <thead><tr><th>Pénibilité</th><th>Sujétions</th><th class="col-act"></th></tr></thead>
            <tbody>${penRows}</tbody>
          </table>
          <button type="button" class="btn btn-small settings-add" data-add="penibilites">+ Ajouter</button>
        </div>

        <div class="card">
          <h3>Durées hebdomadaires</h3>
          ${simpleTable("durees", "Durée", s.durees)}
        </div>

        <div class="card">
          <h3>Quotités</h3>
          ${simpleTable("quotites", "Quotité", s.quotites)}
        </div>

        <div class="card">
          <h3>Nb de jours par semaine</h3>
          ${simpleTable("jours_hebdo", "Jours / semaine", s.jours_hebdo, { type: "number", extra: 'step="0.5" min="0" max="7"' })}
        </div>

        <div class="card">
          <h3>Durée → NB RTT annuels</h3>
          <table class="settings-table">
            <thead><tr><th>Durée</th><th>NB RTT</th><th class="col-act"></th></tr></thead>
            <tbody>${ttRows}</tbody>
          </table>
          <button type="button" class="btn btn-small settings-add" data-add="temps_travail">+ Ajouter</button>
        </div>

        <div class="card">
          <h3>Jours fériés</h3>
          <table class="settings-table">
            <thead><tr><th>Date</th><th>Libellé</th><th class="col-act"></th></tr></thead>
            <tbody>${ferieRows}</tbody>
          </table>
          <button type="button" class="btn btn-small settings-add" data-add="jours_feries">+ Ajouter</button>
        </div>

        <div class="card settings-wide">
          <h3>Vacances scolaires (zone C)</h3>
          <table class="settings-table">
            <thead><tr><th>Début</th><th>Fin</th><th>Libellé</th><th class="col-act"></th></tr></thead>
            <tbody>${vacRows}</tbody>
          </table>
          <button type="button" class="btn btn-small settings-add" data-add="vacances_scolaires">+ Ajouter une période</button>
        </div>

        <div class="card settings-wide">
          <h3>Codes d'absence</h3>
          <table class="settings-table codes-table">
            <thead><tr>
              <th>Code</th><th>Libellé</th><th>Couleur</th>
              <th class="col-check" title="Présent dans la liste N">Liste N</th>
              <th class="col-check" title="Présent dans la liste S (menu du calendrier)">Liste S</th>
              <th class="col-act"></th>
            </tr></thead>
            <tbody>${codeRows}</tbody>
          </table>
          <button type="button" class="btn btn-small settings-add" data-add="codes">+ Ajouter un code</button>
        </div>

        <div class="card settings-wide">
          <h3>Année par défaut</h3>
          <label style="max-width:220px">Année
            <input type="number" id="set-year" value="${esc(s.general.year)}"></label>
          <p class="users-hint">Année proposée par défaut dans le sélecteur d'année ; chaque utilisateur peut ensuite choisir une autre année.</p>
          <h3 style="margin-top:16px">Matrice des droits (${(s.matrix || []).length} lignes)</h3>
          <div class="matrix-table">
            <table>
              <thead><tr><th>Pénibilité</th><th>Durée</th><th>Quotité</th><th>Jours</th></tr></thead>
              <tbody id="matrix-body"></tbody>
            </table>
          </div>
          <button type="button" class="btn btn-small" id="matrix-add" style="margin-top:6px">+ Ajouter une ligne</button>
        </div>
      </div>

      <div class="card" style="display:flex;gap:10px">
        <button class="btn btn-primary" id="set-save">Enregistrer le paramétrage</button>
        <button class="btn" id="set-reimport">Réimporter depuis le classeur Excel</button>
      </div>`;
  };

  const drawMatrix = () => {
    $("#matrix-body").innerHTML = (s.matrix || []).map((r, i) => `
      <tr data-i="${i}">
        <td><input data-f="pen" value="${esc(r.pen)}"></td>
        <td><input data-f="duree" value="${esc(r.duree)}"></td>
        <td><input data-f="quotite" value="${esc(r.quotite)}"></td>
        <td><input data-f="jours" value="${esc(r.jours)}"></td>
      </tr>`).join("");
  };

  const bindAll = () => {
    // Année
    $("#set-year").addEventListener("input", (e) => {
      s.general.year = Number(e.target.value) || s.general.year;
    });

    // Matrice
    $("#matrix-add").addEventListener("click", () => {
      s.matrix.push({ pen: "", duree: "", quotite: "", jours: 5 });
      drawMatrix();
    });
    $("#matrix-body").addEventListener("change", (e) => {
      const tr = e.target.closest("tr");
      if (!tr) return;
      const r = s.matrix[parseInt(tr.dataset.i, 10)];
      const f = e.target.dataset.f;
      r[f] = f === "jours" ? Number(e.target.value) : e.target.value;
    });

    // Listes : édition (délégation sur la racine)
    const root = $("#settings-root");
    root.addEventListener("input", (e) => {
      const el = e.target;
      const coll = el.dataset.coll;
      if (!coll) return;
      const i = Number(el.dataset.i);
      const f = el.dataset.f;
      let val;
      if (el.type === "checkbox") val = el.checked;
      else if (el.type === "number") val = el.value === "" ? "" : Number(el.value);
      else val = el.value;

      if (f === "colorPick") {
        const hex = String(val).replace("#", "").toUpperCase();
        s.codes[i].color = hex;
        const txt = el.parentElement.querySelector(".hex-input");
        if (txt) txt.value = hex;
        return;
      }
      if (f === "color") {
        const hex = String(val).replace(/[^0-9a-fA-F]/g, "").slice(0, 6).toUpperCase();
        el.value = hex;
        s.codes[i].color = hex;
        if (hex.length === 6) {
          const pick = el.parentElement.querySelector('input[type="color"]');
          if (pick) pick.value = "#" + hex.toLowerCase();
        }
        return;
      }

      if (coll === "durees" || coll === "quotites" || coll === "jours_hebdo") {
        s[coll][i] = val;
      } else if (coll === "jours_feries" || coll === "vacances_scolaires") {
        s[coll][i][Number(f)] = val;
      } else {
        s[coll][i][f] = val;
      }
    });

    root.addEventListener("click", (e) => {
      const add = e.target.closest("[data-add]");
      if (add) {
        const coll = add.dataset.add;
        const year = s.general.year || new Date().getFullYear();
        const defs = {
          penibilites: () => ({ name: "", sujections: 0 }),
          durees: () => "",
          quotites: () => "",
          jours_hebdo: () => 5,
          temps_travail: () => ({ name: "", rtt: 0 }),
          codes: () => ({ code: "", libelle: "", color: "F2F2F2", in_n: true, in_s: true }),
          jours_feries: () => [`${year}-01-01`, ""],
          vacances_scolaires: () => [`${year}-01-01`, `${year}-01-01`, ""],
        };
        s[coll].push(defs[coll]());
        render();
        return;
      }

      const rem = e.target.closest("[data-remove]");
      if (rem) {
        const coll = rem.dataset.remove;
        s[coll].splice(Number(rem.dataset.i), 1);
        render();
      }
    });
  };

  const saveSettings = async () => {
    // Année
    s.general = { ...s.general, year: Number($("#set-year").value) || s.general.year };
    if (s.general.year) {
      s.general.year_start = s.general.year + "-01-01";
      s.general.year_end = s.general.year + "-12-31";
    }

    // Nettoyage et normalisation des listes
    const out = JSON.parse(JSON.stringify(s));
    out.penibilites = out.penibilites
      .filter((p) => String(p.name || "").trim())
      .map((p) => ({ name: String(p.name).trim(), sujections: Number(p.sujections) || 0 }));
    out.durees = out.durees.map((x) => String(x).trim()).filter(Boolean);
    out.quotites = out.quotites.map((x) => String(x).trim()).filter(Boolean);
    out.jours_hebdo = out.jours_hebdo.map(Number).filter((n) => !Number.isNaN(n) && n > 0);
    out.temps_travail = out.temps_travail
      .filter((t) => String(t.name || "").trim())
      .map((t) => ({ name: String(t.name).trim(), rtt: Number(t.rtt) || 0 }));
    out.durees_rtt = out.temps_travail;
    out.codes = out.codes
      .filter((x) => String(x.code || "").trim())
      .map((x) => ({
        code: String(x.code).trim(),
        libelle: String(x.libelle || x.code).trim(),
        color: (/^[0-9A-Fa-f]{6}$/.test(String(x.color || "")) ? String(x.color) : "F2F2F2").toUpperCase(),
        in_n: !!x.in_n,
        in_s: !!x.in_s,
      }));
    out.jours_feries = out.jours_feries
      .filter((x) => x && x[0])
      .map((x) => [x[0], String(x[1] || "").trim()]);
    out.vacances_scolaires = (out.vacances_scolaires || [])
      .filter((x) => x && x[0] && x[1])
      .map((x) => [x[0], x[1], String(x[2] || "").trim()]);

    try {
      await api("/api/settings", { method: "PUT", body: JSON.stringify(out) });
      state.settings = await api("/api/settings");
      $("#set-msg").innerHTML = `<div class="form-ok">Paramétrage enregistré.</div>`;
      toast("Paramétrage enregistré");
    } catch (err) {
      $("#set-msg").innerHTML = `<div class="form-error">${esc(err.message)}</div>`;
    }
  };

  const reimportSettings = async () => {
    if (!confirm("Réimporter les paramètres depuis le classeur Excel ? Vos modifications seront perdues.")) return;
    try {
      await api("/api/settings/reimport", { method: "POST" });
      state.settings = await api("/api/settings");
      toast("Paramètres réimportés depuis le classeur");
      viewSettings();
    } catch (err) {
      $("#set-msg").innerHTML = `<div class="form-error">${esc(err.message)}</div>`;
    }
  };

  // Rendu complet : reconstruit les tableaux puis réattache tous les écouteurs
  // (le bouton Enregistrer doit être réattaché après chaque ajout/suppression).
  const render = () => {
    build();
    drawMatrix();
    bindAll();
    $("#set-save").addEventListener("click", saveSettings);
    $("#set-reimport").addEventListener("click", reimportSettings);
  };

  render();
}

/* ==========================================================================
   Paramétrage : menu général à sous-sections (calcul, accès, e-mails, journaux)
   ========================================================================== */
const ADMIN_MENU = [
  { group: "Congés", items: [["calcul", "Calcul et calendrier"]] },
  { group: "Accès", items: [["users", "Utilisateurs"], ["apikeys", "Clés API"], ["connexions", "Journal des connexions"]] },
  { group: "E-mails", items: [["emails", "Expéditeur et pied de page"], ["messages", "Messages automatiques"], ["journal-emails", "Journal des e-mails"]] },
  { group: "Intégrations", items: [["sedit-rh", "API Sedit RH"], ["organisation-rh", "Organisation RH"], ["matricules", "Matricules"]] },
];

/* Conteneur du contenu : la zone de la section en cours dans le Paramétrage, sinon la page entière. */
function contentEl() { return $("#admin-body") || $("#content"); }

function viewAdmin(hash) {
  if (!state.user.admin) { location.hash = "#/dashboard"; return; }
  const known = ADMIN_MENU.flatMap((g) => g.items.map((i) => i[0]));
  const parts = hash.split("?")[0].split("/");
  let section = parts[2] || "";
  const arg = parts[3] || "";
  if (!known.includes(section)) section = "calcul";
  const menu = ADMIN_MENU.map((g) => `
    <div class="admin-group">${esc(g.group)}</div>
    ${g.items.map(([key, label]) => `<a href="#/settings/${key}" class="${key === section ? "active" : ""}">${esc(label)}</a>`).join("")}`).join("");
  $("#content").innerHTML = `
    <h1>Paramétrage</h1>
    <div class="admin-layout">
      <nav class="admin-menu">${menu}</nav>
      <section id="admin-body"><p>Chargement…</p></section>
    </div>`;
  const run = {
    calcul: () => viewSettings(), users: () => viewUsers(), apikeys: () => viewApiKeys(),
    connexions: viewLoginLogs, emails: viewMailLayout, messages: () => viewMailMessages(arg), "journal-emails": viewMailLogs, "sedit-rh": viewSeditRh, "organisation-rh": viewOrgRh, matricules: viewMatricules,
  }[section];
  Promise.resolve(run()).catch((e) => { $("#admin-body").innerHTML = `<div class="form-error">${esc(e.message)}</div>`; });
}

/* ---- aides communes aux journaux ---- */
function fmtDateTime(s) {
  const m = /^(\d{4})-(\d{2})-(\d{2})[ T](\d{2}:\d{2}:\d{2})/.exec(s || "");
  return m ? `${m[3]}/${m[2]}/${m[1]} ${m[4]}` : esc(s || "");
}

function renderPager(el, total, limit, offset, go) {
  const from = total ? offset + 1 : 0, to = Math.min(offset + limit, total);
  el.innerHTML = `<span class="muted">${from}–${to} sur ${total}</span>
    <button class="btn btn-small" data-p="prev" ${offset <= 0 ? "disabled" : ""}>← Précédent</button>
    <button class="btn btn-small" data-p="next" ${offset + limit >= total ? "disabled" : ""}>Suivant →</button>`;
  el.querySelector('[data-p="prev"]').addEventListener("click", () => go(Math.max(0, offset - limit)));
  el.querySelector('[data-p="next"]').addEventListener("click", () => go(offset + limit));
}

async function retentionControl(el, field, label) {
  const r = await api("/api/admin/log-retention");
  el.innerHTML = `<label class="inline">${esc(label)} <input type="number" id="ret-days" min="30" max="3650" value="${r[field]}" style="width:90px"> jours
    <button class="btn btn-small" id="ret-save">Enregistrer</button></label>
    <span class="muted"> Les entrées plus anciennes sont supprimées automatiquement (RGPD).</span>`;
  $("#ret-save").addEventListener("click", async () => {
    try {
      await api("/api/admin/log-retention", { method: "PUT", body: JSON.stringify({ ...r, [field]: Number($("#ret-days").value) }) });
      toast("Durée de conservation enregistrée");
    } catch (e) { toast(e.message, true); }
  });
}

/* ---- Journal des connexions ---- */
const EVENT_LABELS = { connexion: "Connexion", echec: "Échec", deconnexion: "Déconnexion", en_tant_que: "« En tant que » (début)", fin_en_tant_que: "« En tant que » (fin)" };
const REASON_LABELS = { inconnu: "Identifiant inconnu", mot_de_passe: "Mot de passe incorrect", desactive: "Compte désactivé", service_ad: "Service AD indisponible", limite: "Trop de tentatives" };
const METHOD_LABELS = { local: "Local", ad: "Active Directory", secours: "Secours (local)" };

async function viewLoginLogs() {
  const body = contentEl();
  body.innerHTML = `
    <h2>Journal des connexions</h2>
    <p class="muted">Qui s'est connecté, quand et depuis quelle adresse (connexions, échecs, déconnexions, « se connecter en tant que »).</p>
    <div class="log-filters">
      <input id="ll-q" placeholder="Identifiant ou adresse IP…">
      <select id="ll-event"><option value="">Tous les événements</option>${Object.entries(EVENT_LABELS).map(([k, v]) => `<option value="${k}">${esc(v)}</option>`).join("")}</select>
      <select id="ll-ok"><option value="">Succès et échecs</option><option value="1">Succès</option><option value="0">Échecs</option></select>
      <label class="inline">Du <input type="date" id="ll-from"></label>
      <label class="inline">au <input type="date" id="ll-to"></label>
      <button class="btn btn-small" id="ll-go">Filtrer</button>
    </div>
    <table class="data"><thead><tr><th>Date</th><th>Événement</th><th>Identifiant</th><th>Résultat</th><th>Méthode</th><th>Adresse IP</th><th>Navigateur</th></tr></thead>
      <tbody id="ll-body"><tr><td colspan="7" class="muted">Chargement…</td></tr></tbody></table>
    <div id="ll-pager" class="pager"></div>
    <div id="ll-ret" class="log-retention"></div>`;
  let offset = 0;
  const limit = 50;
  const load = async (off = 0) => {
    offset = off;
    const qs = new URLSearchParams({ limit, offset });
    for (const [id, k] of [["ll-q", "q"], ["ll-event", "event"], ["ll-ok", "success"], ["ll-from", "from"], ["ll-to", "to"]]) {
      const v = $("#" + id).value; if (v) qs.set(k, v);
    }
    const r = await api("/api/admin/login-logs?" + qs);
    $("#ll-body").innerHTML = r.items.map((l) => `<tr class="${l.success ? "" : "log-fail"}">
      <td>${fmtDateTime(l.at)}</td><td>${esc(EVENT_LABELS[l.event] || l.event)}</td><td>${esc(l.login || "—")}</td>
      <td>${l.success ? "OK" : "<b>Refusé</b>"}${l.reason && l.event !== "en_tant_que" && l.event !== "fin_en_tant_que" ? " — " + esc(REASON_LABELS[l.reason] || l.reason) : (l.reason ? " " + esc(l.reason) : "")}</td>
      <td>${esc(METHOD_LABELS[l.method] || l.method || "—")}</td><td>${esc(l.ip || "—")}</td>
      <td class="muted" title="${esc(l.user_agent)}">${esc((l.user_agent || "").slice(0, 40))}</td></tr>`).join("")
      || `<tr><td colspan="7" class="muted">Aucune entrée.</td></tr>`;
    renderPager($("#ll-pager"), r.total, r.limit, r.offset, load);
  };
  $("#ll-go").addEventListener("click", () => load(0));
  $("#ll-q").addEventListener("keydown", (e) => { if (e.key === "Enter") load(0); });
  retentionControl($("#ll-ret"), "connexions_jours", "Conserver le journal des connexions");
  await load(0);
}

/* ---- Journal des e-mails ---- */
const MAIL_STATUS = { envoye: "Envoyé", echec: "Échec", non_envoye: "Non envoyé" };

async function viewMailLogs() {
  const body = contentEl();
  body.innerHTML = `
    <h2>Journal des e-mails</h2>
    <p class="muted">Les e-mails envoyés (ou tentés) par l'application : destinataire, objet, résultat et texte envoyé.</p>
    <div class="log-filters">
      <input id="ml-q" placeholder="Destinataire ou objet…">
      <select id="ml-status"><option value="">Tous les statuts</option>${Object.entries(MAIL_STATUS).map(([k, v]) => `<option value="${k}">${esc(v)}</option>`).join("")}</select>
      <select id="ml-tpl"><option value="">Tous les messages</option></select>
      <label class="inline">Du <input type="date" id="ml-from"></label>
      <label class="inline">au <input type="date" id="ml-to"></label>
      <button class="btn btn-small" id="ml-go">Filtrer</button>
    </div>
    <table class="data"><thead><tr><th>Date</th><th>Destinataire</th><th>Objet</th><th>Message</th><th>Statut</th><th></th></tr></thead>
      <tbody id="ml-body"><tr><td colspan="6" class="muted">Chargement…</td></tr></tbody></table>
    <div id="ml-pager" class="pager"></div>
    <div id="ml-ret" class="log-retention"></div>`;
  const limit = 50;
  let templates = null;
  const load = async (off = 0) => {
    const qs = new URLSearchParams({ limit, offset: off });
    for (const [id, k] of [["ml-q", "q"], ["ml-status", "status"], ["ml-tpl", "template"], ["ml-from", "from"], ["ml-to", "to"]]) {
      const v = $("#" + id).value; if (v) qs.set(k, v);
    }
    const r = await api("/api/admin/mail-logs?" + qs);
    if (!templates) {
      templates = r.templates;
      $("#ml-tpl").innerHTML += Object.entries(templates).map(([k, v]) => `<option value="${esc(k)}">${esc(v)}</option>`).join("");
    }
    $("#ml-body").innerHTML = r.items.map((m) => `<tr class="${m.status === "envoye" ? "" : "log-fail"}">
      <td>${fmtDateTime(m.at)}</td><td>${esc(m.to_addr || "—")}</td><td>${esc(m.subject)}</td>
      <td>${esc(templates[m.template] || m.template || "—")}</td>
      <td>${esc(MAIL_STATUS[m.status] || m.status)}${m.error ? `<br><span class="muted">${esc(m.error)}</span>` : ""}</td>
      <td><button class="btn btn-small" data-id="${m.id}">Voir</button></td></tr>`).join("")
      || `<tr><td colspan="6" class="muted">Aucun e-mail.</td></tr>`;
    $("#ml-body").querySelectorAll("button[data-id]").forEach((b) => b.addEventListener("click", async () => {
      const m = await api("/api/admin/mail-logs/" + b.dataset.id);
      showTextModal(`${m.subject}`, `À : ${m.to_addr}\nDate : ${fmtDateTime(m.at).replace(/&[a-z#0-9]+;/g, "")}\nStatut : ${MAIL_STATUS[m.status] || m.status}${m.error ? " (" + m.error + ")" : ""}\n\n${m.body}`);
    }));
    renderPager($("#ml-pager"), r.total, r.limit, r.offset, load);
  };
  $("#ml-go").addEventListener("click", () => load(0));
  $("#ml-q").addEventListener("keydown", (e) => { if (e.key === "Enter") load(0); });
  retentionControl($("#ml-ret"), "emails_jours", "Conserver le journal des e-mails");
  await load(0);
}

function showTextModal(title, text) {
  const wrap = document.createElement("div");
  wrap.className = "modal";
  wrap.innerHTML = `<div class="modal-card" style="max-width:720px"><h3>${esc(title)}</h3>
    <pre class="mail-body"></pre><div class="modal-actions"><button class="btn btn-primary">Fermer</button></div></div>`;
  wrap.querySelector("pre").textContent = text;
  wrap.querySelector("button").addEventListener("click", () => wrap.remove());
  document.body.appendChild(wrap);
}

/* Adresse du test d'envoi : dernière saisie (mémorisée dans le navigateur), sinon l'e-mail du compte. */
function testAddress() {
  try { return localStorage.getItem("suivi_test_mail") || state.user.email || ""; } catch (_) { return state.user.email || ""; }
}
function rememberTestAddress(v) { try { if (v) localStorage.setItem("suivi_test_mail", v); } catch (_) { /* facultatif */ } }

/* ---- Sedit RH : matricules des agents de la base ---- */
const MATRICULE_STATUS = {
  certain: ["Correspondance certaine", "ok"], ambigu: ["Plusieurs agents du même nom", "warn"],
  introuvable: ["Introuvable dans Sedit RH", "off"], deja_pris: ["Matricule déjà attribué", "warn"],
};

async function viewMatricules() {
  const body = contentEl();
  body.innerHTML = `<h2>Matricules des agents de la base</h2><p class="muted">Recherche, dans Sedit RH, des agents déjà présents dans l'application (rapprochement par nom et prénom)…</p>`;
  const r = await api("/api/admin/rh/matricules");
  const certain = r.items.filter((i) => i.status === "certain");
  const row = (i) => {
    const [label, cls] = MATRICULE_STATUS[i.status];
    const info = i.status === "certain" || i.status === "deja_pris"
      ? `${esc(i.matricule)}<br><span class="muted">${esc(i.rh.direction)}${i.rh.service && i.rh.service !== i.rh.direction ? " › " + esc(i.rh.service) : ""}${i.rh.secteur ? " › " + esc(i.rh.secteur) : ""}</span>`
      : i.status === "ambigu"
        ? i.candidates.map((c) => `<span class="muted">${esc(c.matricule)} — ${esc(c.service || c.direction)}</span>`).join("<br>")
        : '<span class="muted">À saisir à la main dans Utilisateurs</span>';
    return `<tr class="${i.status === "certain" ? "" : "row-off"}">
      <td>${i.status === "certain" ? `<input type="checkbox" class="mt-check" data-uid="${i.agent_user_id}" data-m="${esc(i.matricule)}" checked>` : ""}</td>
      <td>${esc(i.login)}</td><td><b>${esc(i.nom)}</b> ${esc(i.prenom)}</td><td>${info}</td>
      <td><span class="chip chip-${cls}">${esc(label)}</span>${i.holder ? ` <span class="muted">(${esc(i.holder)})</span>` : ""}</td></tr>`;
  };
  body.innerHTML = `
    <h2>Matricules des agents de la base</h2>
    <p class="muted">Pour chaque agent de l'application <b>sans matricule</b>, recherche dans Sedit RH (agents en poste) par nom et prénom. Seules les correspondances <b>certaines</b>
      (un seul agent de ce nom) sont proposées ; décochez ce que vous ne voulez pas appliquer. Les matricules déjà renseignés ne sont jamais modifiés.</p>
    <div class="log-filters">
      <span><b>${r.counts.certain}</b> certaine(s)</span><span><b>${r.counts.ambigu}</b> ambiguë(s)</span>
      <span><b>${r.counts.introuvable}</b> introuvable(s)</span><span><b>${r.counts.deja_pris}</b> déjà attribuée(s)</span>
    </div>
    ${r.items.length ? `<table class="data"><thead><tr><th></th><th>Compte</th><th>Agent</th><th>Matricule Sedit RH</th><th>Résultat</th></tr></thead>
      <tbody>${r.items.map(row).join("")}</tbody></table>
      <div style="margin-top:12px;display:flex;gap:8px;align-items:center">
        <button class="btn btn-primary" id="mt-apply" ${certain.length ? "" : "disabled"}>Appliquer les matricules cochés</button>
        <button class="btn btn-small" id="mt-toggle" ${certain.length ? "" : "disabled"}>Tout décocher</button><span id="mt-count" class="muted"></span></div>`
      : '<p class="muted">Tous les agents de la base ont déjà un matricule.</p>'}`;
  if (!r.items.length) return;
  const boxes = () => [...body.querySelectorAll(".mt-check")];
  const count = () => { const n = boxes().filter((b) => b.checked).length; $("#mt-count").textContent = n + " sélectionné(s)"; $("#mt-apply").disabled = !n; };
  boxes().forEach((b) => b.addEventListener("change", count));
  $("#mt-toggle").addEventListener("click", (e) => {
    const all = boxes().every((b) => b.checked);
    boxes().forEach((b) => { b.checked = !all; });
    e.target.textContent = all ? "Tout cocher" : "Tout décocher"; count();
  });
  count();
  $("#mt-apply").addEventListener("click", async () => {
    try {
      const items = boxes().filter((b) => b.checked).map((b) => ({ agent_user_id: Number(b.dataset.uid), matricule: b.dataset.m }));
      const res = await api("/api/admin/rh/matricules/apply", { method: "POST", body: JSON.stringify({ items }) });
      toast(`${res.applied} matricule(s) enregistré(s)` + (res.refused.length ? `, ${res.refused.length} refusé(s)` : ""), res.refused.length > 0 && !res.applied);
      viewMatricules();
    } catch (e) { toast(e.message, true); }
  });
}

/* ---- Sedit RH : organisation (Direction > Service > Secteur > Agents) et création d'agents ---- */
const LEVEL_LABEL = { direction: "Direction", service: "Service", secteur: "Secteur" };

async function viewOrgRh() {
  const body = contentEl();
  body.innerHTML = `<h2>Organisation Sedit RH</h2><p class="muted">Lecture de l'organisation et des agents en poste dans Sedit RH…</p>`;
  let data = await api("/api/admin/rh/organisation");
  const selected = new Set(), open = new Set();
  const index = new Map();
  let nextId = 0, filterText = "", mode = "all";
  const indexTree = (nodes, path) => nodes.forEach((n) => { n._id = "n" + (nextId++); n._path = path; index.set(n._id, n); indexTree(n.children, path + 1); });

  const matches = (a) => (mode === "all" || (mode === "missing" ? !a.in_app : a.in_app)) &&
    (!filterText || (a.nom + " " + a.prenom + " " + a.matricule).toLowerCase().includes(filterText));
  const visibleAgents = (n) => [...n.agents.filter(matches), ...n.children.flatMap(visibleAgents)];
  const missingOf = (n) => [...n.agents.filter((a) => !a.in_app && matches(a)), ...n.children.flatMap(missingOf)];

  const nodeHtml = (n) => {
    const shown = visibleAgents(n);
    if (!shown.length) return "";
    const isOpen = open.has(n._id) || (filterText && shown.length <= 300);
    const miss = missingOf(n);
    const acct = n.account ? `<span class="chip chip-ok" title="Compte valideur de l'application">compte : ${esc(n.account.login)}</span>` : '<span class="chip chip-off">pas de compte valideur</span>';
    const kids = isOpen ? n.children.map(nodeHtml).join("") + (n.agents.some(matches) ? `<table class="data org-agents"><tbody>${n.agents.filter(matches).map((a) => `
      <tr><td style="width:28px"><input type="checkbox" class="org-agent" data-m="${esc(a.matricule)}" ${a.in_app ? "disabled" : ""}></td>
        <td style="width:90px">${esc(a.matricule)}</td><td><b>${esc(a.nom)}</b> ${esc(a.prenom)}</td><td class="muted">${esc(a.fonction)}</td><td class="muted">${esc(a.statut)}</td>
        <td>${a.in_app ? `<span class="chip chip-ok">dans l'application (${esc(a.login)})</span>` : '<span class="chip chip-off">absent</span>'}</td></tr>`).join("")}</tbody></table>` : "") : "";
    return `<div class="org-node lv-${n.level}" data-id="${n._id}">
      <div class="org-head"><button type="button" class="org-toggle" data-id="${n._id}">${isOpen ? "▾" : "▸"}</button>
        <input type="checkbox" class="org-check" data-id="${n._id}" ${miss.length ? "" : "disabled"}>
        <span class="lv-tag">${LEVEL_LABEL[n.level]}</span> <b>${esc(n.libelle)}</b>
        <span class="muted">${shown.length} agent(s)${miss.length ? " · " + miss.length + " absent(s) de l'application" : ""}</span> ${acct}</div>
      <div class="org-body ${isOpen ? "" : "hidden"}">${kids}</div></div>`;
  };

  const refreshChecks = () => {
    body.querySelectorAll(".org-agent").forEach((c) => { c.checked = selected.has(c.dataset.m); });
    body.querySelectorAll(".org-check").forEach((c) => {
      const miss = missingOf(index.get(c.dataset.id)), n = miss.filter((a) => selected.has(a.matricule)).length;
      c.checked = miss.length > 0 && n === miss.length; c.indeterminate = n > 0 && n < miss.length;
    });
    $("#org-selected").textContent = selected.size ? selected.size + " agent(s) sélectionné(s)" : "";
    $("#org-create").disabled = !selected.size;
  };

  const render = () => {
    const html = data.tree.map(nodeHtml).join("");
    $("#org-tree").innerHTML = html || '<p class="muted">Aucun agent ne correspond.</p>';
    $("#org-tree").querySelectorAll(".org-toggle").forEach((b) => b.addEventListener("click", () => {
      open.has(b.dataset.id) ? open.delete(b.dataset.id) : open.add(b.dataset.id); render();
    }));
    $("#org-tree").querySelectorAll(".org-check").forEach((c) => c.addEventListener("change", () => {
      const miss = missingOf(index.get(c.dataset.id));
      miss.forEach((a) => { c.checked ? selected.add(a.matricule) : selected.delete(a.matricule); });
      refreshChecks();
    }));
    $("#org-tree").querySelectorAll(".org-agent").forEach((c) => c.addEventListener("change", () => {
      c.checked ? selected.add(c.dataset.m) : selected.delete(c.dataset.m); refreshChecks();
    }));
    refreshChecks();
  };

  const draw = () => {
    indexTree(data.tree, 0);
    body.innerHTML = `
      <h2>Organisation Sedit RH</h2>
      <p class="muted">Organisation et agents <b>en poste</b> dans Sedit RH, présentés comme la hiérarchie de l'application (Direction › Service › Secteur › Agent).
        Cochez des agents, un secteur, un service ou une direction entière, puis créez-les dans l'application : seuls les agents <b>absents</b> sont proposés.</p>
      <div class="log-filters">
        <input id="org-q" placeholder="Rechercher (nom, prénom, matricule)…">
        <select id="org-mode"><option value="all">Tous les agents</option><option value="missing">Absents de l'application</option><option value="present">Déjà dans l'application</option></select>
        <button class="btn btn-small" id="org-refresh">Actualiser depuis Sedit RH</button>
        <span class="muted"><b>${data.total}</b> agents · <b>${data.missing}</b> absents de l'application</span>
      </div>
      <div class="org-bar"><span id="org-selected" class="muted"></span>
        <button class="btn btn-small" id="org-clear">Tout désélectionner</button>
        <button class="btn btn-primary" id="org-create" disabled>Créer les agents sélectionnés…</button></div>
      <div id="org-tree" class="org-tree"></div>`;
    $("#org-q").addEventListener("input", (e) => { filterText = e.target.value.trim().toLowerCase(); render(); });
    $("#org-mode").addEventListener("change", (e) => { mode = e.target.value; render(); });
    $("#org-clear").addEventListener("click", () => { selected.clear(); refreshChecks(); });
    $("#org-refresh").addEventListener("click", async () => {
      try { data = await api("/api/admin/rh/organisation?refresh=1"); index.clear(); nextId = 0; draw(); toast("Données Sedit RH actualisées"); }
      catch (e) { toast(e.message, true); }
    });
    $("#org-create").addEventListener("click", () => openRhImportModal([...selected], () => viewOrgRh()));
    render();
  };
  draw();
}

/* Fenêtre de création : options, aperçu (rien n'est écrit), confirmation, résultat. */
async function openRhImportModal(matricules, done) {
  const users = (await api("/api/users")).filter((u) => u.role !== "agent" && u.actif);
  const wrap = document.createElement("div");
  wrap.className = "modal";
  wrap.innerHTML = `<div class="modal-card" style="max-width:940px;width:94vw;max-height:88vh;overflow:auto">
    <h3>Créer ${matricules.length} agent(s) depuis Sedit RH</h3>
    <div id="ri-error" class="form-error hidden"></div>
    <div id="ri-form">
      <label>Année des fiches <input type="number" id="ri-year" min="2000" max="2100" value="${state.year}" style="width:100px"></label>
      <label class="inline"><input type="checkbox" id="ri-units" checked> Créer les comptes valideurs manquants de l'organisation (direction, service, secteur), sous le compte du même nom s'il existe</label>
      <label>Propriétaire par défaut (si un agent n'a pas de compte d'unité)
        <select id="ri-owner"><option value="">— aucun —</option>${users.map((u) => `<option value="${u.id}">${esc(u.nom || u.login)} (${esc(u.login)})</option>`).join("")}</select></label>
      <label class="inline"><input type="checkbox" id="ri-ad" checked> Chercher l'e-mail et l'identifiant dans l'annuaire Active Directory (si un seul compte correspond au nom)</label>
      <p class="muted">Chaque agent est créé avec son compte et sa fiche, rattachés au compte de son unité ; le matricule est repris de Sedit RH. Un aperçu précède toujours la création.</p>
      <div class="modal-actions"><button class="btn" id="ri-cancel">Annuler</button><button class="btn btn-primary" id="ri-preview">Prévisualiser</button></div>
    </div>
    <div id="ri-result"></div></div>`;
  document.body.appendChild(wrap);
  const close = () => wrap.remove();
  const payload = () => ({ matricules, year: Number($("#ri-year").value), create_units: $("#ri-units").checked,
    default_owner_id: $("#ri-owner").value ? Number($("#ri-owner").value) : null, use_ad: $("#ri-ad").checked });
  const err = (m) => { const e = $("#ri-error"); e.textContent = m; e.classList.toggle("hidden", !m); };
  $("#ri-cancel").addEventListener("click", close);
  $("#ri-preview").addEventListener("click", async () => {
    err(""); $("#ri-result").innerHTML = '<p class="muted">Préparation (recherche dans l\'annuaire en cours)…</p>';
    try {
      const p = await api("/api/admin/rh/import/preview", { method: "POST", body: JSON.stringify(payload()) });
      const todo = p.items.filter((i) => i.status === "a_creer");
      $("#ri-result").innerHTML = `
        <p><b>${p.counts.a_creer}</b> agent(s) à créer · ${p.counts.existe} déjà présent(s) · ${p.counts.ignore} ignoré(s) · <b>${p.units_new.length}</b> compte(s) d'unité à créer</p>
        ${p.units_new.length ? `<p class="muted">Comptes d'unité : ${p.units_new.map((u) => `${LEVEL_LABEL[u.level]} « ${esc(u.libelle)} »`).join(" ; ")}</p>` : ""}
        <table class="data"><thead><tr><th>Matricule</th><th>Agent</th><th>Propriétaire</th><th>E-mail (AD)</th><th>Résultat</th></tr></thead><tbody>
          ${p.items.map((i) => `<tr class="${i.status === "a_creer" ? "" : "row-off"}"><td>${esc(i.matricule)}</td><td>${esc(i.nom || "")} ${esc(i.prenom || "")}</td>
            <td>${esc(i.owner || "")}</td><td>${i.status === "a_creer" ? (i.email ? esc(i.email) : '<span class="muted">à renseigner</span>') : ""}</td>
            <td>${i.status === "a_creer" ? "À créer" : `<span class="muted">${esc(i.reason)}</span>`}</td></tr>`).join("")}</tbody></table>
        <div class="modal-actions"><button class="btn" id="ri-back">Modifier les options</button>
          <button class="btn btn-primary" id="ri-go" ${todo.length ? "" : "disabled"}>Créer ${todo.length} agent(s)</button></div>`;
      $("#ri-back").addEventListener("click", () => { $("#ri-result").innerHTML = ""; });
      $("#ri-go").addEventListener("click", async () => {
        $("#ri-go").disabled = true; $("#ri-go").textContent = "Création…";
        try {
          const r = await api("/api/admin/rh/import", { method: "POST", body: JSON.stringify(payload()) });
          $("#ri-form").classList.add("hidden");
          $("#ri-result").innerHTML = `<p><b>${r.created.length}</b> agent(s) créé(s) · ${r.units_created.length} compte(s) d'unité créé(s) · ${r.skipped.length} ignoré(s).</p>
            <p class="muted">${r.created.filter((c) => !c.email).length} agent(s) sans e-mail (à renseigner dans leur fiche) ; ${r.created.filter((c) => !c.ad_login).length} sans identifiant AD
              (à renseigner dans Paramétrage > Utilisateurs pour qu'ils puissent se connecter). Les comptes d'unité sont à attribuer à leurs responsables.</p>
            <div class="modal-actions"><button class="btn btn-primary" id="ri-ok">Fermer</button></div>`;
          $("#ri-ok").addEventListener("click", () => { close(); done(); });
          toast(r.created.length + " agent(s) créé(s)");
        } catch (e) { err(e.message); $("#ri-go").disabled = false; $("#ri-go").textContent = "Réessayer"; }
      });
    } catch (e) { $("#ri-result").innerHTML = ""; err(e.message); }
  });
}

/* ---- API Sedit RH : test de connexion et nombre d'agents ---- */
async function viewSeditRh() {
  const body = contentEl();
  const info = await api("/api/admin/sedit-rh");
  body.innerHTML = `
    <h2>API Sedit RH</h2>
    <p class="muted">Connexion à l'API Sedit RH (agents et organisation de la Ville, lecture seule). L'adresse et la clé se règlent dans le fichier de configuration <code>.env</code>
      (<code>SEDITRH_API_URL</code>, <code>SEDITRH_API_KEY</code>) ; la clé n'est jamais affichée.</p>
    <div class="card" style="margin-bottom:14px">
      <h3>Configuration</h3>
      <table class="var-table"><tbody>
        <tr><td>Adresse</td><td>${info.url ? `<code>${esc(info.url)}</code>` : '<span class="muted">non renseignée</span>'}</td></tr>
        <tr><td>Clé d'accès</td><td>${info.key_set ? "renseignée" : '<span class="muted">non renseignée</span>'}</td></tr>
      </tbody></table>
      <div style="margin-top:10px"><button class="btn btn-primary" id="sr-test" ${info.configured ? "" : "disabled"}>Tester la connexion et compter les agents</button></div>
    </div>
    <div id="sr-result"></div>`;
  $("#sr-test").addEventListener("click", async () => {
    const out = $("#sr-result");
    out.innerHTML = '<div class="card"><p class="muted">Interrogation de l\'API Sedit RH…</p></div>';
    try {
      const r = await api("/api/admin/sedit-rh/test", { method: "POST" });
      if (!r.ok) {
        out.innerHTML = `<div class="card warn-banner"><h3>Connexion en échec</h3><p>${esc(r.error)}</p>
          <p class="muted">${r.latency_ms} ms${r.status ? " · HTTP " + r.status : ""}</p></div>`;
        return;
      }
      const max = Math.max(...r.par_statut.map((s) => s.effectif), 1);
      out.innerHTML = `
        <div class="card ok-banner" style="margin-bottom:14px"><h3>Connexion réussie</h3>
          <p class="muted">API Sedit RH joignable, clé acceptée — ${r.latency_ms} ms.</p>
          <p style="font-size:28px;margin:6px 0"><b>${r.total_agents.toLocaleString("fr-FR")}</b> <span style="font-size:14px">agents en poste</span></p></div>
        <div class="card"><h3>Répartition par statut</h3>
          <table class="data"><thead><tr><th>Code</th><th>Statut</th><th style="text-align:right">Agents</th><th style="width:40%"></th></tr></thead><tbody>
            ${r.par_statut.map((s) => `<tr><td>${esc(s.code)}</td><td>${esc(s.libelle)}</td><td style="text-align:right">${s.effectif.toLocaleString("fr-FR")}</td>
              <td><div class="bar"><span style="width:${Math.round((s.effectif / max) * 100)}%"></span></div></td></tr>`).join("")}
          </tbody></table></div>`;
    } catch (e) { out.innerHTML = `<div class="form-error">${esc(e.message)}</div>`; }
  });
}

/* ---- E-mails : activation, expéditeur, signature et pied de page ---- */
function renderMailSwitch(el, s) {
  const on = s.enabled;
  const detail = !s.apm_configured
    ? "L'API centrale de la Ville (APM) n'est pas configurée dans <code>.env</code> : aucun e-mail ne peut partir, test compris."
    : on ? "Les e-mails automatiques partent par l'API centrale de la Ville."
      : "Les e-mails automatiques ne partent pas : ils sont seulement inscrits au journal. Les <b>messages de test partent quand même</b>.";
  el.innerHTML = `<div class="card ${on && s.apm_configured ? "ok-banner" : "warn-banner"}">
    <label class="inline"><input type="checkbox" id="mail-switch" ${on ? "checked" : ""}>
      <b>Envoi automatique des e-mails : ${on ? "activé" : "désactivé"}</b></label>
    <div class="muted" style="margin-top:4px">${detail}</div></div>`;
  $("#mail-switch").addEventListener("change", async (e) => {
    try {
      const r = await api("/api/admin/mail-settings", { method: "PUT", body: JSON.stringify({ enabled: e.target.checked }) });
      toast(r.enabled ? "Envoi des e-mails activé" : "Envoi des e-mails désactivé");
      renderMailSwitch(el, r);
    } catch (err) { e.target.checked = !e.target.checked; toast(err.message, true); }
  });
}

/* Aperçu du MESSAGE seul : l'en-tête et le pied de page sont ajoutés par l'API centrale (pas prévisualisés ici). */
function previewFrame(el, p) {
  el.innerHTML = `<div class="muted" style="margin:6px 0">Aperçu du message avec des données d'exemple — l'en-tête et le pied de page sont ajoutés par l'API centrale.</div>
    <div class="muted">Objet : <b>${esc(p.subject)}</b></div>
    <iframe sandbox class="mail-preview" title="Aperçu du message"></iframe>`;
  el.querySelector("iframe").srcdoc = `<body style="font-family:Arial,sans-serif;font-size:14px;color:#222;margin:12px">${p.html}</body>`;
}

async function viewMailLayout() {
  const body = contentEl();
  const s = await api("/api/admin/mail-settings");
  const L = s.layout;
  const f = (id, label, val, extra = "") => `<label>${label}<input id="ml-${id}" value="${esc(val)}" ${extra}></label>`;
  body.innerHTML = `
    <h2>Expéditeur et pied de page</h2>
    <p class="muted">Réglages communs à <b>tous</b> les e-mails automatiques ; le texte de chaque message se règle dans « Messages automatiques ».
      L'expéditeur et le pied de page sont transmis à l'API centrale de la Ville, qui ajoute son en-tête institutionnel.</p>
    <div id="mail-switch-zone"></div>
    <div class="card" style="margin-bottom:14px"><h3>Expéditeur</h3>
      <div class="params-grid">${f("from_name", "Nom de l'expéditeur", L.from_name, 'placeholder="(par défaut de l\'API centrale)"')}
        ${f("from_email", "Adresse de l'expéditeur", L.from_email, 'placeholder="(par défaut de l\'API centrale)"')}</div></div>
    <div class="card" style="margin-bottom:14px"><h3>Signature</h3>
      <label>Ajoutée en bas du texte de chaque message<textarea id="ml-signature" rows="3">${esc(L.signature)}</textarea></label></div>
    <div class="card" style="margin-bottom:14px"><h3>Pied de page</h3>
      <div class="params-grid">${f("footer1", "Ligne 1", L.footer1)}${f("footer2", "Ligne 2", L.footer2)}${f("footer3", "Ligne 3", L.footer3)}
        <label>Couleur du pied de page<span class="color-pair"><input type="color" id="ml-footer_color-pick" value="${esc(L.footer_color)}"><input id="ml-footer_color" value="${esc(L.footer_color)}" maxlength="7" style="width:90px"></span></label></div></div>
    <div style="display:flex;gap:8px;flex-wrap:wrap;align-items:center">
      <button class="btn btn-primary" id="ml-save">Enregistrer</button>
      <span class="muted">Envoyer un message de test à</span><input id="ml-test-to" type="email" placeholder="adresse e-mail" value="${esc(testAddress())}" style="width:240px">
      <button class="btn" id="ml-test">Envoyer le test</button>
    </div>`;
  renderMailSwitch($("#mail-switch-zone"), s);
  $("#ml-footer_color-pick").addEventListener("input", (e) => { $("#ml-footer_color").value = e.target.value.toUpperCase(); });
  $("#ml-footer_color").addEventListener("input", (e) => { if (/^#[0-9A-Fa-f]{6}$/.test(e.target.value)) $("#ml-footer_color-pick").value = e.target.value; });
  const collect = () => Object.fromEntries(["from_name", "from_email", "signature", "footer1", "footer2", "footer3", "footer_color"].map((k) => [k, $("#ml-" + k).value]));
  $("#ml-save").addEventListener("click", async () => {
    try { await api("/api/admin/mail-settings", { method: "PUT", body: JSON.stringify({ layout: collect() }) }); toast("Réglages enregistrés"); }
    catch (e) { toast(e.message, true); }
  });
  $("#ml-test").addEventListener("click", async () => {
    try {
      await api("/api/admin/mail-settings", { method: "PUT", body: JSON.stringify({ layout: collect() }) });  // le test utilise les réglages saisis
      const to = $("#ml-test-to").value.trim();
      if (!to) { toast("Saisissez l'adresse e-mail qui recevra le test", true); return; }
      rememberTestAddress(to);
      const r = await api("/api/admin/mail-settings/test", { method: "POST", body: JSON.stringify({ to }) });
      toast(r.ok ? "Message de test envoyé à " + r.to : "Non envoyé : " + r.error, !r.ok);
    } catch (e) { toast(e.message, true); }
  });
}

/* ---- E-mails : messages automatiques (liste à gauche, contenu à droite) ---- */
async function viewMailMessages(selected) {
  const body = contentEl();
  const s = await api("/api/admin/mail-settings");
  const current = s.templates.find((t) => t.key === selected) || s.templates[0];
  body.innerHTML = `
    <h2>Messages automatiques</h2>
    <p class="muted">Choisissez un message dans la liste pour voir et modifier son contenu. Les <code>{variables}</code> sont remplacées à l'envoi ; une ligne dont toutes
      les variables sont vides est supprimée.</p>
    <div id="mail-switch-zone"></div>
    <div class="msg-layout">
      <nav class="msg-list">${s.templates.map((t) => `
        <a href="#/settings/messages/${esc(t.key)}" class="${t.key === current.key ? "active" : ""}">
          <b>${esc(t.label)}</b>${t.enabled ? "" : ' <span class="tag-off">désactivé</span>'}
          <span class="muted">${esc(t.recipients)}</span></a>`).join("")}</nav>
      <section class="msg-edit card" data-key="${esc(current.key)}">
        <h3>${esc(current.label)}</h3>
        <p class="muted">${esc(current.description)} Destinataire : ${esc(current.recipients)}.</p>
        <label class="inline"><input type="checkbox" id="tpl-enabled" ${current.enabled ? "checked" : ""}> Message activé</label>
        <label>Objet<input id="tpl-subject" value="${esc(current.subject)}"></label>
        <label>Texte du message<textarea id="tpl-body" rows="14">${esc(current.body)}</textarea></label>
        <div class="var-box">
          <b>Variables disponibles</b> <span class="muted">(cliquez pour insérer dans l'objet ou le texte)</span>
          <table class="var-table"><tbody>${Object.entries(current.variables).map(([v, d]) => `
            <tr><td><button type="button" class="var-chip" data-v="${esc(v)}">{${esc(v)}}</button></td><td class="muted">${esc(d)}</td></tr>`).join("")}</tbody></table>
        </div>
        <div style="display:flex;gap:8px;flex-wrap:wrap;margin-top:10px">
          <button class="btn btn-primary" id="tpl-save">Enregistrer</button>
          <button class="btn" id="tpl-preview">Aperçu</button>
          <span class="muted">Envoyer un test à</span>
          <input id="tpl-test-to" type="email" placeholder="adresse e-mail" value="${esc(testAddress())}" style="width:240px">
          <button class="btn" id="tpl-test">Envoyer le test</button>
          <button class="btn btn-danger" id="tpl-reset">Revenir au texte d'origine</button>
        </div>
        <div id="tpl-prev" style="margin-top:10px"></div>
      </section>
    </div>`;
  renderMailSwitch($("#mail-switch-zone"), s);
  const key = current.key;
  const val = () => ({ subject: $("#tpl-subject").value, body: $("#tpl-body").value, enabled: $("#tpl-enabled").checked });
  let lastFocus = $("#tpl-body");
  $("#tpl-subject").addEventListener("focus", (e) => { lastFocus = e.target; });
  $("#tpl-body").addEventListener("focus", (e) => { lastFocus = e.target; });
  body.querySelectorAll(".var-chip").forEach((chip) => chip.addEventListener("click", () => {
    const t = `{${chip.dataset.v}}`, el = lastFocus, a = el.selectionStart ?? el.value.length, b = el.selectionEnd ?? a;
    el.value = el.value.slice(0, a) + t + el.value.slice(b);
    el.focus(); el.selectionStart = el.selectionEnd = a + t.length;
  }));
  const preview = async () => previewFrame($("#tpl-prev"),
    await api("/api/admin/mail-settings/preview", { method: "POST", body: JSON.stringify({ key, ...val() }) }));
  $("#tpl-preview").addEventListener("click", () => preview().catch((e) => toast(e.message, true)));
  $("#tpl-save").addEventListener("click", async () => {
    try { await api("/api/admin/mail-settings", { method: "PUT", body: JSON.stringify({ templates: { [key]: val() } }) }); toast("Message enregistré"); viewMailMessages(key); }
    catch (e) { toast(e.message, true); }
  });
  $("#tpl-test").addEventListener("click", async () => {
    try {
      const to = $("#tpl-test-to").value.trim();
      if (!to) { toast("Saisissez l'adresse e-mail qui recevra le test", true); $("#tpl-test-to").focus(); return; }
      rememberTestAddress(to);
      const r = await api("/api/admin/mail-settings/test", { method: "POST", body: JSON.stringify({ key, to }) });
      toast(r.ok ? "Test envoyé à " + r.to : "Non envoyé : " + r.error, !r.ok);
    } catch (e) { toast(e.message, true); }
  });
  $("#tpl-reset").addEventListener("click", async () => {
    if (!confirm("Revenir au texte d'origine de ce message ?")) return;
    try { await api("/api/admin/mail-settings/reset", { method: "POST", body: JSON.stringify({ key }) }); viewMailMessages(key); }
    catch (e) { toast(e.message, true); }
  });
  preview().catch(() => {});
}

/* ==========================================================================
   Version et journal des versions (« Nouveautés »)
   ========================================================================== */
async function loadVersion() {
  try {
    const v = await fetch("/api/version").then((r) => r.json());
    const label = "v" + v.version;
    $("#app-version").textContent = label;
    $("#login-version").textContent = "Version " + v.version + " — " + v.date;
  } catch (_) { /* affichage facultatif */ }
}

async function viewVersions() {
  const c = $("#content");
  c.innerHTML = "<h1>Journal des versions</h1><p>Chargement…</p>";
  const data = await api("/api/changelog");
  const fmtDate = (d) => String(d || "").split("-").reverse().join("/");
  c.innerHTML = `
    <h1>Journal des versions</h1>
    <p class="muted">Version actuelle : <b>${esc(data.version)}</b></p>
    ${data.versions.map((v) => `
      <div class="card" style="margin-bottom:12px">
        <h3>${esc(v.version)} <span class="muted">— ${esc(fmtDate(v.date))}</span>
          ${v.version === data.version ? '<span class="req-badge" style="position:static;margin-left:8px">actuelle</span>' : ""}</h3>
        <p><b>${esc(v.titre)}</b></p>
        <ul>${v.items.map((i) => `<li>${esc(i)}</li>`).join("")}</ul>
      </div>`).join("")}`;
}

/* ==========================================================================
   « Se connecter en tant que » (administrateurs) : recherche prédictive AD
   ========================================================================== */
function renderActAsBanner() {
  let bar = $("#actas-banner");
  const imp = state.user && state.user.impersonation;
  if (!imp) { if (bar) bar.remove(); return; }
  if (!bar) {
    bar = document.createElement("div");
    bar.id = "actas-banner";
    bar.className = "actas-banner";
    document.body.prepend(bar);
  }
  bar.innerHTML = `Vous agissez en tant que <b>${esc(state.user.nom || state.user.login)}</b>
    (connecté comme ${esc(imp.by.nom || imp.by.login)}) <button class="btn btn-small" id="actas-back">Revenir à mon compte</button>`;
  $("#actas-back").addEventListener("click", async () => {
    try { await api("/api/admin/act-as", { method: "DELETE" }); location.hash = "#/dashboard"; location.reload(); }
    catch (e) { toast(e.message, true); }
  });
}

function setupActAs() {
  const btn = $("#btn-act-as");
  btn.classList.toggle("hidden", !(state.user.admin && !state.user.impersonation));
  renderActAsBanner();
  if (btn.dataset.bound) return;
  btn.dataset.bound = "1";
  const modal = $("#actas-modal"), input = $("#actas-q"), list = $("#actas-list"), msg = $("#actas-msg");
  let timer = null, seq = 0;
  const close = () => modal.classList.add("hidden");
  btn.addEventListener("click", () => {
    modal.classList.remove("hidden");
    input.value = ""; list.innerHTML = ""; msg.textContent = "";
    input.focus();
  });
  $("#actas-cancel").addEventListener("click", close);
  input.addEventListener("input", () => {
    clearTimeout(timer);
    const q = input.value.trim();
    if (q.length < 2) { list.innerHTML = ""; msg.textContent = ""; return; }
    timer = setTimeout(async () => {
      const mine = ++seq;
      msg.textContent = "Recherche…";
      try {
        const r = await api("/api/admin/act-as/search?q=" + encodeURIComponent(q));
        if (mine !== seq) return;  // une saisie plus récente a pris le relais
        msg.textContent = r.ad_error ? "Annuaire AD indisponible : seuls les comptes de l'application sont proposés."
          : (r.items.length ? "" : "Aucun résultat.");
        list.innerHTML = r.items.map((it, i) => `
          <li class="${it.selectable ? "" : "disabled"}" data-i="${i}">
            <b>${esc(it.displayName)}</b> <span class="muted">${esc(it.username)}${it.email ? " · " + esc(it.email) : ""}</span>
            ${it.account ? `<span class="muted"> — compte ${esc(it.account.login)}</span>` : ""}
            ${it.selectable ? "" : `<em class="muted"> (${esc(it.reason)})</em>`}
          </li>`).join("");
        list.querySelectorAll("li:not(.disabled)").forEach((li) => li.addEventListener("click", async () => {
          const it = r.items[Number(li.dataset.i)];
          try {
            await api("/api/admin/act-as", { method: "POST", body: JSON.stringify({ user_id: it.account.id }) });
            location.hash = "#/dashboard"; location.reload();
          } catch (e) { toast(e.message, true); }
        }));
      } catch (e) { msg.textContent = e.message; }
    }, 250);
  });
}

/* ==========================================================================
   Clés API (admin) — accès des applications tierces à /api/v1
   ========================================================================== */
async function viewApiKeys() {
  if (!state.user.admin) { location.hash = "#/dashboard"; return; }
  const c = contentEl();
  const H = $("#admin-body") ? "h2" : "h1";
  c.innerHTML = `<${H}>Clés API</${H}><p>Chargement…</p>`;
  const data = await api("/api/v1/admin/api-keys");
  const scopeBoxes = Object.entries(data.scopes).map(([k, label]) =>
    `<label class="inline"><input type="checkbox" class="ak-scope" value="${esc(k)}"> <code>${esc(k)}</code> — ${esc(label)}</label>`).join("");
  const rows = data.items.map((k) => `
    <tr data-id="${k.id}">
      <td><b>${esc(k.name)}</b><br><span class="muted"><code>${esc(k.key_prefix)}…</code></span></td>
      <td>${esc(k.scopes.split(",").join(", "))}</td>
      <td>${esc(k.allowed_ips || "toutes")}</td>
      <td>${esc(k.expires_at || "—")}</td>
      <td>${esc(k.last_used_at || "jamais")}</td>
      <td>${k.actif ? "Active" : "<b>Désactivée</b>"}</td>
      <td>
        <button class="btn btn-small" data-act="toggle">${k.actif ? "Désactiver" : "Réactiver"}</button>
        <button class="btn btn-small" data-act="logs">Journal</button>
        <button class="btn btn-small btn-danger" data-act="del">Supprimer</button>
      </td>
    </tr>`).join("") || `<tr><td colspan="7" class="muted">Aucune clé.</td></tr>`;
  c.innerHTML = `
    <${H}>Clés API</${H}>
    <p class="muted">Permettent à d'autres applications de la Ville de <b>lire</b> les données (documentation :
      <a href="/api-docs/" target="_blank" rel="noopener">/api-docs</a>). Une clé n'est affichée qu'une seule fois, à sa création.</p>
    <div class="card" style="margin-bottom:16px">
      <h3>Nouvelle clé</h3>
      <div class="params-grid">
        <label>Application <input id="ak-name" placeholder="ex. Portail RH"></label>
        <label>Expire le <input id="ak-exp" type="date"></label>
        <label>IP / réseaux autorisés <input id="ak-ips" placeholder="ex. 10.103.0.0/16 (vide = toutes)"></label>
      </div>
      <div class="ak-scopes">${scopeBoxes}</div>
      <button class="btn btn-primary" id="ak-create">Créer la clé</button>
      <div id="ak-new" class="hidden card" style="margin-top:12px"></div>
    </div>
    <table class="data"><thead><tr>
      <th>Application</th><th>Périmètres</th><th>IP autorisées</th><th>Expiration</th><th>Dernier appel</th><th>État</th><th>Actions</th>
    </tr></thead><tbody>${rows}</tbody></table>
    <div id="ak-logs"></div>`;

  $("#ak-create").addEventListener("click", async () => {
    try {
      const created = await api("/api/v1/admin/api-keys", {
        method: "POST",
        body: JSON.stringify({
          name: $("#ak-name").value.trim(),
          expires_at: $("#ak-exp").value,
          allowed_ips: $("#ak-ips").value.trim(),
          scopes: $$(".ak-scope").filter((b) => b.checked).map((b) => b.value),
        }),
      });
      const box = $("#ak-new");
      box.classList.remove("hidden");
      box.innerHTML = `<p><b>Clé créée pour « ${esc(created.name)} ».</b> Copiez-la maintenant : elle ne sera plus affichée.</p>
        <p><code id="ak-key" style="user-select:all;word-break:break-all">${esc(created.key)}</code></p>
        <button class="btn btn-small" id="ak-copy">Copier</button>
        <button class="btn btn-small" id="ak-done">J'ai noté la clé</button>`;
      $("#ak-copy").addEventListener("click", () => navigator.clipboard.writeText(created.key).then(() => toast("Clé copiée")));
      $("#ak-done").addEventListener("click", viewApiKeys);
    } catch (e) { toast(e.message, true); }
  });

  c.querySelectorAll("tr[data-id]").forEach((tr) => {
    const id = tr.dataset.id;
    const key = data.items.find((k) => String(k.id) === id);
    tr.querySelector('[data-act="toggle"]').addEventListener("click", async () => {
      await api(`/api/v1/admin/api-keys/${id}`, { method: "PUT", body: JSON.stringify({ actif: !key.actif }) });
      viewApiKeys();
    });
    tr.querySelector('[data-act="del"]').addEventListener("click", async () => {
      if (!confirm(`Supprimer définitivement la clé « ${key.name} » ? L'application concernée perdra son accès.`)) return;
      await api(`/api/v1/admin/api-keys/${id}`, { method: "DELETE" });
      viewApiKeys();
    });
    tr.querySelector('[data-act="logs"]').addEventListener("click", async () => {
      const logs = await api(`/api/v1/admin/api-keys/${id}/logs?limit=50`);
      $("#ak-logs").innerHTML = `<h3>Journal — ${esc(key.name)} (${logs.total} appel(s), 50 derniers)</h3>
        <table class="data"><thead><tr><th>Date</th><th>Appel</th><th>Statut</th><th>IP</th></tr></thead><tbody>${
          logs.items.map((l) => `<tr><td>${esc(l.at)}</td><td>${esc(l.method)} ${esc(l.path)}</td><td>${l.status}</td><td>${esc(l.ip)}</td></tr>`).join("")
          || `<tr><td colspan="4" class="muted">Aucun appel.</td></tr>`}</tbody></table>`;
    });
  });
}

/* ==========================================================================
   Utilisateurs (admin)
   ========================================================================== */
async function viewUsers() {
  if (!canManageUsers()) { location.hash = "#/dashboard"; return; }
  const isAdmin = !!state.user.admin;
  const c = contentEl();
  const H = $("#admin-body") ? "h2" : "h1";
  const adMode = state.user.auth_mode === "ad";
  c.innerHTML = `<${H}>Utilisateurs</${H}><p>Chargement…</p>`;
  const users = await api("/api/users");

  const roleOptions = (current) => Object.entries(ROLE_LABELS).map(([value, label]) =>
    `<option value="${value}" ${value === current ? "selected" : ""}>${label}</option>`).join("");
  const parentRolesFor = (role) => ({
    dgs: ["administrateur"],
    dga: ["dgs"],
    direction: ["dga", "dgs", "administrateur"],
    service: ["direction"],
    secteur: ["service", "direction"],
    unite: ["secteur", "service"],
    equipe: ["unite", "secteur"],
    agent: ["administrateur", "dgs", "dga", "direction", "service", "secteur", "unite", "equipe"],
  }[role] || []);
  const parentOptions = (role, current, excludeId, includeSelf = false) => {
    if (role === "administrateur") return `<option value="">—</option>`;
    const expected = parentRolesFor(role);
    const pool = users.slice();
    if (includeSelf && state.user && !pool.some((u) => u.id === state.user.id)) pool.push(state.user);
    const opts = pool
      .filter((u) => u.id !== excludeId && expected.includes(userRole(u)))
      .map((u) => `<option value="${u.id}" ${String(u.id) === String(current) ? "selected" : ""}>${esc(u.nom || u.login)} (${esc(u.login)})</option>`);
    return `<option value="">—</option>` + opts.join("");
  };
  const creatableRoles = state.user.admin
    ? Object.keys(ROLE_LABELS)
    : ({
      dgs: ["dga", "direction", "service", "secteur", "unite", "equipe", "agent"],
      dga: ["direction", "service", "secteur", "unite", "equipe", "agent"],
      direction: ["service", "secteur", "unite", "equipe", "agent"],
      service: ["secteur", "unite", "equipe", "agent"],
      secteur: ["unite", "equipe", "agent"],
      unite: ["equipe", "agent"],
      equipe: ["agent"],
    }[userRole(state.user)] || []);
  const createRoleOptions = creatableRoles.map((value) =>
    `<option value="${value}">${ROLE_LABELS[value]}</option>`).join("");
  const defaultCreateRole = creatableRoles[0] || "";

  let lastRole = null;
  const rowsHtml = users.map((u) => {
    const role = userRole(u);
    const self = u.id === state.user.id;
    const lockRole = !isAdmin || self;
    const group = role !== lastRole
      ? `<tr class="role-group" data-role="${role}"><td colspan="10">${esc(ROLE_LABELS[role] || role)}</td></tr>`
      : "";
    lastRole = role;
    return group + `
      <tr data-id="${u.id}" data-role="${role}" data-login="${esc(u.login)}" data-nom="${esc(u.nom)}" data-email="${esc(u.email || "")}" data-actif="${u.actif ? 1 : 0}">
        <td>${isAdmin ? `<input data-f="login" value="${esc(u.login)}">` : esc(u.login)}</td>
        <td><input data-f="ad_login" value="${esc(u.ad_login || "")}" placeholder="(identique)"></td>
        <td><input data-f="matricule" value="${esc(u.matricule || "")}" maxlength="20"></td>
        <td><input data-f="nom" value="${esc(u.nom)}"></td>
        <td><input data-f="email" type="email" value="${esc(u.email || "")}"></td>
        <td>${adMode && role !== "administrateur" ? '<span class="muted" title="Mot de passe de l\'Active Directory">AD</span>' : '<input data-f="password" type="password" placeholder="(inchangé)">'}</td>
        <td><select data-f="role" ${lockRole ? "disabled" : ""}>${roleOptions(role)}</select></td>
        <td><select data-f="parent_id" ${lockRole || role === "administrateur" ? "disabled" : ""}>${parentOptions(role, u.parent_id, u.id, true)}</select></td>
        <td><input type="checkbox" data-f="actif" ${u.actif ? "checked" : ""} ${self ? "disabled" : ""}></td>
        <td>
          <button class="btn btn-small" data-act="save">Enregistrer</button>
          ${!self && canManageUsers() ? `<button class="btn btn-small btn-danger" data-act="del">Supprimer</button>` : ""}
        </td>
      </tr>`;
  }).join("");

  c.innerHTML = `
    <div class="page-head">
      <${H}>Utilisateurs</${H}>
      ${isAdmin ? `<button type="button" class="btn btn-small" id="btn-user-audit">Journal d'audit</button>` : ""}
    </div>
    <div id="users-msg"></div>

    ${canManageUsers() ? `
    <div class="card new-user-card" style="margin-bottom:16px">
      <h3>Nouvel utilisateur</h3>
      <div class="params-grid new-user-grid">
        <label>Identifiant <input id="nu-login"></label>
        <label>Identifiant AD <input id="nu-ad-login" placeholder="(identique)"></label>
        <label>Matricule <input id="nu-matricule" maxlength="20"></label>
        <label>Nom <input id="nu-nom"></label>
        <label>E-mail <input id="nu-email" type="email"></label>
        <label>${adMode ? "Mot de passe (administrateur seulement)" : "Mot de passe"} <input id="nu-pass" type="password"></label>
        <label>Rôle <select id="nu-role">${createRoleOptions}</select></label>
        <label>Responsable <select id="nu-parent">${parentOptions(defaultCreateRole, state.user.id, null, true)}</select></label>
        <button class="btn btn-primary new-user-submit" id="nu-create">Créer</button>
      </div>
    </div>` : ""}

    <p class="users-hint">Hiérarchie : Administrateur > Valideur DGS > Valideur DGA > Valideur Direction > Valideur Service > Valideur Secteur > Valideur Unité > Valideur Équipe > Agent. Les valideurs gèrent les comptes de leur périmètre.</p>
    <div class="users-toolbar">
      <input type="search" id="users-search" placeholder="Rechercher un identifiant, un nom ou un e-mail">
      <select id="users-role-filter">
        <option value="">Tous les niveaux</option>
        ${Object.entries(ROLE_LABELS).map(([value, label]) => `<option value="${value}">${label}</option>`).join("")}
      </select>
      <select id="users-active-filter">
        <option value="">Tous</option>
        <option value="1">Actifs</option>
        <option value="0">Inactifs</option>
      </select>
      <select id="users-page-size">
        <option value="25">25 par page</option>
        <option value="50">50 par page</option>
        <option value="100">100 par page</option>
      </select>
    </div>
    <table class="data users-table">
      <colgroup>
        <col style="width:8%"><col style="width:8%"><col style="width:7%"><col style="width:11%"><col style="width:12%"><col style="width:7%">
        <col style="width:11%"><col style="width:15%"><col style="width:5%"><col style="width:13%">
      </colgroup>
      <thead><tr>
        <th>Identifiant</th><th title="Identifiant Active Directory (vide = identique à l'identifiant)">Identifiant AD</th><th>Matricule</th><th>Nom</th><th>E-mail</th><th>Mot de passe</th>
        <th>Rôle</th><th>Responsable</th><th>Actif</th><th>Actions</th>
      </tr></thead>
      <tbody id="users-table-body">
        ${rowsHtml}
      </tbody>
    </table>
    <div class="users-pager">
      <span id="users-page-info"></span>
      <div class="users-pager-buttons">
        <button type="button" class="btn btn-small" id="users-prev">‹</button>
        <span id="users-page-label"></span>
        <button type="button" class="btn btn-small" id="users-next">›</button>
      </div>
    </div>`;

  let usersPage = 1;
  const applyUsersFilter = () => {
    const q = ($("#users-search").value || "").trim().toLowerCase();
    const role = $("#users-role-filter").value;
    const active = $("#users-active-filter").value;
    const pageSize = Number($("#users-page-size").value) || 25;
    const rows = [...document.querySelectorAll("#users-table-body tr[data-id]")];
    const filtered = rows.filter((row) => {
      if (role && row.dataset.role !== role) return false;
      if (active && row.dataset.actif !== active) return false;
      if (!q) return true;
      return [row.dataset.login, row.dataset.nom, row.dataset.email]
        .some((v) => String(v || "").toLowerCase().includes(q));
    });
    const total = filtered.length;
    const maxPage = Math.max(1, Math.ceil(total / pageSize));
    usersPage = Math.min(usersPage, maxPage);
    const start = (usersPage - 1) * pageSize;
    const pageRows = filtered.slice(start, start + pageSize);
    const visibleIds = new Set(pageRows.map((row) => row.dataset.id));
    rows.forEach((row) => {
      row.style.display = visibleIds.has(row.dataset.id) ? "" : "none";
    });
    const visibleRoles = new Set(pageRows.map((row) => row.dataset.role));
    document.querySelectorAll("#users-table-body tr.role-group").forEach((row) => {
      row.style.display = visibleRoles.has(row.dataset.role) ? "" : "none";
    });
    const from = total ? start + 1 : 0;
    const to = Math.min(start + pageSize, total);
    $("#users-page-info").textContent = `${from}–${to} sur ${total} utilisateur(s)`;
    $("#users-page-label").textContent = `${usersPage}/${maxPage}`;
    $("#users-prev").disabled = usersPage <= 1;
    $("#users-next").disabled = usersPage >= maxPage;
  };
  const resetUsersPage = () => { usersPage = 1; applyUsersFilter(); };
  $("#users-search").addEventListener("input", resetUsersPage);
  $("#users-role-filter").addEventListener("change", resetUsersPage);
  $("#users-active-filter").addEventListener("change", resetUsersPage);
  $("#users-page-size").addEventListener("change", resetUsersPage);
  $("#users-prev").addEventListener("click", () => { if (usersPage > 1) { usersPage--; applyUsersFilter(); } });
  $("#users-next").addEventListener("click", () => { usersPage++; applyUsersFilter(); });
  applyUsersFilter();

  if (canManageUsers()) {
    const auditBtn = $("#btn-user-audit");
    if (auditBtn) auditBtn.addEventListener("click", openUserAuditModal);
    const refreshCreateParents = () => {
      const role = $("#nu-role").value;
      $("#nu-parent").innerHTML = parentOptions(role, state.user.id, null, true);
      $("#nu-parent").disabled = role === "administrateur";
    };
    $("#nu-role").addEventListener("change", refreshCreateParents);
    refreshCreateParents();

    $("#nu-create").addEventListener("click", async () => {
      try {
        const role = $("#nu-role").value;
        await api("/api/users", {
          method: "POST",
          body: JSON.stringify({
            login: $("#nu-login").value.trim(),
            nom: $("#nu-nom").value.trim(),
            ad_login: $("#nu-ad-login").value.trim(),
            matricule: $("#nu-matricule").value.trim(),
            email: $("#nu-email").value.trim(),
            password: $("#nu-pass").value,
            role,
            parent_id: role === "administrateur" ? null : ($("#nu-parent").value || null),
          }),
        });
        toast("Utilisateur créé");
        viewUsers();
      } catch (err) {
        $("#users-msg").innerHTML = `<div class="form-error">${esc(err.message)}</div>`;
      }
    });
  }

  $$("table.data tr[data-id]").forEach((tr) => {
    const id = Number(tr.dataset.id);
    const roleEl = tr.querySelector('[data-f="role"]');
    const parentEl = tr.querySelector('[data-f="parent_id"]');
    if (roleEl && !roleEl.disabled) {
      roleEl.addEventListener("change", () => {
        parentEl.innerHTML = parentOptions(roleEl.value, null, id);
        parentEl.disabled = roleEl.value === "administrateur";
      });
    }
    tr.querySelector('[data-act="save"]').addEventListener("click", async () => {
      const loginEl = tr.querySelector('[data-f="login"]');
      const payload = {
        nom: tr.querySelector('[data-f="nom"]').value,
        ad_login: tr.querySelector('[data-f="ad_login"]').value.trim(),
        matricule: tr.querySelector('[data-f="matricule"]').value.trim(),
        email: tr.querySelector('[data-f="email"]').value,
        role: roleEl.value,
        parent_id: parentEl.value || null,
        actif: tr.querySelector('[data-f="actif"]').checked,
      };
      if (loginEl) payload.login = loginEl.value.trim();
      const pwEl = tr.querySelector('[data-f="password"]');
      if (pwEl && pwEl.value) payload.password = pwEl.value;
      try {
        const updated = await api("/api/users/" + id, { method: "PUT", body: JSON.stringify(payload) });
        if (updated && state.user && updated.id === state.user.id) {
          state.user.login = updated.login;
          localStorage.setItem("suivi_user", JSON.stringify(state.user));
        }
        toast("Utilisateur mis à jour");
        viewUsers();
      } catch (err) {
        $("#users-msg").innerHTML = `<div class="form-error">${esc(err.message)}</div>`;
      }
    });
    const del = tr.querySelector('[data-act="del"]');
    if (del) del.addEventListener("click", async () => {
      if (!confirm("Supprimer cet utilisateur et toutes ses fiches ?")) return;
      try {
        await api("/api/users/" + id, { method: "DELETE" });
        toast("Utilisateur supprimé");
        viewUsers();
      } catch (err) {
        $("#users-msg").innerHTML = `<div class="form-error">${esc(err.message)}</div>`;
      }
    });
  });
}

async function openUserAuditModal() {
  const modal = $("#user-audit-modal");
  const body = $("#user-audit-body");
  const err = $("#user-audit-error");
  if (!modal || !body) return;
  body.innerHTML = `<tr><td colspan="8" class="muted">Chargement…</td></tr>`;
  err.classList.add("hidden");
  modal.classList.remove("hidden");
  try {
    const rows = await api("/api/users/audit?limit=300");
    body.innerHTML = rows.length
      ? rows.map((r) => `<tr>
          <td>${esc(String(r.created_at || "").slice(0, 16))}</td>
          <td>${esc(r.target_login || "—")}</td>
          <td>${esc(r.action || "")}</td>
          <td>${esc(r.field || "")}</td>
          <td>${esc(r.old_value || "—")}</td>
          <td>${esc(r.new_value || "—")}</td>
          <td>${esc(r.actor_login || "—")}</td>
          <td>${esc(r.comment || "")}</td>
        </tr>`).join("")
      : `<tr><td colspan="8" class="muted">Aucune modification enregistrée.</td></tr>`;
  } catch (e) {
    err.textContent = e.message;
    err.classList.remove("hidden");
    body.innerHTML = "";
  }
}

$("#user-audit-close").addEventListener("click", () => $("#user-audit-modal").classList.add("hidden"));
$("#user-audit-modal").addEventListener("mousedown", (e) => {
  if (e.target.id === "user-audit-modal") $("#user-audit-modal").classList.add("hidden");
});

/* ---------------------------- démarrage ---------------------------- */
$("#year-select").addEventListener("change", (e) => setYear(Number(e.target.value)));
loadVersion();
tryRestoreSession();
