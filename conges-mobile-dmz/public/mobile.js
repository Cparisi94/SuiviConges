/* Suivi des congés — version mobile (DMZ). Page autonome : aucune dépendance sur l'application complète.
   Fonctions de base : compteurs, demandes en cours (en attente ou validées), demande simple « du … au … », agenda.
   N'appelle que : /api/auth/login, /api/auth/logout, /api/me, /api/mobile/summary, /api/mobile/days, POST /api/requests
   et POST /api/mobile/requests/<id>/cancel | cancel-request, plus POST /api/activation/* (première connexion), GET /api/mobile/calendar, POST /api/mobile/calendar/link | revoke.
   Le flux ICS (/cal/<jeton>.ics) est lu par le téléphone, pas par cette page.
   (la liste blanche du nginx de ce dossier). */
(() => {
  "use strict";
  const $ = (sel) => document.querySelector(sel);
  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const num = (v) => (v == null ? "—" : Number(v).toLocaleString("fr-FR", { maximumFractionDigits: 2 }));
  const MONTHS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre", "novembre", "décembre"];
  const iso = (y, m, d) => `${y}-${String(m + 1).padStart(2, "0")}-${String(d).padStart(2, "0")}`;
  const today = () => { const t = new Date(); return iso(t.getFullYear(), t.getMonth(), t.getDate()); };
  const state = { user: null, year: new Date().getFullYear(), month: null };

  function toast(msg, isErr) {
    const el = $("#toast");
    el.textContent = msg;
    el.className = "toast" + (isErr ? " err" : "");
    clearTimeout(el._t);
    el._t = setTimeout(() => el.classList.add("hidden"), 3200);
  }

  // Préfixe de la page : « » quand elle est servie à la racine (DMZ), « /mobile » quand elle l'est sous /mobile/ (backend mobile derrière le nginx du serveur).
  const BASE = location.pathname.replace(/\/[^/]*$/, "");

  async function api(path, opts = {}) {
    const res = await fetch(BASE + path, { ...opts, headers: { "Content-Type": "application/json", ...(opts.headers || {}) }, credentials: "same-origin" });
    let data = null;
    try { data = await res.json(); } catch (_) { /* corps vide */ }
    if (res.status === 401 && path !== "/api/auth/login") { showLogin(); throw new Error("Session expirée"); }
    if (!res.ok) throw new Error((data && (data.error || (data.errors || []).join(" — "))) || ("Erreur " + res.status));
    return data;
  }

  /* ----------------------------- connexion ----------------------------- */
  function showLogin(message, prefillLogin, info) {
    state.user = null;
    document.querySelectorAll("#m-sheet").forEach((n) => n.remove());
    $("#app").innerHTML = `<div class="m-wrap"><form id="login-form" class="m-card m-login" autocomplete="on">
        <h1>📅 Mes congés</h1><p class="muted">Connectez-vous avec votre compte de la Ville.</p>
        <label>Identifiant ou matricule<input id="login-user" autocomplete="username" autocapitalize="none" value="${esc(prefillLogin || "")}" required></label>
        <label>Mot de passe<input id="login-pass" type="password" autocomplete="current-password" required></label>
        <label class="m-check"><input type="checkbox" id="login-remember"> Se souvenir de moi (30 jours)</label>
        ${info ? `<div class="m-info">${esc(info)}</div>` : ""}
        <div id="login-error" class="form-error${message ? "" : " hidden"}">${esc(message || "")}</div>
        <button type="submit" class="m-new">Se connecter</button>
        <p class="m-act-back"><a href="#" id="go-forgot">Mot de passe oublié ?</a></p>
        </form>
        <p class="m-act-sep">Première connexion ?</p>
        <button type="button" class="m-ghost m-block" id="go-activation">Activer mon compte</button></div>`;
    $("#go-activation").addEventListener("click", () => showActivation());
    $("#go-forgot").addEventListener("click", (e) => { e.preventDefault(); showForgot($("#login-user").value.trim()); });
    $("#login-form").addEventListener("submit", async (e) => {
      e.preventDefault();
      const err = $("#login-error"), btn = e.target.querySelector("button");
      err.classList.add("hidden");
      btn.disabled = true;
      try {
        const data = await api("/api/auth/login", { method: "POST", body: JSON.stringify({ login: $("#login-user").value.trim(), password: $("#login-pass").value, remember: $("#login-remember").checked }) });
        state.user = data.user;
        render();
      } catch (ex) {
        err.textContent = ex.message;
        err.classList.remove("hidden");
        btn.disabled = false;
      }
    });
    $("#login-user").focus();
  }

  async function logout() {
    try { await api("/api/auth/logout", { method: "POST" }); } catch (_) { /* déjà déconnecté */ }
    try { localStorage.removeItem("m_bio"); } catch (_) { /* sans effet */ }
    showLogin();
  }

  /* ----------------------------- mot de passe oublié (smartphone contrôlé) ----------------------------- */
  function showForgot(prefill) {
    const app = $("#app");
    const frame = (title, body) => `<div class="m-wrap"><div class="m-card m-login"><h1>📅 ${title}</h1>${body}
        <div id="fg-error" class="form-error hidden"></div><p class="m-act-back"><a href="#" id="fg-back">← Retour à la connexion</a></p></div></div>`;
    const fail = (msg) => { const el = $("#fg-error"); el.textContent = msg; el.classList.remove("hidden"); };
    let ident = prefill || "";
    const step1 = () => {
      app.innerHTML = frame("Mot de passe oublié", `<p class="muted">Saisissez votre matricule ou votre identifiant : si votre smartphone a été enregistré, un code vous est envoyé par SMS.</p>
        <form id="fg-form"><label>Matricule ou identifiant<input id="fg-id" value="${esc(ident)}" autocomplete="username" autocapitalize="none" required></label>
        <button type="submit" class="m-new">Recevoir le code par SMS</button></form>`);
      $("#fg-form").addEventListener("submit", async (e) => {
        e.preventDefault();
        ident = $("#fg-id").value.trim();
        try { await api("/api/activation/forgot", { method: "POST", body: JSON.stringify({ identifiant: ident }) }); step2(); }
        catch (ex) { fail(ex.message); }
      });
      back();
    };
    const step2 = () => {
      app.innerHTML = frame("Nouveau mot de passe", `<p class="muted">Si ces informations correspondent à un compte dont le smartphone est enregistré, un SMS vient d'être envoyé (valable 10 minutes).</p>
        <form id="fg-form"><label>Code reçu par SMS<input id="fg-code" inputmode="numeric" autocomplete="one-time-code" maxlength="6" required></label>
        <label>Nouveau mot de passe (10 caractères, lettres et chiffres)<input id="fg-pw" type="password" autocomplete="new-password" required></label>
        <label>Confirmez-le<input id="fg-pw2" type="password" autocomplete="new-password" required></label>
        <button type="submit" class="m-new">Changer mon mot de passe</button></form>`);
      $("#fg-form").addEventListener("submit", async (e) => {
        e.preventDefault();
        try {
          const r = await api("/api/activation/reset", { method: "POST", body: JSON.stringify({ identifiant: ident, code: $("#fg-code").value.trim(), password: $("#fg-pw").value, confirm: $("#fg-pw2").value }) });
          showLogin(null, r.matricule || ident, "Mot de passe modifié : connectez-vous avec votre nouveau mot de passe.");
        } catch (ex) { fail(ex.message); }
      });
      back();
    };
    const back = () => { $("#fg-back").addEventListener("click", (e) => { e.preventDefault(); showLogin(); }); };
    step1();
  }

  /* ----------------------------- empreinte / Face ID : verrouillage de l'application sur ce téléphone -----------------------------
     Verrou LOCAL (WebAuthn, authentificateur du téléphone, vérification de l'utilisateur obligatoire) : à l'ouverture, la page demande l'empreinte ou le visage
     avant d'afficher quoi que ce soit. Il protège un téléphone déverrouillé prêté ou volé ; il ne remplace pas le mot de passe (connexion mémorisée 30 jours). */
  // Icône d'empreinte digitale (SVG en ligne : hérite de la couleur du texte, aucune image à charger).
  const fpIcon = (size) => `<svg class="m-fp" width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false"><path d="M12 10a2 2 0 0 0-2 2c0 1.02-.1 2.51-.26 4"/><path d="M14 13.12c0 2.38 0 6.38-1 8.88"/><path d="M17.29 21.02c.12-.6.43-2.3.5-3.02"/><path d="M2 12a10 10 0 0 1 18-6"/><path d="M2 16h.01"/><path d="M21.8 16c.2-2 .131-5.354 0-6"/><path d="M5 19.5C5.5 18 6 15 6 12a6 6 0 0 1 .34-2"/><path d="M8.65 22c.21-.66.45-1.32.57-2"/><path d="M9 6.8a6 6 0 0 1 9 5.2v2"/></svg>`;
  const BIO_KEY = "m_bio";
  const b64 = (buf) => btoa(String.fromCharCode(...new Uint8Array(buf))).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
  const unb64 = (s) => Uint8Array.from(atob(s.replace(/-/g, "+").replace(/_/g, "/")), (c) => c.charCodeAt(0));
  const bioStored = () => { try { return JSON.parse(localStorage.getItem(BIO_KEY) || "null"); } catch (_) { return null; } };
  async function bioAvailable() {
    try { return !!(window.isSecureContext && window.PublicKeyCredential && await PublicKeyCredential.isUserVerifyingPlatformAuthenticatorAvailable()); } catch (_) { return false; }
  }
  async function bioEnable() {
    const cred = await navigator.credentials.create({ publicKey: {
      challenge: crypto.getRandomValues(new Uint8Array(32)), rp: { name: "Mes congés" },
      user: { id: crypto.getRandomValues(new Uint8Array(16)), name: "u" + state.user.id, displayName: "Mes congés" },
      pubKeyCredParams: [{ type: "public-key", alg: -7 }, { type: "public-key", alg: -257 }],
      authenticatorSelection: { authenticatorAttachment: "platform", userVerification: "required", residentKey: "discouraged" }, attestation: "none", timeout: 60000 } });
    try { localStorage.setItem(BIO_KEY, JSON.stringify({ uid: state.user.id, cred: b64(cred.rawId) })); } catch (_) { /* stockage indisponible */ }
  }
  async function bioCheck(stored) {
    await navigator.credentials.get({ publicKey: { challenge: crypto.getRandomValues(new Uint8Array(32)),
      allowCredentials: [{ type: "public-key", id: unb64(stored.cred) }], userVerification: "required", timeout: 60000 } });
  }
  function showLock(stored) {
    $("#app").innerHTML = `<div class="m-wrap"><div class="m-card m-login"><div class="m-lock-icon">${fpIcon(72)}</div><h1>Mes congés</h1><p class="muted">Application verrouillée : confirmez avec votre empreinte ou votre visage.</p>
        <div id="lock-error" class="form-error hidden"></div>
        <button type="button" class="m-new" id="lock-go">${fpIcon(20)} Déverrouiller</button>
        <button type="button" class="m-ghost m-block" id="lock-other">Me connecter avec mon mot de passe</button></div></div>`;
    const go = async () => {
      try { await bioCheck(stored); render(); }
      catch (_) { const el = $("#lock-error"); el.textContent = "Vérification annulée ou refusée."; el.classList.remove("hidden"); }
    };
    $("#lock-go").addEventListener("click", go);
    $("#lock-other").addEventListener("click", async () => { try { localStorage.removeItem(BIO_KEY); } catch (_) { /* sans effet */ } await logout(); });
    go();
  }

  /* ----------------------------- première connexion : activation du compte (code + SMS + mot de passe) ----------------------------- */
  function showActivation(prefill) {
    prefill = prefill || {};
    let step = "code", login = "";
    const app = $("#app");
    const frame = (title, body) => `<div class="m-wrap"><div class="m-card m-login"><h1>📅 ${title}</h1>${body}
        <div id="act-error" class="form-error hidden"></div><p class="m-act-back"><a href="#" id="act-back">← Retour à la connexion</a></p></div></div>`;
    const fail = (msg) => { const el = $("#act-error"); el.textContent = msg; el.classList.remove("hidden"); };
    const call = async (path, body) => {
      $("#act-error").classList.add("hidden");
      return api("/api/activation/" + path, { method: "POST", body: JSON.stringify(body) });
    };
    const draw = (info) => {
      if (step === "code") {
        app.innerHTML = frame("Première connexion", `<p class="muted">Saisissez le matricule et le code d'activation remis par votre responsable (ou scannez le QR code).</p>
          <form id="act-form"><label>Matricule<input id="act-mat" value="${esc(prefill.matricule || "")}" autocomplete="off" autocapitalize="characters" required></label>
          <label>Code d'activation<input id="act-code" value="${esc(prefill.code || "")}" autocomplete="off" autocapitalize="characters" placeholder="XXXXX-XXXXX" required></label>
          <button type="submit" class="m-new">Continuer</button></form>`);
        $("#act-form").addEventListener("submit", async (e) => {
          e.preventDefault();
          try { await call("start", { matricule: $("#act-mat").value.trim(), code: $("#act-code").value.trim() }); step = "sms"; draw(); }
          catch (ex) { fail(ex.message); }
        });
      } else if (step === "sms") {
        app.innerHTML = frame("Votre smartphone", `<p class="muted">Saisissez votre numéro de smartphone : nous vous envoyons un code par SMS pour le contrôler.</p>
          <form id="act-form"><label>Numéro de smartphone<input id="act-mobile" type="tel" inputmode="tel" autocomplete="tel" placeholder="06 12 34 56 78" required></label>
          <button type="submit" class="m-new">Recevoir le code par SMS</button></form>`);
        $("#act-form").addEventListener("submit", async (e) => {
          e.preventDefault();
          try { const r = await call("sms", { mobile: $("#act-mobile").value.trim() }); step = "otp"; draw(r); }
          catch (ex) { fail(ex.message); }
        });
      } else if (step === "otp") {
        app.innerHTML = frame("Code reçu par SMS", `<p class="muted">Un SMS a été envoyé au ${esc(info && info.mobile || "")}. Saisissez le code à 6 chiffres (valable ${esc(info && info.valable_minutes || 10)} minutes).</p>
          <form id="act-form"><label>Code SMS<input id="act-otp" inputmode="numeric" autocomplete="one-time-code" maxlength="6" pattern="[0-9]{6}" required></label>
          <button type="submit" class="m-new">Valider</button></form>
          <p class="m-act-back"><a href="#" id="act-resend">Je n'ai rien reçu : renvoyer un SMS</a></p>`);
        $("#act-form").addEventListener("submit", async (e) => {
          e.preventDefault();
          try { await call("otp", { code: $("#act-otp").value.trim() }); step = "email"; draw(); }
          catch (ex) { fail(ex.message); }
        });
        $("#act-resend").addEventListener("click", (e) => { e.preventDefault(); step = "sms"; draw(); });
      } else if (step === "email") {
        app.innerHTML = frame("Votre adresse e-mail", `<p class="muted"><strong>Facultatif.</strong> Sans adresse e-mail, vos confirmations de demandes et de validations vous seront envoyées <strong>par SMS</strong>.</p>
          <form id="act-form"><label>Adresse e-mail<input id="act-email" type="email" inputmode="email" autocomplete="email" autocapitalize="none" placeholder="prenom.nom@exemple.fr"></label>
          <button type="submit" class="m-new">Continuer</button></form>
          <button type="button" class="m-ghost m-block" id="act-noemail">Je n'ai pas d'adresse e-mail</button>`);
        const send = async (value) => { try { await call("email", { email: value }); step = "password"; draw(); } catch (ex) { fail(ex.message); } };
        $("#act-form").addEventListener("submit", (e) => { e.preventDefault(); send($("#act-email").value.trim()); });
        $("#act-noemail").addEventListener("click", () => send(""));
      } else if (step === "password") {
        app.innerHTML = frame("Choisissez votre mot de passe", `<p class="muted">10 caractères au moins, avec des lettres et des chiffres.</p>
          <form id="act-form"><label>Mot de passe<input id="act-pw" type="password" autocomplete="new-password" required></label>
          <label>Confirmez-le<input id="act-pw2" type="password" autocomplete="new-password" required></label>
          <button type="submit" class="m-new">Activer mon compte</button></form>`);
        $("#act-form").addEventListener("submit", async (e) => {
          e.preventDefault();
          try { const r = await call("password", { password: $("#act-pw").value, confirm: $("#act-pw2").value }); login = r.matricule || r.login; step = "done"; draw(); }
          catch (ex) { fail(ex.message); }
        });
      } else {
        app.innerHTML = frame("Compte activé", `<p>Votre compte est activé. Connectez-vous avec votre <strong>matricule</strong> (${esc(login)}) et le mot de passe que vous venez de choisir.</p>
          <button type="button" class="m-new" id="act-go">Se connecter</button>`);
        $("#act-go").addEventListener("click", () => showLogin(null, login));
      }
      const back = $("#act-back");
      if (back) back.addEventListener("click", (e) => { e.preventDefault(); showLogin(); });
    };
    draw();
  }

  /* ----------------------------- écran principal ----------------------------- */
  async function render() {
    const app = $("#app");
    let d;
    try { d = await api("/api/mobile/summary?year=" + encodeURIComponent(state.year)); }
    catch (e) { if (state.user) app.innerHTML = `<div class="m-wrap"><div class="form-error">${esc(e.message)}</div></div>`; return; }
    const year = d.year;
    if (state.month === null || state.shownYear !== year) { state.shownYear = year; state.month = new Date().getFullYear() === year ? new Date().getMonth() : 0; }

    const head = `<header class="m-head">
        <div><b>📅 Mes congés</b><div class="m-who">${esc(d.user.label)}</div></div>
        <span class="m-head-btns"><button type="button" id="m-bio" class="hidden" aria-label="Verrouillage par empreinte"></button><button type="button" id="m-logout" title="Déconnexion" aria-label="Déconnexion">⏻</button></span></header>
      <div class="m-year"><button type="button" id="m-prev-year" aria-label="Année précédente">‹</button><strong>${year}</strong><button type="button" id="m-next-year" aria-label="Année suivante">›</button></div>`;
    const bind = () => {
      $("#m-logout").addEventListener("click", logout);
      bioAvailable().then((ok) => {
        const b = $("#m-bio");
        if (!ok || !b) return;
        const on = () => { const s = bioStored(); return !!(s && s.uid === (state.user || {}).id); };
        const paint = () => { b.innerHTML = fpIcon(22); b.classList.toggle("m-bio-on", on()); b.setAttribute("aria-pressed", on() ? "true" : "false"); b.title = on() ? "Verrouillage par empreinte actif (toucher pour le retirer)" : "Activer le verrouillage par empreinte ou Face ID"; b.classList.remove("hidden"); };
        paint();
        b.addEventListener("click", async () => {
          try {
            if (on()) { localStorage.removeItem("m_bio"); toast("Verrouillage retiré"); }
            else { await bioEnable(); toast("Verrouillage activé : l'empreinte sera demandée à l'ouverture"); }
          } catch (_) { toast("Activation annulée ou impossible sur cet appareil", true); }
          paint();
        });
      });
      $("#m-prev-year").addEventListener("click", () => { state.year = year - 1; render(); });
      $("#m-next-year").addEventListener("click", () => { state.year = year + 1; render(); });
    };
    if (!d.fiche) {
      app.innerHTML = `<div class="m-wrap">${head}<div class="m-card"><p>Vous n'avez pas de fiche de congés pour ${year}.</p><p class="muted">Votre valideur doit d'abord définir votre période de travail.</p></div></div>`;
      bind();
      return;
    }

    const soldes = (d.soldes || []).map((s) => `<div class="m-solde"><span class="m-solde-l">${esc(s.label)}</span><strong class="${s.restant != null && s.restant < 0 ? "neg" : ""}">${num(s.restant)}<small> j</small></strong></div>`).join("");
    const total = d.total ? `<div class="m-solde m-solde-total"><span class="m-solde-l">Total restant</span><strong>${num(d.total.restant)}<small> j</small></strong></div>` : "";
    const estime = d.estime ? `<p class="m-estime">Si vos ${num(d.estime.jours_en_attente)} j en attente sont validés : congés <strong>${num(d.estime.ca)} j</strong>${d.estime.rtt != null ? ` · RTT <strong>${num(d.estime.rtt)} j</strong>` : ""}</p>` : "";
    const demandes = d.demandes.length
      ? d.demandes.map((r) => `<div class="m-req m-req-${esc(r.statut)}"><div class="m-req-top"><strong>${esc(r.label)}</strong><span class="m-badge m-badge-${esc(r.statut)}">${esc(r.statut_label)}</span></div>
          <div class="m-req-dates">${r.dates.map(esc).join("<br>")}</div><div class="muted">${num(r.jours)} jour${r.jours > 1 ? "s" : ""}${r.soumis_le ? " · demandé le " + esc(r.soumis_le.split("-").reverse().join("/")) : ""}</div>
          ${r.statut === "annulation_demandee" ? `<div class="m-req-note">Annulation demandée : en attente de la décision de votre valideur.</div>`
            : `<button type="button" class="m-link" data-cancel="${r.id}">${r.statut === "validee" ? "Demander l'annulation" : "Annuler la demande"}</button>`}</div>`).join("")
      : `<p class="muted">Aucune demande en cours.</p>`;

    app.innerHTML = `<div class="m-wrap">${head}
      <section class="m-card"><h2>Mes compteurs</h2><div class="m-soldes">${soldes}${total}</div>${estime}</section>
      <button type="button" class="m-new" id="m-new">➕ Nouvelle demande</button>
      <section class="m-card"><h2>Mes demandes en cours</h2>${demandes}</section>
      <section class="m-card"><h2>Mon agenda</h2><div id="m-cal"></div>
        <div id="m-types" class="m-types"></div>
        <p class="m-legend"><span class="m-dot m-dot-val"></span> validé <span class="m-dot m-dot-att"></span> en attente <span class="m-dot m-dot-off"></span> non travaillé</p></section>
      <section class="m-card"><h2>Agenda de mon téléphone</h2><p id="m-sync" class="muted">Chargement…</p><button type="button" class="m-ghost m-ghost-full" id="m-sync-btn">📲 Synchroniser mon agenda</button></section></div>`;
    bind();
    app.querySelectorAll("[data-cancel]").forEach((b) => b.addEventListener("click", () => openCancelSheet(d.demandes.find((x) => String(x.id) === b.dataset.cancel))));
    const firstDay = new Date().getFullYear() === year ? today() : iso(year, 0, 1);
    $("#m-new").addEventListener("click", () => openSheet(d, firstDay));
    drawCalendar(d);
    loadSyncCard();
  }

  function worked(d, day) {
    const p = (d.couverture || []).find((x) => x.start <= day && day <= x.end);
    if (!p) return false;
    const wd = new Date(day + "T12:00:00").getDay() || 7;
    return (p.days || []).map(Number).includes(wd) && (p.ferie || !(d.feries || []).includes(day));
  }

  function drawCalendar(d) {
    const year = d.year, m = state.month, byDay = {};
    (d.agenda || []).forEach((a) => { (byDay[a.d] = byDay[a.d] || {})[a.h] = a; });
    const lead = (new Date(year, m, 1).getDay() || 7) - 1, last = new Date(year, m + 1, 0).getDate(), now = today();
    let cells = "";
    const used = {};
    const colorOf = (code) => { const raw = ((d.codes || {})[code] || {}).color || ""; return /^#[0-9a-fA-F]{3,8}$/.test(raw) ? raw : "#c4573a"; };
    for (let i = 0; i < lead; i++) cells += `<div class="m-day m-day-void"></div>`;
    for (let day = 1; day <= last; day++) {
      const key = iso(year, m, day), info = byDay[key] || {}, ok = worked(d, key);
      const bar = (a, cls) => `<i class="${a.s === "attente" ? "m-att" : "m-val"}${cls || ""}" style="--c:${esc(colorOf(a.code))}" title="${esc(((d.codes || {})[a.code] || {}).label || a.code)}">${esc(a.code)}</i>`;
      const a0 = info[0], a1 = info[1];
      let halves;
      if (a0 && a1 && a0.code === a1.code && a0.s === a1.s) halves = bar(a0, " m-wide");      // journée entière : une seule barre
      else halves = (a0 ? bar(a0) : "<i></i>") + (a1 ? bar(a1) : "<i></i>");
      (a0 ? [a0] : []).concat(a1 ? [a1] : []).forEach((a) => { used[a.code] = true; });
      cells += `<button type="button" class="m-day${ok ? "" : " m-day-off"}${key === now ? " m-day-today" : ""}" data-iso="${key}" ${ok ? "" : "disabled"}><span>${day}</span><div class="m-halves">${halves}</div></button>`;
    }
    $("#m-cal").innerHTML = `<div class="m-cal-nav"><button type="button" id="m-prev-m" ${m === 0 ? "disabled" : ""} aria-label="Mois précédent">‹</button><strong>${MONTHS[m]} ${year}</strong><button type="button" id="m-next-m" ${m === 11 ? "disabled" : ""} aria-label="Mois suivant">›</button></div>
      <div class="m-cal-head"><span>L</span><span>M</span><span>M</span><span>J</span><span>V</span><span>S</span><span>D</span></div><div class="m-cal-grid">${cells}</div>`;
    const kinds = Object.keys(used).map((code) => `<span class="m-key"><span class="m-chip" style="background:${esc(colorOf(code))}"></span>${esc(((((d.codes || {})[code] || {}).label || "").toUpperCase().startsWith(code)) ? ((d.codes || {})[code] || {}).label : code + " " + (((d.codes || {})[code] || {}).label || ""))}</span>`).join("");
    $("#m-types").innerHTML = kinds || `<span class="muted">Aucun congé ce mois-ci.</span>`;
    $("#m-prev-m").addEventListener("click", () => { state.month--; drawCalendar(d); });
    $("#m-next-m").addEventListener("click", () => { state.month++; drawCalendar(d); });
    document.querySelectorAll("#m-cal .m-day[data-iso]").forEach((b) => b.addEventListener("click", () => openSheet(d, b.dataset.iso)));
  }

  /* ----------------------------- demande simple (du … au …) avec répartition par type ----------------------------- */
  const fr = (key) => `${String(Math.floor((key % 1000) / 10)).padStart(2, "0")}/${String(Math.floor(key / 1000)).padStart(2, "0")}`;
  // « du 23/11 au 24/11 » pour un lot de demi-journées consécutives (première en après-midi / dernière le matin précisées)
  function spanText(list) {
    if (!list.length) return "";
    const a = list[0], b = list[list.length - 1];
    const left = a % 10 === 1 ? " (après-midi)" : "", right = b % 10 === 0 ? " (matin)" : "";
    const da = Math.floor(a / 10), db = Math.floor(b / 10);
    return da === db ? `le ${fr(a)}${left || right}` : `du ${fr(a)}${left} au ${fr(b)}${right}`;
  }

  function openSheet(d, day) {
    if ($("#m-sheet")) return;
    const year = d.year;
    const types = (d.demandables || []).slice();
    const tracked = types.filter((t) => t.restant != null && t.restant > 0);
    const untracked = types.filter((t) => t.restant == null);
    const color = (code) => { const raw = ((d.codes || {})[code] || {}).color || ""; return /^#[0-9a-fA-F]{3,8}$/.test(raw) ? raw : "#c4573a"; };
    const qty = {};                                   // demi-journées attribuées à chaque type
    types.forEach((t) => { qty[t.code] = 0; });
    let cells = [], seq = 0;

    const sheet = document.createElement("div");
    sheet.id = "m-sheet";
    sheet.className = "m-sheet";
    sheet.innerHTML = `<div class="m-sheet-card" role="dialog" aria-label="Nouvelle demande">
        <div class="m-sheet-top"><h3>Nouvelle demande</h3><button type="button" id="ms-close" aria-label="Fermer">✕</button></div>
        <div class="m-row"><label>Du<input type="date" id="ms-du" value="${day}" min="${year}-01-01" max="${year}-12-31"></label>
          <label>Premier jour<select id="ms-debut"><option value="matin">dès le matin</option><option value="apres_midi">dès l'après-midi</option></select></label></div>
        <div class="m-row"><label>Au<input type="date" id="ms-au" value="${day}" min="${year}-01-01" max="${year}-12-31"></label>
          <label>Dernier jour<select id="ms-fin"><option value="soir">jusqu'au soir</option><option value="midi">jusqu'à midi</option></select></label></div>
        <div id="ms-preview" class="m-preview muted">Calcul…</div>
        <div id="ms-split" class="m-split hidden"></div>
        <label>Commentaire (facultatif)<input type="text" id="ms-comment" maxlength="200"></label>
        <div id="ms-error" class="form-error hidden"></div>
        <button type="button" class="m-new" id="ms-send" disabled>Envoyer la demande</button></div>`;
    document.body.appendChild(sheet);
    const close = () => sheet.remove();
    $("#ms-close").addEventListener("click", close);
    sheet.addEventListener("mousedown", (e) => { if (e.target === sheet) close(); });

    const maxHalves = (t) => (t.restant == null ? Infinity : Math.floor(t.restant * 2 + 1e-9));
    const allocated = () => types.reduce((n, t) => n + qty[t.code], 0);
    // attribution par défaut : tout sur le premier type qui a du solde (congés annuels), le reste sur le suivant si le solde manque
    const autoFill = () => {
      types.forEach((t) => { qty[t.code] = 0; });
      let left = cells.length;
      for (const t of tracked) { const take = Math.min(left, maxHalves(t)); qty[t.code] = take; left -= take; if (!left) break; }
    };
    // lots de demi-journées, dans l'ordre des types affiché : le premier type prend les premiers jours
    const parts = () => {
      let i = 0;
      return types.filter((t) => qty[t.code] > 0).map((t) => { const lot = cells.slice(i, i + qty[t.code]); i += qty[t.code]; return { code: t.code, cells: lot }; });
    };
    const days = (halves) => num(halves / 2);

    const renderSplit = () => {
      const box = $("#ms-split");
      if (!cells.length) { box.classList.add("hidden"); $("#ms-send").disabled = true; return; }
      const left = cells.length - allocated();
      const lots = Object.fromEntries(parts().map((p) => [p.code, p.cells]));
      const row = (t) => {
        const q = qty[t.code], plusOk = left > 0 && q < maxHalves(t), minusOk = q > 0;
        return `<div class="m-split-row${q ? " m-split-on" : ""}">
          <div class="m-split-l"><span class="m-chip" style="background:${color(t.code)}"></span><div><strong>${esc(t.label)}</strong>
            <small>${t.restant != null ? "solde " + num(t.restant) + " j" : "sans solde suivi"}${lots[t.code] ? " · " + esc(spanText(lots[t.code])) : ""}</small></div></div>
          <div class="m-step"><button type="button" data-code="${esc(t.code)}" data-step="-1" ${minusOk ? "" : "disabled"} aria-label="Retirer un jour">−</button><b>${days(q)}</b>
            <button type="button" data-code="${esc(t.code)}" data-step="1" ${plusOk ? "" : "disabled"} aria-label="Ajouter un jour">+</button></div></div>`;
      };
      box.innerHTML = `<div class="m-split-head"><strong>Répartir ${days(cells.length)} jour${cells.length > 2 ? "s" : ""}</strong>
          <span class="m-split-left ${left === 0 ? "m-ok" : "m-todo"}">${left === 0 ? "✓ tout est réparti" : "reste " + days(left) + " j à répartir"}</span></div>
        ${tracked.map(row).join("")}
        ${untracked.length ? `<details class="m-split-more"${untracked.some((t) => qty[t.code]) ? " open" : ""}><summary>Autres types</summary>${untracked.map(row).join("")}</details>` : ""}
        <p class="m-split-note">Les jours sont attribués dans l'ordre : le premier type prend les premiers jours.</p>`;
      box.classList.remove("hidden");
      $("#ms-send").disabled = left !== 0;
    };
    $("#ms-split").addEventListener("click", (e) => {
      const b = e.target.closest("button[data-code]");
      if (!b || b.disabled) return;
      const t = types.find((x) => x.code === b.dataset.code);
      const left = cells.length - allocated();
      if (b.dataset.step === "1") qty[t.code] += Math.min(2, left, maxHalves(t) - qty[t.code]);
      else qty[t.code] -= qty[t.code] % 2 === 1 ? 1 : Math.min(2, qty[t.code]);
      renderSplit();
    });

    const refresh = async () => {
      const du = $("#ms-du").value, au = $("#ms-au").value, mine = ++seq;
      $("#ms-send").disabled = true;
      $("#ms-error").classList.add("hidden");
      if (!du || !au) { $("#ms-preview").textContent = "Choisissez les dates."; return; }
      if (au < du) { $("#ms-au").value = du; return refresh(); }
      try {
        const r = await api(`/api/mobile/days?du=${du}&au=${au}&debut=${$("#ms-debut").value}&fin=${$("#ms-fin").value}`);
        if (mine !== seq) return;
        cells = r.cells || [];
        $("#ms-preview").innerHTML = cells.length
          ? `<strong>${num(r.jours)} jour${r.jours > 1 ? "s" : ""}</strong> à poser : ${(r.resume || []).map(esc).join(" ; ")}${r.deja_occupees ? `<br><small>${r.deja_occupees} demi-journée(s) déjà prise(s) ou en attente, ignorée(s)</small>` : ""}`
          : "Aucun jour travaillé à poser sur cette période.";
        autoFill();
        renderSplit();
      } catch (e) { if (mine === seq) { cells = []; $("#ms-preview").textContent = e.message; renderSplit(); } }
    };
    ["ms-du", "ms-au", "ms-debut", "ms-fin"].forEach((id) => ["input", "change"].forEach((ev) => $("#" + id).addEventListener(ev, refresh)));
    refresh();

    // Une demande ne porte qu'un type : la répartition crée une demande par type, dans l'ordre des jours.
    $("#ms-send").addEventListener("click", async () => {
      const btn = $("#ms-send"), list = parts();
      btn.disabled = true;
      let sent = 0;
      for (const p of list) {
        try {
          await api("/api/requests", { method: "POST", body: JSON.stringify({
            agent_id: d.fiche.id, request_type: "absence", code: p.code, cells: p.cells, comment: $("#ms-comment").value.trim() }) });
          sent += 1;
        } catch (e) {
          const label = (types.find((t) => t.code === p.code) || {}).label || p.code;
          const msg = `${label} : ${e.message}`;
          if (sent) { close(); toast(`${sent} demande(s) sur ${list.length} envoyée(s). ${msg}`, true); render(); return; }
          const el = $("#ms-error");
          el.textContent = msg;
          el.classList.remove("hidden");
          btn.disabled = false;
          return;
        }
      }
      close();
      toast(list.length > 1 ? `${list.length} demandes envoyées à votre valideur` : "Demande envoyée à votre valideur");
      render();
    });
  }

  /* ----------------------------- annulation d'une demande ----------------------------- */
  // « cancel » : demande en attente -> annulée tout de suite ; « cancel-request » : demande validée -> annulation à faire valider par le valideur.
  function openCancelSheet(r) {
    if ($("#m-sheet")) return;
    const mode = r.statut === "validee" ? "cancel-request" : "cancel";
    const sheet = document.createElement("div");
    sheet.id = "m-sheet";
    sheet.className = "m-sheet";
    sheet.innerHTML = `<div class="m-sheet-card" role="dialog" aria-label="${mode === "cancel" ? "Annuler la demande" : "Demander l'annulation"}">
        <div class="m-sheet-top"><h3>${mode === "cancel" ? "Annuler la demande" : "Demander l'annulation"}</h3><button type="button" id="mc-close" aria-label="Fermer">✕</button></div>
        <div class="m-req m-req-${esc(r.statut)}"><div class="m-req-top"><strong>${esc(r.label)}</strong><span class="m-badge m-badge-${esc(r.statut)}">${esc(r.statut_label)}</span></div>
          <div class="m-req-dates">${r.dates.map(esc).join("<br>")}</div><div class="muted">${num(r.jours)} jour${r.jours > 1 ? "s" : ""}</div></div>
        <p class="muted">${mode === "cancel"
          ? "Cette demande n'est pas encore validée : elle sera annulée immédiatement et les jours seront libérés."
          : "Cette demande est déjà validée : votre valideur doit accepter l'annulation. Les jours restent posés tant qu'il ne l'a pas fait."}</p>
        ${mode === "cancel-request" ? `<label>Motif (facultatif)<input type="text" id="mc-reason" maxlength="200"></label>` : ""}
        <div id="mc-error" class="form-error hidden"></div>
        <div class="m-row"><button type="button" class="m-ghost" id="mc-back">Retour</button>
          <button type="button" class="m-new m-danger" id="mc-go">${mode === "cancel" ? "Annuler la demande" : "Demander l'annulation"}</button></div></div>`;
    document.body.appendChild(sheet);
    const close = () => sheet.remove();
    $("#mc-close").addEventListener("click", close);
    $("#mc-back").addEventListener("click", close);
    sheet.addEventListener("mousedown", (e) => { if (e.target === sheet) close(); });
    $("#mc-go").addEventListener("click", async () => {
      const btn = $("#mc-go");
      btn.disabled = true;
      try {
        await api(`/api/mobile/requests/${r.id}/${mode}`, { method: "POST", body: JSON.stringify({ comment: mode === "cancel-request" ? $("#mc-reason").value.trim() : "" }) });
        close();
        toast(mode === "cancel" ? "Demande annulée" : "Demande d'annulation envoyée à votre valideur");
        render();
      } catch (e) {
        const el = $("#mc-error");
        el.textContent = e.message;
        el.classList.remove("hidden");
        btn.disabled = false;
      }
    });
  }

  /* ----------------------------- agenda du téléphone (abonnement ICS) ----------------------------- */
  // Le lien est personnel et secret : il n'est montré qu'à sa création (le serveur n'en garde que l'empreinte).
  const feedUrl = (token) => `${location.origin}${BASE}/cal/${token}.ics`;

  async function loadSyncCard() {
    const box = $("#m-sync");
    if (!box) return;
    try {
      const s = await api("/api/mobile/calendar");
      box.innerHTML = s.active
        ? `✅ Synchronisation active${s.last_used_at ? ` · dernière lecture par le téléphone le ${esc(s.last_used_at.replace("T", " ").slice(8, 10) + "/" + s.last_used_at.slice(5, 7) + " à " + s.last_used_at.slice(11, 16))}` : " · pas encore lue par le téléphone"}`
        : "Vos congés (✅ validés, ⏳ en attente) dans l'agenda de votre téléphone.";
      $("#m-sync-btn").textContent = s.active ? "Gérer la synchronisation" : "📲 Synchroniser mon agenda";
      $("#m-sync-btn").onclick = () => openSyncSheet(s);
    } catch (e) { box.textContent = e.message; }
  }

  function openSyncSheet(info) {
    if ($("#m-sheet")) return;
    const sheet = document.createElement("div");
    sheet.id = "m-sheet";
    sheet.className = "m-sheet";
    sheet.innerHTML = `<div class="m-sheet-card" role="dialog" aria-label="Agenda du téléphone"><div class="m-sheet-top"><h3>Agenda de mon téléphone</h3><button type="button" id="mz-close" aria-label="Fermer">✕</button></div><div id="mz-body"></div></div>`;
    document.body.appendChild(sheet);
    const close = () => { sheet.remove(); loadSyncCard(); };
    $("#mz-close").addEventListener("click", close);
    sheet.addEventListener("mousedown", (e) => { if (e.target === sheet) close(); });
    const body = $("#mz-body");
    const err = (m) => { const el = $("#mz-error"); if (el) { el.textContent = m; el.classList.remove("hidden"); } };

    const intro = () => {
      body.innerHTML = `<p class="muted">Vos congés apparaîtront dans l'agenda de votre téléphone : <strong>✅ validé</strong>, <strong>⏳ en attente</strong> (provisoire). L'agenda est en lecture seule et se met à jour tout seul ; le rythme dépend de votre téléphone (de quelques minutes à une journée).</p>
        <p class="muted">Aucun motif n'y figure : maladie, congés familiaux ou absences particulières s'affichent « Absence ».</p>
        ${info.active ? `<p>✅ Une synchronisation est active${info.created_at ? " (lien créé le " + esc(info.created_at.slice(8, 10) + "/" + info.created_at.slice(5, 7)) + ")" : ""}. Le lien n'est affiché qu'à sa création : pour vous réabonner, créez-en un nouveau (l'ancien cessera de fonctionner).</p>` : ""}
        <div id="mz-error" class="form-error hidden"></div>
        <button type="button" class="m-new" id="mz-create">${info.active ? "Créer un nouveau lien" : "Créer mon lien d'abonnement"}</button>
        ${info.active ? `<button type="button" class="m-ghost m-ghost-full" id="mz-stop">Arrêter la synchronisation</button>` : ""}`;
      $("#mz-create").addEventListener("click", create);
      const stop = $("#mz-stop");
      if (stop) stop.addEventListener("click", revoke);
    };

    const create = async () => {
      try {
        const r = await api("/api/mobile/calendar/link", { method: "POST", body: "{}" });
        info = { active: true, created_at: "", last_used_at: "" };
        shown(feedUrl(r.token));
      } catch (e) { err(e.message); }
    };
    const revoke = async () => {
      if (!window.confirm("Arrêter la synchronisation ? Le lien actuel cessera de fonctionner et les congés disparaîtront de l'agenda du téléphone.")) return;
      try {
        await api("/api/mobile/calendar/revoke", { method: "POST", body: "{}" });
        info = { active: false };
        toast("Synchronisation arrêtée");
        intro();
      } catch (e) { err(e.message); }
    };

    const shown = (url) => {
      const webcal = url.replace(/^https?:/, "webcal:");
      const google = "https://calendar.google.com/calendar/r?cid=" + encodeURIComponent(webcal);
      const outlook = "https://outlook.office.com/calendar/0/addfromweb?url=" + encodeURIComponent(url) + "&name=" + encodeURIComponent("Mes congés");
      body.innerHTML = `<p><strong>Votre lien est prêt.</strong> Il est personnel : ne le partagez pas. Il n'est affiché qu'une fois.</p>
        <p class="m-help">Touchez votre agenda, puis confirmez l'abonnement :</p>
        <a class="m-new m-anchor" id="mz-apple" href="${esc(webcal)}">🍎 iPhone / Apple Calendrier</a>
        <a class="m-ghost m-anchor m-ghost-full" id="mz-google" href="${esc(google)}" target="_blank" rel="noopener">Google Agenda (Gmail, Android)</a>
        <a class="m-ghost m-anchor m-ghost-full" id="mz-outlook" href="${esc(outlook)}" target="_blank" rel="noopener">Outlook</a>
        <p class="m-help">Google et Outlook lisent le lien depuis Internet ; l'agenda apparaît ensuite sur le téléphone, sur le compte concerné.</p>
        <details class="m-split-more"><summary>Autre agenda : copier le lien</summary>
          <label>Lien d'abonnement<input id="mz-url" readonly value="${esc(url)}"></label>
          <button type="button" class="m-ghost m-ghost-full" id="mz-copy">Copier le lien</button>
          <p class="m-help">Collez-le dans « Ajouter un calendrier par abonnement / à partir de l'URL » de votre application d'agenda.</p></details>
        <div id="mz-error" class="form-error hidden"></div>
        <button type="button" class="m-ghost m-ghost-full" id="mz-done">Terminé</button>`;
      $("#mz-url").addEventListener("focus", (e) => e.target.select());
      $("#mz-copy").addEventListener("click", async () => {
        try { await navigator.clipboard.writeText(url); toast("Lien copié"); }
        catch (_) { $("#mz-url").select(); toast("Sélectionné : copiez-le (appui long)"); }
      });
      $("#mz-done").addEventListener("click", close);
    };
    intro();
  }

  /* ----------------------------- démarrage ----------------------------- */
  (async () => {
    const m = /^#activation=([^.]+)\.(.+)$/.exec(location.hash || "");
    if (m) {                                                // lien du QR code : matricule et code préremplis, puis retiré de l'adresse
      history.replaceState(null, "", location.pathname);
      showActivation({ matricule: decodeURIComponent(m[1]), code: decodeURIComponent(m[2]) });
      return;
    }
    try {
      const me = await api("/api/me");
      state.user = me.user;
      const stored = bioStored();
      if (stored && stored.uid === me.user.id && await bioAvailable()) showLock(stored); else render();
    } catch (_) { showLogin(); }
  })();
})();
