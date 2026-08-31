/* headless test harness for retention.html (DOM stub + node) */
const fs = require("fs");
const html = fs.readFileSync(__dirname + "/../journey.html", "utf8");
const scripts = [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)].map(m => m[1]);

function makeEl(id) {
  return {
    id, innerHTML: "", textContent: "", value: "", title: "", style: {}, dataset: {}, disabled: false,
    children: [],
    appendChild(c) { this.children.push(c); return c; },
    querySelectorAll() { return []; },
    querySelector() { return null; },
    addEventListener() {},
    closest() { return this; },
    after() {},
    remove() {},
    click() {},
    getBoundingClientRect() { return { left: 0, width: 900 }; },
  };
}
const elements = {};
global.document = {
  getElementById(id) { if (!elements[id]) elements[id] = makeEl(id); return elements[id]; },
  querySelectorAll() { return { forEach() {} }; },
  querySelector() { return null; },
  createElement(tag) { return makeEl(tag); },
};
global.window = {};
global.Blob = class { constructor(parts) { this.text = parts.join(""); } };
global.URL = { createObjectURL: () => "blob:x", revokeObjectURL: () => {} };

let fails = 0;
function check(name, cond, detail) {
  if (cond) console.log("  ✓ " + name);
  else { fails++; console.log("  ✗ " + name + (detail ? "  " + detail : "")); }
}

try {
  (0, eval)(scripts[0] + "\n" + scripts[1] +
    "\nglobalThis.__DATA = DATA; globalThis.__T = {S, apply, filtered, computeCohort, matches};");
} catch (e) {
  console.log("✗ script execution threw:", e.stack);
  process.exit(1);
}
const D = globalThis.__DATA, T = globalThis.__T;
console.log("[A] data + full-cohort render");
check("DATA customers = 152,091", D.nCustomers === 152091, String(D.nCustomers));
check("DATA orders = 193,756", D.nOrders === 193756, String(D.nOrders));
check("custItems rows = customers", D.custItems.length === D.nCustomers);
check("custEntry rows = customers", D.custEntry.length === D.nCustomers);
check("varFirstProd covers all variants", Object.keys(D.varFirstProd).length >= 10);

const kpis = elements["kpis"].innerHTML;
check("KPI customers 152,091", kpis.includes("152,091"));
check("KPI orders 193,756", kpis.includes("193,756"));
check("KPI repeat buyers 24,771", kpis.includes("24,771"));
check("KPI V2V 31.8%", kpis.includes("V2V 31.8%"), kpis.slice(0, 400));
check("KPI V2C 69.1%", kpis.includes("V2C 69.1%"));
const showing = elements["showing"].innerHTML;
check("showing line full cohort", showing.includes("152,091"));
check("insights rendered (>=4 cards)", (elements["insights"].innerHTML.match(/apply ↗/g) || []).length >= 4,
      String((elements["insights"].innerHTML.match(/apply ↗/g) || []).length));
const nCols = id => elements[id].children.filter(c => String(c.className).includes("bcol")).length;
check("retention curve rendered (7 windows)", elements["retCurve"].children.length === 7,
      String(elements["retCurve"].children.length));
check("repeat-by-month rendered (31 bars)", nCols("repeatByMonth") === 31, String(nCols("repeatByMonth")));
check("gap distribution rendered (9 buckets)", elements["gapDist"].children.length === 9,
      String(elements["gapDist"].children.length));
check("loyalty grid rendered (6 cells)", (elements["loyGrid"].innerHTML.match(/class="kpi"/g) || []).length === 6,
      String((elements["loyGrid"].innerHTML.match(/class="kpi"/g) || []).length));
