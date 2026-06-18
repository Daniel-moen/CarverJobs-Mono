"use strict";

/* ---------------------------------------------------------------------------
 * Carver Admin dashboard — vanilla JS, CSP-safe (no inline anything).
 * Probes /admin/dashboard/metrics; shows login on 401/403, else renders.
 * ------------------------------------------------------------------------- */

const METRICS_URL = "/admin/dashboard/metrics";
const LOGIN_URL = "/auth/login";
const LOGOUT_URL = "/auth/logout";

let currentDays = 30;

/* ---------- small DOM/util helpers ---------- */
function $(id) { return document.getElementById(id); }

function show(id) {
  ["loading-screen", "login-screen", "dashboard-screen"].forEach(function (s) {
    const el = $(s);
    if (el) { el.classList.toggle("hidden", s !== id); }
  });
}

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) { node.className = className; }
  if (text !== undefined && text !== null) { node.textContent = String(text); }
  return node;
}

function clear(node) { if (node) { while (node.firstChild) { node.removeChild(node.firstChild); } } }

// Defensive numeric coercion.
function num(v) {
  const n = Number(v);
  return Number.isFinite(n) ? n : 0;
}

function fmtInt(v) {
  return num(v).toLocaleString("en-US");
}

function fmtMoney(amount, currency) {
  const symbol = (currency === "ZAR" || !currency) ? "R" : (currency + " ");
  const n = num(amount);
  return symbol + " " + n.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function fmtDate(iso) {
  if (!iso) { return "—"; }
  const d = new Date(iso);
  if (isNaN(d.getTime())) { return String(iso); }
  return d.toLocaleString("en-GB", {
    year: "numeric", month: "short", day: "2-digit",
    hour: "2-digit", minute: "2-digit"
  });
}

function fmtDateShort(iso) {
  if (!iso) { return ""; }
  const d = new Date(iso);
  if (isNaN(d.getTime())) { return String(iso); }
  return d.toLocaleDateString("en-GB", { month: "short", day: "2-digit" });
}

function safeText(v) {
  if (v === undefined || v === null || v === "") { return "—"; }
  return String(v);
}

/* ---------- networking ---------- */
async function fetchMetrics(days) {
  const url = METRICS_URL + "?days=" + encodeURIComponent(days);
  return fetch(url, { credentials: "include", headers: { "Accept": "application/json" } });
}

/* ---------- boot ---------- */
async function init() {
  show("loading-screen");
  try {
    const resp = await fetchMetrics(currentDays);
    if (resp.status === 401 || resp.status === 403) {
      showLogin();
      return;
    }
    if (!resp.ok) {
      // Unexpected error — still show login as a safe fallback.
      showLogin("Could not load dashboard (HTTP " + resp.status + ").");
      return;
    }
    const data = await resp.json();
    renderDashboard(data);
    show("dashboard-screen");
  } catch (err) {
    showLogin("Network error. Check your connection and sign in.");
  }
}

/* ---------- login ---------- */
function showLogin(message) {
  show("login-screen");
  const errEl = $("login-error");
  if (errEl) {
    if (message) { errEl.textContent = message; errEl.classList.remove("hidden"); }
    else { errEl.textContent = ""; errEl.classList.add("hidden"); }
  }
  const u = $("login-username");
  if (u) { u.focus(); }
}

async function handleLogin(event) {
  event.preventDefault();
  const errEl = $("login-error");
  const btn = $("login-submit");
  const username = ($("login-username") || {}).value || "";
  const password = ($("login-password") || {}).value || "";

  if (errEl) { errEl.classList.add("hidden"); }
  if (btn) { btn.disabled = true; btn.textContent = "Signing in…"; }

  try {
    const resp = await fetch(LOGIN_URL, {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json", "Accept": "application/json" },
      body: JSON.stringify({ username: username, password: password })
    });

    let body = {};
    try { body = await resp.json(); } catch (e) { body = {}; }

    if (resp.ok && body && body.ok) {
      const pw = $("login-password");
      if (pw) { pw.value = ""; }
      await loadAndRender();
      return;
    }
    showLoginError(errEl, "Invalid credentials.");
  } catch (err) {
    showLoginError(errEl, "Network error. Please try again.");
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = "Sign in"; }
  }
}

function showLoginError(errEl, msg) {
  if (errEl) { errEl.textContent = msg; errEl.classList.remove("hidden"); }
}

async function handleLogout() {
  try {
    await fetch(LOGOUT_URL, { method: "POST", credentials: "include" });
  } catch (e) { /* ignore — return to login regardless */ }
  showLogin();
}

/* ---------- load + render flow ---------- */
async function loadAndRender() {
  show("loading-screen");
  try {
    const resp = await fetchMetrics(currentDays);
    if (resp.status === 401 || resp.status === 403) { showLogin(); return; }
    if (!resp.ok) { showLogin("Could not load dashboard (HTTP " + resp.status + ")."); return; }
    const data = await resp.json();
    renderDashboard(data);
    show("dashboard-screen");
  } catch (err) {
    showLogin("Network error loading the dashboard.");
  }
}

