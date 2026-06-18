"use strict";

/* ===========================================================================
 * Carver Admin dashboard — vanilla JS, CSP-safe (no inline anything).
 *
 * Flow: probe /admin/dashboard/metrics → 401/403 shows login, else renders.
 * Auth is cookie-session via /auth/login + /auth/logout.
 * The metrics JSON contract is owned by routes/admin_dashboard.py and unchanged.
 * ======================================================================== */

const METRICS_URL = "/admin/dashboard/metrics";
const LOGIN_URL   = "/auth/login";
const LOGOUT_URL  = "/auth/logout";

let currentDays = 30;
let lastData = null; // retained so a window resize can redraw the chart

/* ---------------------------------------------------------------------------
 * Tiny DOM helpers
 * ------------------------------------------------------------------------- */
function $(id) { return document.getElementById(id); }

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) { node.className = className; }
  if (text !== undefined && text !== null) { node.textContent = String(text); }
  return node;
}

function svgEl(tag, attrs) {
  const node = document.createElementNS("http://www.w3.org/2000/svg", tag);
  if (attrs) {
    Object.keys(attrs).forEach(function (k) { node.setAttribute(k, attrs[k]); });
  }
  return node;
}

function clear(node) {
  if (node) { while (node.firstChild) { node.removeChild(node.firstChild); } }
}

function showScreen(id) {
  ["loading-screen", "login-screen", "dashboard-screen"].forEach(function (s) {
    const node = $(s);
    if (node) { node.classList.toggle("hidden", s !== id); }
  });
}

/* ---------------------------------------------------------------------------
 * Formatting
 * ------------------------------------------------------------------------- */
function num(v) { const n = Number(v); return Number.isFinite(n) ? n : 0; }

function fmtInt(v) { return num(v).toLocaleString("en-US"); }

function fmtMoney(amount, currency) {
  const symbol = (currency === "ZAR" || !currency) ? "R " : (currency + " ");
  return symbol + num(amount).toLocaleString("en-US", {
    minimumFractionDigits: 2, maximumFractionDigits: 2
  });
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

function cap(s) {
  s = String(s || "");
  return s ? s.charAt(0).toUpperCase() + s.slice(1) : "—";
}

function slug(v) {
  return String(v || "").toLowerCase().replace(/[^a-z0-9]+/g, "");
}

/* ---------------------------------------------------------------------------
 * Networking
 * ------------------------------------------------------------------------- */
function fetchMetrics(days) {
  const url = METRICS_URL + "?days=" + encodeURIComponent(days);
  return fetch(url, { credentials: "include", headers: { "Accept": "application/json" } });
}

async function loadAndRender() {
  showScreen("loading-screen");
  try {
    const resp = await fetchMetrics(currentDays);
    if (resp.status === 401 || resp.status === 403) { showLogin(); return; }
    if (!resp.ok) { showLogin("Could not load dashboard (HTTP " + resp.status + ")."); return; }
    const data = await resp.json();
    renderDashboard(data);
    showScreen("dashboard-screen");
  } catch (err) {
    showLogin("Network error loading the dashboard.");
  }
}

/* ---------------------------------------------------------------------------
 * Login / logout
 * ------------------------------------------------------------------------- */
function showLogin(message) {
  showScreen("login-screen");
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
    setLoginError(errEl, "Invalid credentials.");
  } catch (err) {
    setLoginError(errEl, "Network error. Please try again.");
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = "Sign in"; }
  }
}

function setLoginError(errEl, msg) {
  if (errEl) { errEl.textContent = msg; errEl.classList.remove("hidden"); }
}

async function handleLogout() {
  try {
    await fetch(LOGOUT_URL, { method: "POST", credentials: "include" });
  } catch (e) { /* ignore — return to login regardless */ }
  showLogin();
}

/* ---------------------------------------------------------------------------
 * Top-level render
 * ------------------------------------------------------------------------- */
