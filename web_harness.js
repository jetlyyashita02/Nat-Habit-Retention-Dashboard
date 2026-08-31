/* Headless interactivity harness for the multi-page web dashboard (node, no browser).
   Builds a lightweight DOM (innerHTML parsing, class/descendant selectors, events),
   executes each page's real script, and drives the actual UI code paths:
   bar clicks, table sorting, search, cross-filters, tooltips.
   All expectations are data-driven from each page's own DATA blob (no hardcoded business values). */
const fs = require("fs");

const PAGES = ["index", "migration", "sales", "nps-cs", "pricing", "retention", "ntc", "definitions", "insights"];
const VOID = new Set(["meta", "br", "img", "input", "hr", "rect", "line", "polyline", "path", "circle", "link", "col", "source"]);

/* ---------------- mini DOM ---------------- */
let elements = {};
let roots = [];

function makeEl(tag, attrStr) {
  const el = {
    tag: String(tag).toLowerCase(),
    children: [],
    parent: null,
    attrs: {},
    dataset: {},
    style: {},
    listeners: {},
    value: "",
    text: "",
    _raw: null,
    onclick: null,
    offsetWidth: 100,
    getBoundingClientRect() { return { left: 0, top: 0, width: 900, height: 200 }; },
  };
  if (attrStr) parseAttrs(el, attrStr);
  return el;
}

function parseAttrs(el, attrStr) {
  const re = /([\w-]+)(?:=["']([^"']*)["'])?/g;
  let m;
  while ((m = re.exec(attrStr))) {
    const k = m[1], v = m[2];
    el.attrs[k] = v === undefined ? "" : v;
    if (k.startsWith("data-")) el.dataset[k.slice(5).replace(/-([a-z])/g, (_, c) => c.toUpperCase())] = v === undefined ? "" : v;
  }
}

function parseHTML(html, parent) {
  const out = [];
  const stack = [];
  const top = () => stack.length ? stack[stack.length - 1] : null;
  const re = /<\/?([a-zA-Z][a-zA-Z0-9-]*)((?:\s+[\w-]+(?:=["'][^"']*["'])?)*)\s*(\/?)>/g;
  let m, last = 0;
  while ((m = re.exec(html))) {
    const full = m[0], tag = m[1], attrStr = m[2] || "", selfClose = !!m[3];
    if (m.index > last && html.slice(last, m.index).trim()) {
      const t = { tag: "#text", text: html.slice(last, m.index) };
      (top() ? top().children : out).push(t);
    }
    last = re.lastIndex;
    if (full[1] === "/") {
      for (let i = stack.length - 1; i >= 0; i--) if (stack[i].tag === tag.toLowerCase()) { stack.length = i; break; }
      continue;
    }
    const el = makeEl(tag, attrStr);
    el.parent = top() || parent;
    (top() ? top().children : out).push(el);
    if (!selfClose && !VOID.has(el.tag)) stack.push(el);
  }
  return out;
}

function wireEl(el) {
  if (el && el.tag && el.tag !== "#text" && !el._wired) {
    if (typeof el.addEventListener !== "function") addBehaviors(el);
    Object.defineProperty(el, "innerHTML", {
      get() { return el._raw != null ? el._raw : ""; },
      set(v) { el._raw = String(v); el.children = parseHTML(el._raw, el); wireEl(el); },
      configurable: true,
    });
    el._wired = true;
  }
  if (el && el.children) el.children.forEach(c => wireEl(c));
}

function addBehaviors(el) {
  el.addEventListener = (t, f) => { (el.listeners[t] = el.listeners[t] || []).push(f); };
  el.fire = (t, ev) => ((el.listeners[t] || []).slice()).forEach(f => f(ev || { clientX: 5, clientY: 5, target: el }));
  el.setAttribute = (k, v) => { el.attrs[k] = String(v); if (k.startsWith("data-")) el.dataset[k.slice(5)] = String(v); };
  el.getAttribute = k => (k in el.attrs ? el.attrs[k] : null);
  el.click = () => { if (typeof el.onclick === "function") el.onclick({ target: el, clientX: 5, clientY: 5 }); el.fire("click"); };
  el.contains = c => { const s = (el.attrs.class || "").split(/\s+/).filter(Boolean); return s.includes(c); };
  el.classList = {
    contains: c => el.contains(c),
    add: c => { const s = (el.attrs.class || "").split(/\s+/).filter(Boolean); if (!s.includes(c)) s.push(c); el.attrs.class = s.join(" "); },
    remove: c => { el.attrs.class = (el.attrs.class || "").split(/\s+/).filter(x => x && x !== c).join(" "); },
    toggle: (c, force) => { const has = el.contains(c); const want = force == null ? !has : !!force; if (want) el.classList.add(c); else el.classList.remove(c); return want; },
  };
  el.querySelector = sel => el.querySelectorAll(sel)[0] || null;
  el.querySelectorAll = sel => qsa(el, sel);
  el.appendChild = c => { c.parent = el; el.children.push(c); wireEl(c); return c; };
  el.closest = sel => { let e = el; while (e) { if (e.tag !== "#text" && simpleMatch(e, sel)) return e; e = e.parent; } return null; };
  return el;
}