/* ---------- rendering ---------- */
function renderDashboard(data) {
  data = data || {};
  const signups = data.signups || {};
  const revenue = data.revenue || {};
  const tokens = data.tokens || {};
  const messages = data.messages || {};
  const engagement = data.engagement || {};
  const windowDays = num(data.window_days) || currentDays;

  // Header
  const lu = $("last-updated");
  if (lu) { lu.textContent = "Updated " + fmtDate(data.generated_at); }
  const sw = $("signups-window");
  if (sw) { sw.textContent = "(last " + windowDays + " days)"; }
  updateWindowButtons();

  renderKpis(signups, revenue, tokens, messages);
  renderSignupsChart(signups.timeseries);
  renderSignupsSubstats(signups);
  renderSignupsRecent(signups.recent);
  renderRevenueSubstats(revenue);
  renderRevenueRecent(revenue);
  renderTokens(tokens);
  renderMessages(messages);
  renderEngagement(engagement);
}

function kpiCard(label, value, variant) {
  const card = el("div", "kpi-card" + (variant ? " " + variant : ""));
  card.appendChild(el("div", "kpi-label", label));
  card.appendChild(el("div", "kpi-value", value));
  return card;
}

function renderKpis(signups, revenue, tokens, messages) {
  const grid = $("kpi-grid");
  if (!grid) { return; }
  clear(grid);
  grid.appendChild(kpiCard("Total signups", fmtInt(signups.total)));
  grid.appendChild(kpiCard("Website signups", fmtInt(signups.website), "accent"));
  grid.appendChild(kpiCard("WhatsApp signups", fmtInt(signups.whatsapp), "wa"));
  grid.appendChild(kpiCard("Total revenue", fmtMoney(revenue.total_paid, revenue.currency), "green"));
  grid.appendChild(kpiCard("Paying customers", fmtInt(revenue.paying_customers), "green"));
  grid.appendChild(kpiCard("WhatsApp messages", fmtInt(messages.whatsapp_total), "wa"));
  grid.appendChild(kpiCard("Tokens outstanding", fmtInt(tokens.balance_outstanding)));
}

function renderSignupsChart(timeseries) {
  const chart = $("signups-chart");
  if (!chart) { return; }
  clear(chart);
  const rows = Array.isArray(timeseries) ? timeseries : [];
  if (rows.length === 0) {
    chart.appendChild(el("div", "chart-empty", "No signup activity in this window."));
    return;
  }
  let max = 0;
  rows.forEach(function (r) {
    const total = num(r && r.website) + num(r && r.whatsapp);
    if (total > max) { max = total; }
  });
  if (max <= 0) { max = 1; }

  // Avoid clutter: label roughly 12 dates across the axis.
  const step = Math.ceil(rows.length / 12);

  rows.forEach(function (r, i) {
    r = r || {};
    const web = num(r.website);
    const wa = num(r.whatsapp);
    const col = el("div", "bar-col");
    col.title = (r.date || "") + " — website " + web + ", whatsapp " + wa;

    const stack = el("div", "bar-stack");
    const webSeg = el("div", "bar-seg web");
    webSeg.style.height = ((web / max) * 100) + "%";
    const waSeg = el("div", "bar-seg wa");
    waSeg.style.height = ((wa / max) * 100) + "%";
    stack.appendChild(webSeg);
    stack.appendChild(waSeg);
    col.appendChild(stack);

    const label = el("div", "bar-date", (i % step === 0) ? fmtDateShort(r.date) : "");
    col.appendChild(label);
    chart.appendChild(col);
  });
}

function statTile(label, value) {
  const s = el("div", "stat");
  s.appendChild(el("div", "stat-label", label));
  s.appendChild(el("div", "stat-value", value));
  return s;
}

function renderStats(containerId, tiles) {
  const c = $(containerId);
  if (!c) { return; }
  clear(c);
  tiles.forEach(function (t) { c.appendChild(statTile(t[0], t[1])); });
}

function renderSignupsSubstats(signups) {
  const byRole = signups.by_role || {};
  const tiles = [
    ["Active users", fmtInt(signups.active_users)],
    ["Subscribed users", fmtInt(signups.subscribed_users)]
  ];
  Object.keys(byRole).forEach(function (role) {
    tiles.push([cap(role) + " (role)", fmtInt(byRole[role])]);
  });
  renderStats("signups-substats", tiles);
}

function cap(s) { s = String(s || ""); return s ? s.charAt(0).toUpperCase() + s.slice(1) : "—"; }

function badge(text, prefix) {
  const cls = "badge " + prefix + "-" + String(text || "").toLowerCase().replace(/[^a-z0-9]+/g, "");
  return el("span", cls, safeText(text));
}