function renderDashboard(data) {
  lastData = data || {};
  const signups = lastData.signups || {};
  const revenue = lastData.revenue || {};
  const tokens = lastData.tokens || {};
  const messages = lastData.messages || {};
  const engagement = lastData.engagement || {};
  const windowDays = num(lastData.window_days) || currentDays;

  const lu = $("last-updated");
  if (lu) { lu.textContent = "Updated " + fmtDate(lastData.generated_at); }
  const sub = $("chart-sub");
  if (sub) { sub.textContent = "Last " + windowDays + " days · website vs WhatsApp"; }
  updateWindowButtons();

  renderKpis(signups, revenue, tokens, messages, engagement);
  drawSignupsChart(signups.timeseries);

  renderTiles("signups-tiles", buildSignupTiles(signups));
  renderRecentSignups(signups.recent);

  renderTiles("revenue-tiles", buildRevenueTiles(revenue));
  renderRecentPayments(revenue);

  renderTiles("tokens-tiles", [
    ["Balance outstanding", fmtInt(tokens.balance_outstanding)],
    ["Token accounts", fmtInt(tokens.accounts)],
    ["Spent on unlocks", fmtInt(tokens.spent_on_unlocks)],
    ["Contact unlocks", fmtInt(tokens.unlocks_count)]
  ]);

  renderTiles("messaging-tiles", buildMessagingTiles(messages));

  renderTiles("engagement-tiles", [
    ["Jobs", fmtInt(engagement.jobs_total)],
    ["Match sessions", fmtInt(engagement.match_sessions)],
    ["Feedback", fmtInt(engagement.feedback_submissions)],
    ["Documents", fmtInt(engagement.documents)]
  ]);
}

/* ---------------------------------------------------------------------------
 * KPI cards
 * ------------------------------------------------------------------------- */
function kpiCard(label, value, foot, variant) {
  const card = el("div", "kpi" + (variant ? " " + variant : ""));
  card.appendChild(el("div", "kpi-label", label));
  card.appendChild(el("div", "kpi-value", value));
  if (foot) { card.appendChild(el("div", "kpi-foot", foot)); }
  return card;
}

function renderKpis(signups, revenue, tokens, messages, engagement) {
  const grid = $("kpi-grid");
  if (!grid) { return; }
  clear(grid);

  const web = num(signups.website);
  const wa = num(signups.whatsapp);

  grid.appendChild(kpiCard("Total signups", fmtInt(signups.total),
    fmtInt(signups.active_users) + " active", "web"));
  grid.appendChild(kpiCard("Website", fmtInt(web), "via web app", "web"));
  grid.appendChild(kpiCard("WhatsApp", fmtInt(wa), "via WhatsApp", "wa"));
  grid.appendChild(kpiCard("Revenue", fmtMoney(revenue.total_paid, revenue.currency),
    fmtInt(revenue.paying_customers) + " paying", "green"));
  grid.appendChild(kpiCard("Tokens out", fmtInt(tokens.balance_outstanding),
    fmtInt(tokens.unlocks_count) + " unlocks", "amber"));
  grid.appendChild(kpiCard("WA messages", fmtInt(messages.whatsapp_total),
    fmtInt(messages.active_sessions) + " sessions", "wa"));
  grid.appendChild(kpiCard("Jobs", fmtInt(engagement.jobs_total),
    fmtInt(engagement.match_sessions) + " matches", "violet"));
}

/* ---------------------------------------------------------------------------
 * SVG signups chart (dual area + line, hover tooltip)
 * ------------------------------------------------------------------------- */
