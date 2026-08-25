import ast  # noqa

s = open('index.html').read()

# ================= 1) two new tabs in the tab bar =================
old = """  <button onclick="goTab('sales',this)">💰 Sales &amp; Revenue</button>
  <button onclick="goTab('nps',this)">🗣️ NPS &amp; CS</button>
  <button onclick="goTab('movement',this)">🆕 New-to-Category</button>"""
new = """  <button onclick="goTab('sales',this)">💰 Sales &amp; AOP</button>
  <button onclick="goTab('nps',this)">🗣️ NPS &amp; CS</button>
  <button onclick="goTab('price',this)">💲 Price Changes</button>
  <button onclick="goTab('v2v',this)">📈 V2V / V2C %</button>
  <button onclick="goTab('movement',this)">🆕 New-to-Category</button>"""
assert old in s
s = s.replace(old, new)

# ================= 2) new panes before the movement pane =================
old = '<div id="tab-movement" class="tabpane"><div class="pane-in">'
new = """<div id="tab-price" class="tabpane"><div class="pane-in">
  <h2 class="sec">PRICE CHANGES</h2>
  <div class="hint">Price revisions from the retention sheet, plus unit-price moves (₹ per piece) detected automatically from the sales data.</div>
  <div style="display:flex;gap:14px;flex-wrap:wrap">
    <div style="flex:1;min-width:340px"><h3 style="font-size:13px;color:var(--dark)">Price revision notes</h3><div id="p_notes">Loading bundled sample…</div></div>
    <div style="flex:1;min-width:340px"><h3 style="font-size:13px;color:var(--dark)">Auto-detected unit-price moves (&gt;5% MoM)</h3><div id="p_moves">Loading…</div></div>
  </div>
</div></div>

<div id="tab-v2v" class="tabpane"><div class="pane-in">
  <h2 class="sec">RETENTION — V2V &amp; V2C %</h2>
  <div class="hint">Metabase format: customers acquired, how many reorder (2nd/3rd order %), same-variant repeat (V2V %) and average days to reorder. Level:
    <select id="v_level" onchange="renderV2v()"><option>Variant</option><option>Category</option></select></div>
  <div id="v_table"></div>
  <div id="v_chart" class="chart"></div>
</div></div>

<div id="tab-movement" class="tabpane"><div class="pane-in">"""
assert old in s
s = s.replace(old, new, 1)

# AOP container inside the sales pane
old = '<div id="s_variants"></div></div>\n  </div>\n</div></div>\n\n<div id="tab-nps"'
if old not in s:
    old = '<div id="s_variants"></div>'
assert old in s
s = s.replace(old, old + '</div>\n  <h3 style="font-size:13px;color:var(--dark);margin-top:14px">AOP — revenue vs spend (plan file, bundled sample)</h3><div id="s_aop" class="chart"></div>', 1)

# ================= 3) embed retention + AOP samples =================
csv_ret = open('data/retention_fm_feb26.csv').read()
csv_aop = open('data/aop_data.csv').read()
anchor = '<script type="text/csv" id="sampleMv">'
assert anchor in s
s = s.replace(anchor,
              '<script type="text/csv" id="sampleRet">\n' + csv_ret + '</script>\n\n'
              '<script type="text/csv" id="sampleAop">\n' + csv_aop + '</script>\n\n'
              + anchor, 1)