check("orders by month rendered (31 bars)", nCols("ordersByMonth") === 31, String(nCols("ordersByMonth")));
check("category donut rendered", elements["catDonut"].innerHTML.includes("circle"));
check("season tiles rendered (4)", (elements["seasonTiles"].innerHTML.match(/class="tile/g) || []).length === 4);
check("season bars rendered (4)", elements["seasonBars"].children.length === 4);
check("top variants rendered (10)", elements["topVars"].children.length === 10,
      String(elements["topVars"].children.length));
check("depth bars rendered (6)", elements["depthBars"].children.length === 6);
check("region bars rendered (5)", elements["regionBars"].children.length === 5);
check("city chips rendered", elements["cityChips"].innerHTML.includes("Bengaluru"));
check("heat cal rendered", elements["heatCal"].innerHTML.includes("All India"));
check("heat line rendered", elements["heatLine"].innerHTML.includes("Concern"));
check("affinity rendered (1+5+5 bars)", elements["affinity"].children.length === 11,
      String(elements["affinity"].children.length));
check("region loyalty rendered", elements["regionLoy"].innerHTML.includes("Rest of India"));
check("transitions rendered", elements["transitions"].innerHTML.includes("→"));
check("flow tiles rendered (4)", (elements["flowTiles"].innerHTML.match(/class="tile"/g) || []).length === 4);
check("variant table rendered", elements["varTable"].innerHTML.includes("On-season lift"));
check("explorer rendered rows", (elements["explorer"].innerHTML.match(/class="xrow"/g) || []).length === 50);

console.log("[B] python-side cross-check of loyalty math (same data, independent impl)");
// recompute V2V/V2C in node from raw arrays (mirrors etl: 2nd order primary = first item)
{
  let rep = 0, v2v = 0, v2c = 0, gaps = [];
  for (let c = 0; c < D.nCustomers; c++) {
    const it = D.custItems[c], cc = D.custItemCat[c];
    if (it.length >= 2) {
      rep++;
      if (it[0][0] > 0 && it[1][0] > 0 && D.prods[it[0][0]].raw === D.prods[it[1][0]].raw) v2v++;
      if (cc[0][0] >= 0 && cc[1][0] >= 0 && cc[0][0] === cc[1][0]) v2c++;
    }
    D.custGaps[c].forEach(g => { if (g > 0) gaps.push(g); });
  }
  const s = [...gaps].sort((a, b) => a - b);
  const med = s[s.length >> 1];
  console.log(`    rep=${rep} v2v=${(100 * v2v / rep).toFixed(2)}% v2c=${(100 * v2c / rep).toFixed(2)}% medGap=${med}d`);
  check("V2V = 31.8% (model: 31.79%)", Math.abs(100 * v2v / rep - 31.79) < 0.1);
  check("V2C = 69.1% (model: 69.11%)", Math.abs(100 * v2c / rep - 69.11) < 0.1);
  check("median gap ~ 91-123d sanity", med > 60 && med < 140, String(med));
}

console.log("[C] filtering behaviour");
{
  // filter to one region
  T.S.region = 0; // North (New Delhi metro)
  T.apply();
  const nN = elements["showing"].innerHTML;
  const firstN = (nN.match(/Showing <b>([\d,]+)<\/b> of/) || [])[1];
  check("region filter changes cohort", !!firstN && firstN !== "152,091", nN.slice(0, 140));
  const F0 = T.filtered();
  check("region 0 subset sane (10k-60k)", F0.length > 10000 && F0.length < 60000, String(F0.length));
  check("explorer re-rendered for filter", (elements["explorer"].innerHTML.match(/class="xrow"/g) || []).length === 50);
  // reset
  Object.assign(T.S, { cat: -1, var: -1, size: -1, from: -1, to: -1, depth: -1, region: -1, repeat: -1, city: -1, cityQ: "" });
  T.apply();
  check("reset restores full cohort", elements["showing"].innerHTML.includes("152,091"));
  // repeaters only
  T.S.repeat = 1; T.apply();
  check("repeaters filter = 24,771", elements["kpis"].innerHTML.includes("24,771"));
  T.S.repeat = -1; T.apply();
  // entry month filter (first month)
  T.S.from = 0; T.S.to = 0; T.apply();
  const jan = T.filtered();
  check("entry-month filter non-empty", jan.length > 1000, String(jan.length));
  T.S.from = -1; T.S.to = -1; T.apply();
  // city search
  T.S.cityQ = "bengaluru"; T.apply();
  const ben = T.filtered();
  check("city search finds Bengaluru cohort", ben.length > 10000, String(ben.length));
  T.S.cityQ = ""; T.apply();
  // depth filter
  T.S.depth = 2; T.apply();
  const d2 = T.filtered();
  check("depth-2 filter matches", d2.every(c => D.custDepth[c] === 2) && d2.length > 10000, String(d2.length));
  T.S.depth = -1; T.apply();
  // maturity: most recent entry months flagged N/A in repeat-by-month
  const hasNa = elements["repeatByMonth"].children.some(c => String(c.className).includes("na"));
  check("immature cohorts hatched (N/A rule)", hasNa, hasNa ? "hatched" : "no immature marker");
}

console.log(fails ? "HARNESS FAIL (" + fails + ")" : "HARNESS PASS");
process.exit(fails ? 1 : 0);