function drawSignupsChart(timeseries) {
  const host = $("signups-chart");
  if (!host) { return; }
  clear(host);

  const rows = Array.isArray(timeseries) ? timeseries : [];
  if (rows.length === 0) {
    host.appendChild(el("div", "chart-empty", "No signup activity in this window."));
    return;
  }

  // viewBox geometry (responsive via width:100% on the svg)
  const W = 900, H = 280;
  const m = { top: 16, right: 16, bottom: 28, left: 36 };
  const innerW = W - m.left - m.right;
  const innerH = H - m.top - m.bottom;

  let max = 0;
  rows.forEach(function (r) {
    max = Math.max(max, num(r && r.website), num(r && r.whatsapp));
  });
  if (max <= 0) { max = 1; }
  const yMax = niceMax(max);

  const n = rows.length;
  const xAt = function (i) {
    return m.left + (n === 1 ? innerW / 2 : (i / (n - 1)) * innerW);
  };
  const yAt = function (v) {
    return m.top + innerH - (num(v) / yMax) * innerH;
  };

  const svg = svgEl("svg", { viewBox: "0 0 " + W + " " + H, preserveAspectRatio: "none" });

  // horizontal gridlines + y labels (4 steps)
  const steps = 4;
  for (let s = 0; s <= steps; s++) {
    const val = (yMax / steps) * s;
    const y = yAt(val);
    svg.appendChild(svgEl("line", {
      class: "grid-line", x1: m.left, y1: y, x2: W - m.right, y2: y
    }));
    const lbl = svgEl("text", { class: "axis-text", x: m.left - 8, y: y + 3, "text-anchor": "end" });
    lbl.textContent = String(Math.round(val));
    svg.appendChild(lbl);
  }

  // area + line builders
  function areaPath(key) {
    let d = "M " + xAt(0) + " " + (m.top + innerH);
    rows.forEach(function (r, i) { d += " L " + xAt(i) + " " + yAt(r && r[key]); });
    d += " L " + xAt(n - 1) + " " + (m.top + innerH) + " Z";
    return d;
  }
  function linePath(key) {
    let d = "";
    rows.forEach(function (r, i) {
      d += (i === 0 ? "M " : " L ") + xAt(i) + " " + yAt(r && r[key]);
    });
    return d;
  }

  svg.appendChild(svgEl("path", { class: "area-web", d: areaPath("website") }));
  svg.appendChild(svgEl("path", { class: "area-wa",  d: areaPath("whatsapp") }));
  svg.appendChild(svgEl("path", { class: "line-web", d: linePath("website") }));
  svg.appendChild(svgEl("path", { class: "line-wa",  d: linePath("whatsapp") }));

  // x-axis date labels (~8 across)
  const step = Math.max(1, Math.ceil(n / 8));
  rows.forEach(function (r, i) {
    if (i % step !== 0 && i !== n - 1) { return; }
    const t = svgEl("text", { class: "axis-text", x: xAt(i), y: H - 8, "text-anchor": "middle" });
    t.textContent = fmtDateShort(r && r.date);
    svg.appendChild(t);
  });

  // hover cursor + hit area
  const cursor = svgEl("line", {
    class: "chart-cursor", x1: 0, y1: m.top, x2: 0, y2: m.top + innerH,
    style: "opacity:0"
  });
  svg.appendChild(cursor);
  const hit = svgEl("rect", {
    class: "chart-hit", x: m.left, y: m.top, width: innerW, height: innerH
  });
  svg.appendChild(hit);

  const tip = el("div", "chart-tip");
  tip.style.display = "none";
  host.appendChild(svg);
  host.appendChild(tip);

  function nearestIndex(clientX) {
    const box = svg.getBoundingClientRect();
    const scale = W / box.width;
    const px = (clientX - box.left) * scale;
    let best = 0, bestD = Infinity;
    for (let i = 0; i < n; i++) {
      const d = Math.abs(xAt(i) - px);
      if (d < bestD) { bestD = d; best = i; }
    }
    return best;
  }

  hit.addEventListener("mousemove", function (ev) {
    const i = nearestIndex(ev.clientX);
    const r = rows[i] || {};
    const box = svg.getBoundingClientRect();
    const scale = box.width / W;

    cursor.setAttribute("x1", xAt(i));
    cursor.setAttribute("x2", xAt(i));
    cursor.setAttribute("style", "opacity:1");

    clear(tip);
    tip.appendChild(el("div", "tip-date", fmtDateShort(r.date)));
    const rowWeb = el("div", "tip-row");
    rowWeb.appendChild(el("i", "dot dot-web"));
    rowWeb.appendChild(el("span", null, "Website  " + num(r.website)));
    const rowWa = el("div", "tip-row");
    rowWa.appendChild(el("i", "dot dot-wa"));
    rowWa.appendChild(el("span", null, "WhatsApp  " + num(r.whatsapp)));
    tip.appendChild(rowWeb);
    tip.appendChild(rowWa);

    tip.style.display = "block";
    tip.style.left = (xAt(i) * scale) + "px";
    tip.style.top = (m.top * scale + 6) + "px";
  });
  hit.addEventListener("mouseleave", function () {
    tip.style.display = "none";
    cursor.setAttribute("style", "opacity:0");
  });
}