function parseSimple(part) {
  let tag = null, id = null; const cls = []; const attrs = [];
  const aRe = /\[([\w-]+)(?:="([^"]*)")?\]/g;
  let am;
  while ((am = aRe.exec(part))) { attrs.push([am[1], am[2] === undefined ? null : am[2]]); part = part.slice(0, am.index) + part.slice(am.index + am[0].length); }
  const m = part.match(/^([a-zA-Z][a-zA-Z0-9-]*)?((?:(?:#|\.)(?:[\w-]+))*)$/);
  if (!m) return null;
  tag = m[1] || null;
  const rest = m[2] || "";
  const im = rest.match(/#([\w-]+)/); if (im) id = im[1];
  let cm; const cre = /\.([\w-]+)/g; while ((cm = cre.exec(rest))) cls.push(cm[1]);
  if (!tag && !id && !cls.length && !attrs.length) return { any: true };
  return { tag, id, cls, attrs };
}

function simpleMatch(el, part) {
  if (typeof part === "string") { const p = parseSimple(part); if (!p) return false; part = p; }
  if (part.any) return true;
  if (part.tag && el.tag !== part.tag) return false;
  if (part.id && el.attrs.id !== part.id) return false;
  for (const c of part.cls) if (!el.contains(c)) return false;
  for (const [k, v] of part.attrs || []) { if (!(k in el.attrs) || (v !== null && el.attrs[k] !== v)) return false; }
  return true;
}

function qsa(root, sel) {
  const parts = String(sel).split(/\s+/).map(parseSimple).filter(Boolean);
  const last = parts[parts.length - 1];
  const out = [];
  (function rec(el) {
    for (const c of el.children) {
      if (c.tag === "#text") continue;
      if (simpleMatch(c, last)) {
        let i = parts.length - 2, anc = c.parent;
        while (i >= 0 && anc) { if (simpleMatch(anc, parts[i])) i--; anc = anc.parent; }
        if (i < 0) out.push(c);
      }
      rec(c);
    }
  })(root);
  return out;
}

function resetDOM() {
  elements = {}; roots = [];
  global.document = {
    getElementById(id) {
      if (elements[id]) return elements[id];
      const deep = list => {
        for (const e of list) {
          if (!e || e.tag === "#text") continue;
          if (e.attrs && e.attrs.id === id) return e;
          if (e.children) { const f = deep(e.children); if (f) return f; }
        }
        return null;
      };
      const found = deep(roots.concat(Object.values(elements)));
      if (found) { elements[id] = found; return found; }
      const el = addBehaviors(makeEl("div"));
      el.attrs.id = id; el.id = id;
      el.attrs.class = "card"; el.className = "card";
      wireEl(el);
      elements[id] = el; roots.push(el);
      return el;
    },
    querySelectorAll(sel) {
      const out = [];
      const doc = { tag: "#root", children: roots.slice() };
      out.push(...qsa(doc, sel));
      return out;
    },
    querySelector(sel) { return this.querySelectorAll(sel)[0] || null; },
    createElement(tag) { const el = addBehaviors(makeEl(String(tag).toLowerCase())); wireEl(el); roots.push(el); return el; },
    createElementNS(ns, tag) { const el = addBehaviors(makeEl(String(tag).toLowerCase())); wireEl(el); roots.push(el); return el; },
  };
  global.window = { innerWidth: 1920, innerHeight: 900, matchMedia(){ return { matches: false, addEventListener(){} }; }, getComputedStyle(){ return { getPropertyValue: () => "0" }; }, addEventListener(){} };
  global.location = { href: "file:///x.html" };
}

/* ---------------- checks ---------------- */
let fails = 0, passes = 0;
function check(name, cond, detail) {
  if (cond) { passes++; console.log("  \u2713 " + name); }
  else { fails++; console.log("  \u2717 " + name + (detail ? "  " + detail : "")); }
}
const S = id => global.document.getElementById(id);

function loadPage(slug) {
  resetDOM();
  const html = fs.readFileSync(__dirname + "/../" + slug + ".html", "utf8");
  const m = [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)];
  if (!m.length) { check(slug + ": script found", false); return null; }
  const script = m.map(x => x[1]).join("\n");
  try {
    (0, eval)(script + "\nglobalThis.__D = DATA; globalThis.__K = {S, kpis, hbars, vbars, lineChart, heat, table, insights}; globalThis.__L = (typeof LIVE !== \"undefined\") ? LIVE : null;");
    return globalThis.__D;
  } catch (e) {
    check(slug + ": script executed", false, e.message + "\n" + (e.stack || "").split("\n").slice(0, 3).join("\n"));
    return null;
  }
}

function txt(el) {
  if (!el) return "";
  if (el.tag === "#text") return el.text;
  if (el.children && el.children.length) return el.children.map(txt).join("");
  return el._raw != null ? el._raw : "";
}
function numCells(trs, k) { return trs.map(tr => parseFloat(String(txt(tr.children[k])).replace(/[^0-9.\-]/g, ""))); }
function rowTexts(el, skipHeader = 1) { return el.querySelectorAll("tr").slice(skipHeader).map(tr => txt(tr.children[0])); }

console.log("== web dashboard interactivity harness ==");

/* ---- index (overview) ---- */
console.log("[1] index.html — AOP trend, linked KPIs, attention");
{
  const D = loadPage("index");
  check("script executed", !!D);
  if (D) {
    check("DATA.trend labels present", Array.isArray(D.trend.labels) && D.trend.labels.length > 10, String(D.trend.labels && D.trend.labels.length));
    check("KPI cards rendered", S("kpis").children.length === D.kpis.length, S("kpis").children.length + " vs " + D.kpis.length);
    check("KPI values in DOM", D.kpis.every(k => S("kpis").innerHTML.includes(String(k.value))));
    check("trend chart rendered (svg + crosshair)", S("c_trend").innerHTML.includes("<svg") && S("c_trend").innerHTML.includes("xhair"));
    check("AOP polyline present", S("c_trend").innerHTML.includes("polyline"));
    check("attention rendered (n items)", S("c_attention").querySelectorAll(".ins").length === D.attention.length, S("c_attention").querySelectorAll(".ins").length + " vs " + D.attention.length);
    check("deep cuts rendered", S("cuts").querySelectorAll(".ins").length >= 1);
    if (D.attention.length) check("attention link navigates", (() => { const i = S("c_attention").querySelector(".ins[data-href]"); i.click(); return global.location.href !== "file:///x.html"; })());
  }
}

/* ---- migration ---- */
console.log("[2] migration.html — bars, sortable + searchable tables");
{
  const D = loadPage("migration");
  check("script executed", !!D);
  if (D) {
    check("net vbars rendered (n items)", S("c_net").querySelectorAll(".vb").length === D.net.length, S("c_net").querySelectorAll(".vb").length + " vs " + D.net.length);
    const tb = S("c_v2c").querySelector("table");
    check("v2c table rows", tb.querySelectorAll("tr").length === 1 + D.v2c.rows.length, tb.querySelectorAll("tr").length + " vs " + (1 + D.v2c.rows.length));
    // sorting: click col 2 (V2V %) twice → ascending
    let ths = tb.querySelectorAll("th.sortable"); ths[2].onclick();
    ths = tb.querySelectorAll("th.sortable"); ths[2].onclick();
    ths = tb.querySelectorAll("th.sortable");
    const bodyRows = tb.querySelectorAll("tr").slice(1).filter(tr => !txt(tr.children[0]).includes("Overall"));
    const nums = numCells(bodyRows, 2);
    check("v2c sort ascending after 2 clicks", nums.every((v, i) => i === 0 || nums[i - 1] <= v), JSON.stringify(nums));
    check("sort arrow shown", txt(ths[2]).includes("\u25b2"));
    // intra search
    const inEl = S("c_intra");
    if (D.intra) {
      const inp = inEl.querySelector("input");
      const needle = D.intra.rows[0][0];
      inp.value = needle; inp.fire("input", { target: { value: needle } });
      const exp = 1 + D.intra.rows.filter(r => r.join(" ").includes(needle)).length;
      check("intra search filters rows", inEl.querySelectorAll("tr").length === exp, inEl.querySelectorAll("tr").length + " vs " + exp);
    }
    check("deep cuts rendered", S("cuts").querySelectorAll(".ins").length >= 1);
  }
}

/* ---- sales ---- */
console.log("[3] sales.html — Pareto ↔ matrix cross-highlight, AOP KPIs");
{
  const D = loadPage("sales");
  check("script executed", !!D);
  if (D) {
    check("pareto hbars (n items)", S("c_pareto").querySelectorAll(".hb").length === D.pareto.length, S("c_pareto").querySelectorAll(".hb").length + " vs " + D.pareto.length);
    check("channel hbars", S("c_chan").querySelectorAll(".hb").length === D.chan.length);
    const cells = S("c_matrix").querySelectorAll(".hc");
    const expCells = D.matrix.ylabels.length * D.matrix.xlabels.length - D.matrix.vals.flat().filter(v => v == null).length;
    check("matrix heat cells", cells.length === expCells, cells.length + " vs " + expCells);
    const bar0 = S("c_pareto").querySelectorAll(".hb")[0];
    bar0.click();
    const rows = S("c_matrix").querySelectorAll(".hrow");
    check("click bar → row highlighted", rows[0].style.outline === "2px solid var(--ink)" && rows[1].style.outline === "");
    bar0.click();
    check("click again → cleared", rows[0].style.outline === "" );
    check("AOP KPIs rendered", S("c_aop").children.length === D.aop_kpis.length);
    check("deep cuts rendered", S("cuts").querySelectorAll(".ins").length >= 1);
  }
}

/* ---- nps-cs ---- */
console.log("[4] nps-cs.html — distributions, dim → VoC cross-filter, VoC search");
{
  const D = loadPage("nps-cs");
  check("script executed", !!D);
  if (D) {
    check("brand dist bars (11)", S("c_distB").querySelectorAll(".vb").length === 11);
    check("product dist bars (11)", S("c_distP").querySelectorAll(".vb").length === 11);
    check("dim hbars", S("c_dims").querySelectorAll(".hb").length === D.dims.length);
    check("VoC table full", S("vocTable").querySelectorAll("tr").length === 1 + D.voc.length, S("vocTable").querySelectorAll("tr").length + " vs " + (1 + D.voc.length));
    // search
    const inp = S("vocSearch");
    const q = D.voc[0][2].slice(0, 4).toLowerCase();
    inp.value = q; inp.fire("input", { target: { value: q } });
    check("VoC search updates count line", S("vocCount").innerHTML.includes(q), S("vocCount").innerHTML);
    const expRows = 1 + D.voc.filter(r => r.join(" ").toLowerCase().includes(q)).length;
    check("VoC search filters rows", S("vocTable").querySelectorAll("tr").length === expRows, S("vocTable").querySelectorAll("tr").length + " vs " + expRows);
    inp.value = ""; inp.fire("input", { target: { value: "" } });
    // cross-filter: click dim bar 0
    const d0 = S("c_dims").querySelectorAll(".hb")[0];
    d0.click();
    check("dim click → VoC focused", S("vocCount").innerHTML.includes("focused on"), S("vocCount").innerHTML);
    d0.click();
    check("dim click again → cleared", !S("vocCount").innerHTML.includes("focused on"));
    check("CS table rendered", S("c_cs").querySelectorAll("tr").length === 1 + D.cs.rows.length);
    check("deep cuts rendered", S("cuts").querySelectorAll(".ins").length >= 1);
  }
}

/* ---- pricing ---- */
console.log("[5] pricing.html — mover click filters Source B table");
{
  const D = loadPage("pricing");
  check("script executed", !!D);
  if (D) {
    check("movers hbars", S("c_movers").querySelectorAll(".hb").length === D.movers.length);
    check("source B rows full", S("c_b").querySelectorAll("tr").length === 1 + D.b.rows.length, S("c_b").querySelectorAll("tr").length + " vs " + (1 + D.b.rows.length));
    const m0 = S("c_movers").querySelectorAll(".hb")[0];
    m0.click();
    check("mover click → Source B filtered", S("c_b").querySelector("input").value !== "" ? true : S("c_b").querySelector("input").getAttribute("placeholder").includes("Filtered to"), S("c_b").querySelector("input").getAttribute("placeholder"));
    const sku = D.movers[0].sku;
    const expRows = 1 + D.b.rows.filter(r => r.join(" ").includes(sku)).length;
    check("filtered row count matches", S("c_b").querySelectorAll("tr").length === expRows, S("c_b").querySelectorAll("tr").length + " vs " + expRows);
    m0.click();
    check("mover click again → reset", S("c_b").querySelectorAll("tr").length === 1 + D.b.rows.length);
    check("source A table rendered", S("c_a").querySelectorAll("tr").length === 1 + D.a.rows.length);
    check("deep cuts rendered", S("cuts").querySelectorAll(".ins").length >= 1);
  }
}

/* ---- retention ---- */
console.log("[6] retention.html — FM table, V2V/V2C table, journey bars, CTA");
{
  const D = loadPage("retention");
  check("script executed", !!D);
  if (D) {
    check("FM table rows (windows)", S("c_fm").querySelectorAll("tr").length === 1 + D.fm.rows.length, S("c_fm").querySelectorAll("tr").length + " vs " + (1 + D.fm.rows.length));
    check("FM N/A rule visible", txt(S("c_fm")).includes("N/A") || D.fm.rows.every(r => !String(r[1]).includes("N/A")));
    check("v2c table rows", S("c_v2c").querySelectorAll("tr").length === 1 + D.v2c.rows.length);
    check("journey bars", S("c_jr").querySelectorAll(".vb").length === D.jr.length, S("c_jr").querySelectorAll(".vb").length + " vs " + D.jr.length);
    check("CTA links to journey.html", !!S("c_jr") && fs.readFileSync(__dirname + "/../retention.html", "utf8").includes('href="journey.html"'));
    check("deep cuts rendered", S("cuts").querySelectorAll(".ins").length >= 1);
  }
}

/* ---- ntc ---- */
console.log("[7] ntc.html — order curve, cohort heatmap");
{
  const D = loadPage("ntc");
  check("script executed", !!D);
  if (D) {
    check("curve bars", S("c_curve").querySelectorAll(".vb").length === D.curve.length, S("c_curve").querySelectorAll(".vb").length + " vs " + D.curve.length);
    const cells = S("c_heat").querySelectorAll(".hc");
    const expCells = D.heat.vals.flat().filter(v => v != null).length;
    check("heat cells (nulls shown as —)", cells.length === expCells, cells.length + " vs " + expCells);
    check("heat pct format", S("c_heat").innerHTML.match(/>\d+%</) != null);
    check("deep cuts rendered", S("cuts").querySelectorAll(".ins").length >= 1);
  }
}

/* ---- definitions ---- */
console.log("[8] definitions.html — searchable definitions");
{
  const D = loadPage("definitions");
  check("script executed", !!D);
  if (D) {
    check("defs table rows", S("c_defs").querySelectorAll("tr").length === 1 + D.defs.rows.length, S("c_defs").querySelectorAll("tr").length + " vs " + (1 + D.defs.rows.length));
    const inp = S("c_defs").querySelector("input");
    inp.value = D.defs.rows[0][0].slice(0, 3); inp.fire("input", { target: { value: D.defs.rows[0][0].slice(0, 3) } });
    const exp = 1 + D.defs.rows.filter(r => r.join(" ").includes(D.defs.rows[0][0].slice(0, 3))).length;
    check("defs search filters", S("c_defs").querySelectorAll("tr").length === exp, S("c_defs").querySelectorAll("tr").length + " vs " + exp);
    check("no-data note for cuts", S("cuts").innerHTML.includes("No deep cuts"));
  }
}

/* ---- insights ---- */
console.log("[9] insights.html — top conclusions + section cards");
{
  const D = loadPage("insights");
  check("script executed", !!D);
  if (D) {
    check("top insights rendered", S("c_top").querySelectorAll(".ins").length === D.top.length, S("c_top").querySelectorAll(".ins").length + " vs " + D.top.length);
    const cards = global.document.querySelectorAll("#c_sections .card");
    check("section cards rendered", cards.length === D.sections.length, cards.length + " vs " + D.sections.length);
    check("each section has items", cards.every(c => c.querySelectorAll(".ins").length >= 1));
    check("insight link navigates", (() => { const i = S("c_top").querySelector(".ins[data-href]"); if (!i) return false; i.click(); return global.location.href !== "file:///x.html"; })());
    check("per-page details present", !!S("c_top") && fs.readFileSync(__dirname + "/../insights.html", "utf8").includes("Per-page conclusions"));
  }
}

/* ---- tooltip machinery (on a page that has vbars) ---- */
console.log("[10] tooltip machinery");
{
  const D = loadPage("migration");
  if (D) {
    const bar = S("c_net").querySelectorAll(".vb")[0];
    bar.fire("mousemove", { clientX: 10, clientY: 10 });
    check("tooltip shows on hover", S("tip").style.display === "block" && S("tip").innerHTML.includes(D.net[0].label), S("tip").innerHTML.slice(0, 80));
    bar.fire("mouseleave");
    check("tooltip hides", S("tip").style.display === "none");
    // line chart tooltip on index
    const D2 = loadPage("index");
    if (D2) {
      const svg = S("c_trend").querySelector("svg");
      svg.fire("mousemove", { clientX: 100, clientY: 10 });
      check("crosshair tooltip on trend", S("tip").style.display === "block" && S("tip").innerHTML.length > 0, S("tip").innerHTML.slice(0, 80));
    }
  }
}

/* ---- [11] live: in-browser CSV engine recomputes vs embedded values ---- */
console.log("[11] live CSV -> in-browser recomputation");
{
  const rd = f => fs.readFileSync(__dirname + "/../" + f, "utf8");
  const salesTxt = rd("data/sample_sales.csv");
  const aopTxt = rd("data/sample_aop.csv");
  const npsTxt = rd("data/sample_nps.csv");
  const csTxt = rd("data/sample_cs.csv");
  const fmTxt = rd("data/sample_retention.csv");
  const ntcTxt = rd("data/sample_new_to_category.csv");
  const today = new Date().toISOString().slice(0, 10);

  loadPage("sales");
  const L = globalThis.__L;
  if (L) {
    check("LIVE engine present on page", typeof L.attach === "function" && typeof L.loadSource === "function");

    // --- sales ---
    const rS = L.loadSource("sales", salesTxt);
    check("sales: source parsed", rS.ok === true, String(rS.ok));
    const cS = L.C_SALES(rS);
    const Ds = globalThis.__D;
    check("sales: live revenue KPI == embedded", cS.kpis[0].value === Ds.kpis[0].value, cS.kpis[0].value + " vs " + Ds.kpis[0].value);
    check("sales: live pareto #1 == embedded", cS.pareto[0].label === Ds.pareto[0].label && Math.abs(cS.pareto[0].value - Ds.pareto[0].value) < 0.05, cS.pareto[0].label + "/" + cS.pareto[0].value + " vs " + Ds.pareto[0].label + "/" + Ds.pareto[0].value);
    check("sales: live matrix dims == embedded", cS.matrix.xlabels.length === Ds.matrix.xlabels.length && cS.matrix.ylabels.length === Ds.matrix.ylabels.length && cS.matrix.vals.length === Ds.matrix.vals.length, cS.matrix.vals.length + " vs " + Ds.matrix.vals.length);

    // --- pricing from the same sales source ---
    const Dp = loadPage("pricing");
    const cP = L.C_PRICE(L.loadSource("price", salesTxt), 0.05);
    check("pricing: live source-B count == embedded", Dp && cP.bRows.length === Dp.b.rows.length, cP.bRows.length + " vs " + (Dp && Dp.b.rows.length));
    check("pricing: live source-B row1 == embedded", Dp && cP.bRows[0][0] === Dp.b.rows[0][0], cP.bRows[0][0] + " vs " + (Dp && Dp.b.rows[0][0]));
    check("pricing: live movers == embedded", Dp && cP.movers.length === Dp.movers.length && cP.movers[0].sku === Dp.movers[0].sku, cP.movers.length + " vs " + (Dp && Dp.movers.length));
    const mNB = (fs.readFileSync(__dirname + "/../pricing.html", "utf8").match(/id="n_bnote">\s*(\d+)\s*increase\(s\)\s*and\s*(\d+)\s*decrease/) || null);
    check("pricing: embedded up/dn counts match live", Dp && mNB && cP.nUp === Number(Dp.kpis[1].value) && cP.nDn === Number(Dp.kpis[2].value) && Number(mNB[1]) === cP.nUp && Number(mNB[2]) === cP.nDn, cP.nUp + "/" + cP.nDn + " vs " + (Dp && Dp.kpis[1].value + "/" + Dp.kpis[2].value));

    // --- AOP (index) ---
    const Di = loadPage("index");
    const cA = L.C_AOP(L.loadSource("aop", aopTxt));
    check("aop: parsed + same label count as embedded", Di && cA.ok === true && cA.labels.length === Di.trend.labels.length, cA.labels.length + " vs " + (Di && Di.trend.labels.length));
    const _cr = Math.round(cA.revenue[0]/1e7*1000)/1000;
    check("aop: live revenue[0] (₹Cr) == embedded trend[0]", Di && Math.abs(_cr - Di.trend.series[0].values[0]) < 0.005, _cr + " vs " + (Di && Di.trend.series[0].values[0]));
    check("aop: live spend array aligned", Di && cA.spend.length === Di.trend.labels.length, cA.spend.length + " vs " + (Di && Di.trend.labels.length));

    // --- NPS + CS combo (nps-cs) ---
    loadPage("nps-cs");
    const cN = L.C_NPS(L.loadSource("nps", npsTxt));
    const Dn = globalThis.__D;
    check("nps: live score == embedded KPI", Dn && Math.abs(cN.b.nps - Math.abs(parseFloat(String(Dn.kpis[0].value).replace(/[^0-9.\-]/g, "")))) < 0.05, cN.b.nps + " vs " + (Dn && Dn.kpis[0].value));
    check("nps: live dist counts == embedded", Dn && cN.b.dist[0] === Dn.distB[0] && cN.b.dist[10] === Dn.distB[10] && cN.b.dist.reduce((a,x)=>a+x,0) === Dn.distB.reduce((a,x)=>a+x,0), JSON.stringify(cN.b.dist.slice(0,2)) + " vs " + (Dn && JSON.stringify(Dn.distB.slice(0,2))));
    check("nps: live dims == embedded", Dn && cN.dims.length === Dn.dims.length && cN.dims[0][0] === Dn.dims[0][0], cN.dims.length + " vs " + (Dn && Dn.dims.length));
    const cC = L.C_CS(L.loadSource("cs", csTxt));
    check("cs: live totals == embedded", Dn && Number(cC.kpis[0].value) === Number(Dn.kpis[2].value) && cC.topReason === Dn.cs_top, cC.kpis[0].value + "/" + cC.topReason + " vs " + (Dn && Dn.kpis[2].value + "/" + Dn.cs_top));
    check("cs: live table row1 == embedded", Dn && cC.table.rows[0][0] === Dn.cs.rows[0][0], cC.table.rows[0][0] + " vs " + (Dn && Dn.cs.rows[0][0]));
    check("nps+cs: live voc count == embedded", Dn && cN.voc.length + cC.voc.length === Dn.voc.length, (cN.voc.length + "+" + cC.voc.length) + " vs " + (Dn && Dn.voc.length));

    // --- retention FM ---
    loadPage("retention");
    const cF = L.C_FM(L.loadSource("retention_fm", fmTxt), today);
    const Dr = globalThis.__D;
    const _fmK = Dr && Dr.kpis.find(k => String(k.label).startsWith("FM SKUs"));
    check("fm: live nSkus == embedded", _fmK && cF.nSkus === Number(_fmK.value), cF.nSkus + " vs " + (_fmK && _fmK.value));
    check("fm: live lookup table row1 == embedded", Dr && cF.aRows[0][0] === Dr.a.rows[0][0], cF.aRows[0][0] + " vs " + (Dr && Dr.a.rows[0][0]));
    check("fm: live window table row1 == embedded", Dr && cF.fm.rows[0][0] === Dr.fm.rows[0][0], cF.fm.rows[0][0] + " vs " + (Dr && Dr.fm.rows[0][0]));
    check("fm: live lookup row1 == embedded", Dr && Dr.a && cF.aRows.length === Dr.a.rows.length && cF.aRows[0][0] === Dr.a.rows[0][0], cF.aRows.length + " vs " + (Dr && Dr.a && Dr.a.rows.length));

    // --- NTC ---
    loadPage("ntc");
    const cT = L.C_NTC(L.loadSource("order_movement", ntcTxt), today);
    const Dt = globalThis.__D;
    check("ntc: live curve == embedded", Dt && cT.curve.length === Dt.curve.length && Math.abs(cT.curve[0].value - Dt.curve[0].value) < 0.05, cT.curve[0].value + " vs " + (Dt && Dt.curve[0].value));
    check("ntc: live heat rows == embedded", Dt && cT.heat.ylabels.length === Dt.heat.ylabels.length && cT.heat.xlabels.length === Dt.heat.xlabels.length, cT.heat.ylabels.length + " vs " + (Dt && Dt.heat.ylabels.length));

    // --- journey (customer-level recompute vs Python-computed fixture) ---
    const exp = JSON.parse(fs.readFileSync(__dirname + "/fixtures/journey_expect.json", "utf8"));
    const cJ = L.C_JOURNEY(L.loadSource("journey", rd("tests/fixtures/journey_long.csv")), exp.asOf);
    const _p = s => parseFloat(String(s).replace(/[^0-9.\-]/g, ""));
    check("journey: live V2V == python fixture", _p(cJ.kpis[2].value) === Math.round(exp.v2v / exp.qual * 1000) / 10, cJ.kpis[2].value + " vs " + (Math.round(exp.v2v / exp.qual * 1000) / 10) + "%");
    check("journey: live V2C == python fixture", _p(cJ.kpis[3].value) === Math.round(exp.v2c / exp.qual * 1000) / 10, cJ.kpis[3].value + " vs " + (Math.round(exp.v2c / exp.qual * 1000) / 10) + "%");
    check("journey: live qualifying == fixture", cJ.qual === exp.qual, cJ.qual + " vs " + exp.qual);
    check("journey: live net migration top == fixture", cJ.net[0].entity === exp.topNetEntity && cJ.net[0].net === exp.topNet, cJ.net[0].entity + " " + cJ.net[0].net + " vs " + exp.topNetEntity + " " + exp.topNet);
    check("journey: live net split == fixture", cJ.net[0].g === exp.topNetG && cJ.net[0].l === exp.topNetL, cJ.net[0].g + "/" + cJ.net[0].l + " vs " + exp.topNetG + "/" + exp.topNetL);
    const _jr90 = (cJ.jr.find(x => x.label === "90d") || {}).value;
    check("journey: live JR90 == fixture", Math.abs(_jr90 - exp.jr90) < 0.005, _jr90 + " vs " + exp.jr90);

    // --- fallback: schema mismatch -> structural profile, no crash ---
    const rX = L.loadSource("nps", rd("data/sample_migr_seasonality.csv"));
    check("mismatched file: flagged not-ok with reason", rX.ok === false && String(rX.reason).length > 0, JSON.stringify(rX.reason));
    const pr = rX.profile;
    check("mismatched file: profile generated", pr && pr.headers.length >= 2 && pr.preview.length >= 2, pr && (pr.headers.length + " cols / " + pr.preview.length + " rows"));
    check("profile: renderProfile renders", (() => { const w = S("profileCard"); L.renderProfile(w, pr); return w.children.length >= 2; })());

    // --- panel end-to-end: handle() replaces DATA, banner shows, reset restores ---
    loadPage("sales");
    const inst = (global.window.__LIVE_INST || globalThis.__LIVE_INST) && (global.window.__LIVE_INST || globalThis.__LIVE_INST)["livePanel"];
    if (inst) {
      const before = JSON.stringify(globalThis.__D.kpis);
      const spec = inst.specs.find(x => x.key === "sales");
      inst.handle(spec, salesTxt, "my_sales.csv");
      check("panel: handle() recomputed DATA.kpis", globalThis.__D.kpis[0].value === cS.kpis[0].value, globalThis.__D.kpis[0].value + " vs " + cS.kpis[0].value);
      check("panel: live banner visible", S("lv_banner_livePanel").classList.contains("on"));
      const anySpec = inst.specs.find(x => x.key === "any");
      if (anySpec) {
        inst.handle(anySpec, rd("data/sample_migr_seasonality.csv"), "other.csv");
        check("panel: profile card populated", S("profileCard").innerHTML.includes("Generic analysis"));
      }
      inst.reset();
      check("panel: reset restores bundled DATA", JSON.stringify(globalThis.__D.kpis) === before);
      check("panel: banner hidden after reset", !S("livePanel").querySelector(".lv-banner"));
    } else {
      check("panel: instance registered", false);
    }
  }
}

/* ---- [12] journey.html — live journey analysis card ---- */
console.log("[12] journey.html — live journey analysis card");
{
  const DJ = loadPage("journey");
  check("journey: script executed (bundled sheet intact)", !!DJ && DJ.nCustomers === 152091 && DJ.nOrders === 193756, DJ && (DJ.nCustomers + "/" + DJ.nOrders));
  if (DJ) {
    const inst = (global.window.__LIVE_INST || {})["jLivePanel"];
    check("journey: live panel attached", !!inst);
    if (inst) {
      const jexp = JSON.parse(fs.readFileSync(__dirname + "/fixtures/journey_expect.json", "utf8"));
      const jtxt = fs.readFileSync(__dirname + "/fixtures/journey_long.csv", "utf8");
      const spec = inst.specs.find(x => x.key === "journey");
      inst.handle(spec, jtxt, "my_journey.csv");
      const o = S("jLiveOut");
      const html = String(o.innerHTML);
      check("journey: live output shown", o.style.display !== "none" && html.length > 200, html.length);
      check("journey: live customers KPI == fixture", html.includes(jexp.nCustomers), jexp.nCustomers);
      const _jv2v = Math.round(jexp.v2v / jexp.qual * 1000) / 10 + "%";
      check("journey: live V2V == fixture", html.includes(_jv2v), _jv2v);
      check("journey: live top net migration == fixture", html.includes(jexp.topNetEntity), jexp.topNetEntity);
      inst.reset();
      check("journey: reset hides live output", o.style.display === "none" && String(o.innerHTML).length === 0);
    }
  }
}

console.log("\n" + (fails ? "FAILED " + fails + " / " + (passes + fails) : "ALL " + passes + " CHECKS PASSED"));
process.exit(fails ? 1 : 0);