function renderSignupsRecent(recent) {
  const tbody = $("signups-recent");
  if (!tbody) { return; }
  clear(tbody);
  const rows = Array.isArray(recent) ? recent : [];
  if (rows.length === 0) {
    appendEmptyRow(tbody, 5, "No recent signups.");
    return;
  }
  rows.forEach(function (r) {
    r = r || {};
    const tr = el("tr");
    tr.appendChild(el("td", null, safeText(r.name)));
    tr.appendChild(el("td", null, safeText(r.identifier)));
    tr.appendChild(el("td", null, safeText(r.role)));
    const srcTd = el("td");
    srcTd.appendChild(badge(r.source, "src"));
    tr.appendChild(srcTd);
    tr.appendChild(el("td", null, fmtDate(r.created_at)));
    tbody.appendChild(tr);
  });
}

function renderRevenueSubstats(revenue) {
  const byStatus = revenue.by_status || {};
  const tiles = [
    ["Total paid", fmtMoney(revenue.total_paid, revenue.currency)],
    ["Paying customers", fmtInt(revenue.paying_customers)],
    ["Paid / total txns", fmtInt(revenue.transactions_paid) + " / " + fmtInt(revenue.transactions_total)]
  ];
  Object.keys(byStatus).forEach(function (st) {
    tiles.push([cap(st), fmtInt(byStatus[st])]);
  });
  renderStats("revenue-substats", tiles);
}

function renderRevenueRecent(revenue) {
  const tbody = $("revenue-recent");
  if (!tbody) { return; }
  clear(tbody);
  const rows = Array.isArray(revenue.recent_payments) ? revenue.recent_payments : [];
  if (rows.length === 0) {
    appendEmptyRow(tbody, 4, "No recent payments.");
    return;
  }
  const currency = revenue.currency;
  rows.forEach(function (p) {
    p = p || {};
    const tr = el("tr");
    tr.appendChild(el("td", null, safeText(p.user_key)));
    tr.appendChild(el("td", null, fmtMoney(p.amount, currency)));
    const stTd = el("td");
    stTd.appendChild(badge(p.status, "st"));
    tr.appendChild(stTd);
    tr.appendChild(el("td", null, fmtDate(p.created_at)));
    tbody.appendChild(tr);
  });
}

function renderTokens(tokens) {
  renderStats("tokens-substats", [
    ["Balance outstanding", fmtInt(tokens.balance_outstanding)],
    ["Accounts", fmtInt(tokens.accounts)],
    ["Spent on unlocks", fmtInt(tokens.spent_on_unlocks)],
    ["Unlocks count", fmtInt(tokens.unlocks_count)]
  ]);
}

function renderMessages(messages) {
  const byMode = messages.sessions_by_mode || {};
  const tiles = [
    ["WhatsApp total", fmtInt(messages.whatsapp_total)],
    ["Inbound", fmtInt(messages.inbound)],
    ["Outbound", fmtInt(messages.outbound)],
    ["Active sessions", fmtInt(messages.active_sessions)]
  ];
  Object.keys(byMode).forEach(function (mode) {
    tiles.push([cap(mode) + " sessions", fmtInt(byMode[mode])]);
  });
  renderStats("messages-substats", tiles);
}

function renderEngagement(engagement) {
  renderStats("engagement-substats", [
    ["Jobs total", fmtInt(engagement.jobs_total)],
    ["Match sessions", fmtInt(engagement.match_sessions)],
    ["Feedback", fmtInt(engagement.feedback_submissions)],
    ["Documents", fmtInt(engagement.documents)]
  ]);
}

function appendEmptyRow(tbody, colspan, message) {
  const tr = el("tr", "table-empty");
  const td = el("td", null, message);
  td.colSpan = colspan;
  tr.appendChild(td);
  tbody.appendChild(tr);
}

/* ---------- window selector ---------- */
function updateWindowButtons() {
  const sel = $("window-selector");
  if (!sel) { return; }
  const btns = sel.querySelectorAll(".btn-chip");
  btns.forEach(function (b) {
    b.classList.toggle("active", num(b.getAttribute("data-days")) === currentDays);
  });
}

function handleWindowClick(event) {
  const target = event.target.closest ? event.target.closest(".btn-chip") : null;
  if (!target) { return; }
  const days = num(target.getAttribute("data-days"));
  if (!days || days === currentDays) { return; }
  currentDays = days;
  updateWindowButtons();
  loadAndRender();
}

/* ---------- wire up ---------- */
function wire() {
  const loginForm = $("login-form");
  if (loginForm) { loginForm.addEventListener("submit", handleLogin); }

  const logoutBtn = $("logout-btn");
  if (logoutBtn) { logoutBtn.addEventListener("click", handleLogout); }

  const refreshBtn = $("refresh-btn");
  if (refreshBtn) { refreshBtn.addEventListener("click", loadAndRender); }

  const sel = $("window-selector");
  if (sel) { sel.addEventListener("click", handleWindowClick); }

  init();
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", wire);
} else {
  wire();
}