// round a max up to a clean axis bound
function niceMax(v) {
  if (v <= 5) { return 5; }
  const pow = Math.pow(10, Math.floor(Math.log10(v)));
  const f = v / pow;
  let nf;
  if (f <= 1) { nf = 1; }
  else if (f <= 2) { nf = 2; }
  else if (f <= 5) { nf = 5; }
  else { nf = 10; }
  return nf * pow;
}

/* ---------------------------------------------------------------------------
 * Stat tiles
 * ------------------------------------------------------------------------- */
function renderTiles(containerId, tiles) {
  const c = $(containerId);
  if (!c) { return; }
  clear(c);
  tiles.forEach(function (t) {
    const tile = el("div", "tile");
    tile.appendChild(el("div", "tile-label", t[0]));
    tile.appendChild(el("div", "tile-value", t[1]));
    c.appendChild(tile);
  });
}

function buildSignupTiles(signups) {
  const byRole = signups.by_role || {};
  const tiles = [
    ["Total", fmtInt(signups.total)],
    ["Active", fmtInt(signups.active_users)],
    ["Subscribed", fmtInt(signups.subscribed_users)],
    ["Website", fmtInt(signups.website)],
    ["WhatsApp", fmtInt(signups.whatsapp)]
  ];
  Object.keys(byRole).forEach(function (role) {
    tiles.push([cap(role), fmtInt(byRole[role])]);
  });
  return tiles;
}

function buildRevenueTiles(revenue) {
  const byStatus = revenue.by_status || {};
  const tiles = [
    ["Total paid", fmtMoney(revenue.total_paid, revenue.currency)],
    ["Paying customers", fmtInt(revenue.paying_customers)],
    ["Paid txns", fmtInt(revenue.transactions_paid)],
    ["All txns", fmtInt(revenue.transactions_total)]
  ];
  Object.keys(byStatus).forEach(function (st) {
    tiles.push([cap(st), fmtInt(byStatus[st])]);
  });
  return tiles;
}

function buildMessagingTiles(messages) {
  const byMode = messages.sessions_by_mode || {};
  const tiles = [
    ["Total messages", fmtInt(messages.whatsapp_total)],
    ["Inbound", fmtInt(messages.inbound)],
    ["Outbound", fmtInt(messages.outbound)],
    ["Active sessions", fmtInt(messages.active_sessions)]
  ];
  Object.keys(byMode).forEach(function (mode) {
    tiles.push([cap(mode) + " mode", fmtInt(byMode[mode])]);
  });
  return tiles;
}

/* ---------------------------------------------------------------------------
 * Tables
 * ------------------------------------------------------------------------- */
function badge(text) {
  return el("span", "badge badge-" + slug(text), safeText(text));
}

function emptyRow(tbody, colspan, message) {
  const tr = el("tr", "table-empty");
  const td = el("td", null, message);
  td.colSpan = colspan;
  tr.appendChild(td);
  tbody.appendChild(tr);
}

function renderRecentSignups(recent) {
  const tbody = $("signups-recent");
  if (!tbody) { return; }
  clear(tbody);
  const rows = Array.isArray(recent) ? recent : [];
  if (rows.length === 0) { emptyRow(tbody, 5, "No recent signups."); return; }
  rows.forEach(function (r) {
    r = r || {};
    const tr = el("tr");
    tr.appendChild(el("td", null, safeText(r.name)));
    tr.appendChild(el("td", null, safeText(r.identifier)));
    tr.appendChild(el("td", null, safeText(r.role)));
    const src = el("td"); src.appendChild(badge(r.source)); tr.appendChild(src);
    tr.appendChild(el("td", null, fmtDate(r.created_at)));
    tbody.appendChild(tr);
  });
}