# ================= 4) pagescore: new compute functions =================
core_anchor = 'if(typeof module!=="undefined") module.exports='
assert core_anchor in s
funcs = r'''
/* ---------- retention price notes ---------- */
function priceNotes(rows){
  let start=-1;
  for(let c=12;c<(rows[0]||[]).length;c++){
    const v=rows[1]&&rows[1][c];
    if(v && /^[A-Z]{2,4}-/.test(String(v).trim())){ start=c; break; }
  }
  if(start<0) return null;
  const out=[];
  for(let r=1;r<rows.length;r++){
    const sku=rows[r][start];
    if(!sku||!/^[A-Z]{2,4}-/.test(String(sku).trim())) continue;
    const note=String(rows[r][start+2]||"");
    const n=note.toLowerCase();
    const kind=n.includes("increas")?"Increased":n.includes("decreas")?"Decreased":
      n.includes("same")?"Same":n.includes("launch")?"Launch":"Other";
    const row={sku:String(sku).trim(),product:String(rows[r][start+1]||""),
      note:note.split("\n")[0],kind};
    if(!out.some(x=>x.sku===row.sku)) out.push(row);
  }
  return out;
}
/* ---------- unit price moves from sales ---------- */
function unitPriceMoves(sales){
  const bySku={};
  for(const s of sales){ const k=s.product||s.sku;
    const g=bySku[k]=bySku[k]||{}; g[s.month]=g[s.month]||{rev:0,qty:0};
    g[s.month].rev+=s.rev; g[s.month].qty+=s.qty; }
  const out=[];
  for(const k in bySku){ const ms=Object.keys(bySku[k]).sort();
    for(let i=1;i<ms.length;i++){
      const a=bySku[k][ms[i-1]], b=bySku[k][ms[i]];
      if(!a.qty||!b.qty) continue;
      const pa=a.rev/a.qty, pb=b.rev/b.qty, d=100*(pb/pa-1);
      if(Math.abs(d)>5) out.push({sku:k,from:ms[i-1],to:ms[i],fromP:pa,toP:pb,d});
    } }
  return out.sort((x,y)=>y.d-x.d);
}
/* ---------- metabase V2V/V2C table ---------- */
function metabaseRows(level){
  const key=level==="Category"?"cat":"var";
  const rows={};
  for(const c of MODEL.customers){
    const e=c.orders[0].items[0]; if(!e) continue;
    const r=rows[e[key]]=rows[e[key]]||{acq:0,d2:0,d3:0,rep:0,v2v:0,gap:[]};
    r.acq++; if(c.depth>=2)r.d2++; if(c.depth>=3)r.d3++;
    if(c.orders.length>=2){ r.rep++;
      const n=c.orders[1].items[0];
      if(n&&n[key]===e[key])r.v2v++;
      r.gap.push(Math.round((c.orders[1].date-c.orders[0].date)/86400000)); } }
  return Object.entries(rows).map(([k,r])=>({key:k,acq:r.acq,
    p2:100*r.d2/r.acq,p3:100*r.d3/r.acq,
    v2v:r.rep?100*r.v2v/r.rep:null,
    avg:r.gap.length?Math.round(r.gap.reduce((a,b)=>a+b,0)/r.gap.length):null,
    rep:r.rep})).sort((a,b)=>b.acq-a.acq);
}
/* ---------- AOP ---------- */
function monthLab(v){
  if(v==null) return null; const sv=String(v).trim(); if(!sv) return null;
  if(/^\d{4}-\d{2}$/.test(sv)) return sv;
  const M={jan:1,feb:2,mar:3,apr:4,may:5,jun:6,jul:7,aug:8,sep:9,oct:10,nov:11,dec:12};
  let m=/^([A-Za-z]{3,9})['\s\-/]*(\d{2,4})$/.exec(sv);
  if(m){ const mo=M[m[1].slice(0,3).toLowerCase()];
    if(mo){ let y=+m[2]; y=y<100?2000+y:y; return y+"-"+String(mo).padStart(2,"0"); } }
  m=/^(\d{4})['\s\-/]*([A-Za-z]{3,9})$/.exec(sv);
  if(m){ const mo=M[m[2].slice(0,3).toLowerCase()];
    if(mo) return m[1]+"-"+String(mo).padStart(2,"0"); }
  return null;
}
function parseAop(rows){
  let hdr=0,best=-1;
  for(let i=0;i<Math.min(8,rows.length);i++){
    const n=(rows[i]||[]).filter(v=>monthLab(v)).length;
    if(n>best){best=n;hdr=i;} }
  if(best<6) return null;
  const H=(rows[hdr]||[]).map(v=>monthLab(v));
  const firstM=H.findIndex(v=>v);
  const metaN=firstM;
  const labRow=hdr>0?(rows[hdr-1]||[]):[];
  const runs=[]; let curLab=null,cur=[];
  for(let i=firstM;i<H.length;i++){
    let lab=labRow[i]!=null&&String(labRow[i]).trim()!==""?String(labRow[i]).trim():curLab;
    if(lab!==curLab){ if(cur.length>=3)runs.push([curLab,cur]); curLab=lab; cur=[]; }
    if(H[i])cur.push([i,H[i]]); }
  if(cur.length>=3)runs.push([curLab,cur]);
  const blk={};
  for(const [lab,cols] of runs){
    if(lab&&/revenue/i.test(lab)&&!/share|growth/i.test(lab)&&!blk.rev)blk.rev=cols;
    if(lab&&/spend/i.test(lab)&&!/share|growth/i.test(lab)&&!blk.spend)blk.spend=cols; }
  if(!blk.rev||!blk.spend) return null;
  function melt(cols){ const out={};
    for(let r=hdr+1;r<rows.length;r++){
      const metas=rows[r].slice(0,metaN).map(x=>String(x==null?"":x).trim().toUpperCase());
      if(metas.includes("TOTAL")) continue;
      for(const [i,m] of cols){ const v=_num(rows[r][i]); if(v!=null)out[m]=(out[m]||0)+v; } }
    return out; }
  return {rev:melt(blk.rev), spend:melt(blk.spend)};
}
'''
s = s.replace(core_anchor, funcs + "\n" + core_anchor, 1)
s = s.replace('module.exports={parseSales,salesAgg,parseNps,npsScore,topCounts,parseCs,parseMove,migrationData,quarterlyBlocks,_num,_pdate};',
              'module.exports={parseSales,salesAgg,parseNps,npsScore,topCounts,parseCs,parseMove,migrationData,quarterlyBlocks,priceNotes,unitPriceMoves,metabaseRows,parseAop,_num,_pdate};')

open('index.html','w').write(s)
print("part 1 done:", len(s)//1024, "KB")