function renderRecentPayments(revenue) {
  const tbody = $("revenue-recent");
  if (!tbody) { return; }
  clear(tbody);
  const rows = Array.isArray(revenue.recent_payments) ? revenue.recent_payments : [];
  if (rows.length === 0) { emptyRow(tbody, 4, "No recent payments."); return; }
  const currency = revenue.currency;
  rows.forEach(function (p) {
    p = p || {};
    const tr = el("tr");
    tr.appendChild(el("td", null, safeText(p.user_key)));
    tr.appendChild(el("td", null, fmtMoney(p.amount, currency)));
    const st = el("td"); st.appendChild(badge(p.status)); tr.appendChild(st);
    tr.appendChild(el("td", null, fmtDate(p.created_at)));
    tbody.appendChild(tr);
  });
}

/* ---------------------------------------------------------------------------
 * Window selector
 * ------------------------------------------------------------------------- */
function updateWindowButtons() {
  const sel = $("window-selector");
  if (!sel) { return; }
  sel.querySelectorAll("button").forEach(function (b) {
    b.classList.toggle("active", num(b.getAttribute("data-days")) === currentDays);
  });
}

function handleWindowClick(event) {
  const target = event.target.closest ? event.target.closest("button[data-days]") : null;
  if (!target) { return; }
  const days = num(target.getAttribute("data-days"));
  if (!days || days === currentDays) { return; }
  currentDays = days;
  updateWindowButtons();
  loadAndRender();
}

/* ---------------------------------------------------------------------------
 * Sidebar scroll-spy navigation
 * ------------------------------------------------------------------------- */
function setupScrollSpy() {
  const links = Array.prototype.slice.call(document.querySelectorAll(".nav-link"));
  if (!links.length || !("IntersectionObserver" in window)) { return; }

  const byId = {};
  links.forEach(function (l) { byId[l.getAttribute("data-target")] = l; });

  const observer = new IntersectionObserver(function (entries) {
    entries.forEach(function (entry) {
      if (entry.isIntersecting) {
        links.forEach(function (l) { l.classList.remove("active"); });
        const active = byId[entry.target.id];
        if (active) { active.classList.add("active"); }
      }
    });
  }, { rootMargin: "-45% 0px -50% 0px", threshold: 0 });

  links.forEach(function (l) {
    const sec = $(l.getAttribute("data-target"));
    if (sec) { observer.observe(sec); }
  });

  // smooth-scroll on click (anchor default works too, but this is nicer)
  links.forEach(function (l) {
    l.addEventListener("click", function (ev) {
      const sec = $(l.getAttribute("data-target"));
      if (sec) { ev.preventDefault(); sec.scrollIntoView({ behavior: "smooth", block: "start" }); }
    });
  });
}

/* ---------------------------------------------------------------------------
 * Wire-up + boot
 * ------------------------------------------------------------------------- */
function debounce(fn, ms) {
  let t = null;
  return function () {
    clearTimeout(t);
    t = setTimeout(fn, ms);
  };
}

function wire() {
  const loginForm = $("login-form");
  if (loginForm) { loginForm.addEventListener("submit", handleLogin); }

  const logoutBtn = $("logout-btn");
  if (logoutBtn) { logoutBtn.addEventListener("click", handleLogout); }

  const refreshBtn = $("refresh-btn");
  if (refreshBtn) { refreshBtn.addEventListener("click", loadAndRender); }

  const sel = $("window-selector");
  if (sel) { sel.addEventListener("click", handleWindowClick); }

  // redraw the SVG chart on resize so the tooltip geometry stays accurate
  window.addEventListener("resize", debounce(function () {
    if (lastData && lastData.signups) { drawSignupsChart(lastData.signups.timeseries); }
  }, 200));

  setupScrollSpy();
  loadAndRender();
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", wire);
} else {
  wire();
}
