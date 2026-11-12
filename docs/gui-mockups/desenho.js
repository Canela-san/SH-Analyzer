/* Desenho dos mockups: ícones (traço de 24 px, no estilo do Lucide) e gráficos sintéticos em SVG/canvas.
   Só para os mockups do plano da GUI: a GUI de verdade desenha com o PyQtGraph e a pirâmide mín/máx. */

"use strict";

// ------------------------------------------------------------------ ícones
const ICONES = {
  ponteiro: "M5 3l14 8-6 2-2 6z",
  zoom: "M11 4a7 7 0 1 0 0 14 7 7 0 0 0 0-14z M16 16l5 5 M11 8v6 M8 11h6",
  mao: "M8 13V5.5a1.5 1.5 0 0 1 3 0V12 M11 11V4.5a1.5 1.5 0 0 1 3 0V12 M14 11.5V6a1.5 1.5 0 0 1 3 0v8a6 6 0 0 1-6 6h-1a6 6 0 0 1-5-2.7L3.5 14a1.5 1.5 0 0 1 2.5-1.7L8 15",
  cursores: "M7 3v18 M17 3v18 M10 12h4 M10 12l1.6-1.6 M10 12l1.6 1.6 M14 12l-1.6-1.6 M14 12l-1.6 1.6",
  regua: "M3 17L17 3l4 4L7 21z M7 13l2 2 M10 10l2 2 M13 7l2 2",
  texto: "M4 7V5h16v2 M12 5v14 M9 19h6",
  camadas: "M12 3l9 5-9 5-9-5z M3 13l9 5 9-5",
  pasta: "M3 6.5A1.5 1.5 0 0 1 4.5 5H9l2 2h8.5A1.5 1.5 0 0 1 21 8.5v9a1.5 1.5 0 0 1-1.5 1.5h-15A1.5 1.5 0 0 1 3 17.5z",
  arquivo: "M14 3H6.5A1.5 1.5 0 0 0 5 4.5v15A1.5 1.5 0 0 0 6.5 21h11a1.5 1.5 0 0 0 1.5-1.5V8z M14 3v5h5",
  chip: "M7 7h10v10H7z M10 3v4 M14 3v4 M10 17v4 M14 17v4 M3 10h4 M3 14h4 M17 10h4 M17 14h4",
  terminal: "M4 17l6-5-6-5 M12 19h8",
  ajustes: "M4 6h9 M17 6h3 M4 12h3 M11 12h9 M4 18h11 M19 18h1 M15 4v4 M9 10v4 M17 16v4",
  busca: "M11 4a7 7 0 1 0 0 14 7 7 0 0 0 0-14z M16 16l5 5",
  mais: "M12 5v14 M5 12h14",
  x: "M6 6l12 12 M18 6L6 18",
  olho: "M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7S2 12 2 12z M12 9a3 3 0 1 0 0 6 3 3 0 0 0 0-6z",
  onda: "M2 12c2-6.5 4-6.5 6 0s4 6.5 6 0 4-6.5 6 0 2 4 2 4",
  espectro: "M4 20V11 M9 20V4 M14 20v-8 M19 20v-5",
  grade: "M4 4h7v7H4z M13 4h7v7h-7z M4 13h7v7H4z M13 13h7v7h-7z",
  baixar: "M12 4v11 M7 10l5 5 5-5 M5 20h14",
  enviar: "M12 20V9 M7 14l5-5 5 5 M5 4h14",
  play: "M7 4l13 8-13 8z",
  stop: "M6 6h12v12H6z",
  girar: "M20 12a8 8 0 1 1-2.3-5.7 M20 4v5h-5",
  ok: "M5 12.5l4.5 4.5L19 7",
  alerta: "M12 3.5l9.5 16.5h-19z M12 10v4.5 M12 17.5v.2",
  usb: "M12 3v13 M9.5 5.5L12 3l2.5 2.5 M12 12.5l-4-2V8 M12 14.5l4-2V10 M12 16.2a2.4 2.4 0 1 0 0 4.8 2.4 2.4 0 0 0 0-4.8z",
  rede: "M9 3h6v5H9z M12 8v4 M5 12h14 M5 12v4 M19 12v4 M12 12v4 M3 16h4v4H3z M10 16h4v4h-4z M17 16h4v4h-4z",
  relogio: "M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18z M12 7v5l3 2",
  disco: "M3 13l3-8h12l3 8v5.5a1.5 1.5 0 0 1-1.5 1.5h-15A1.5 1.5 0 0 1 3 18.5z M3 13h18 M17 16.5h.2",
  termometro: "M10 4a2 2 0 0 1 4 0v10.2a4 4 0 1 1-4 0z M12 9v8",
  chave: "M15 3.5a5 5 0 0 0-4.6 6.9L3.5 17.3V20.5h3.2l6.9-6.9A5 5 0 0 0 20.5 9l-3 1-2.5-2.5 1-3z",
  sol: "M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8z M12 2v2 M12 20v2 M4.9 4.9l1.4 1.4 M17.7 17.7l1.4 1.4 M2 12h2 M20 12h2 M4.9 19.1l1.4-1.4 M17.7 6.3l1.4-1.4",
  lua: "M20 14.5A8.5 8.5 0 1 1 9.5 4a6.5 6.5 0 0 0 10.5 10.5z",
  baixo: "M6 9l6 6 6-6",
  direita: "M9 6l6 6-6 6",
  filtro: "M3 5h18l-7 8v6l-4 2v-8z",
  desfazer: "M9 14L4 9l5-5 M4 9h10.5a5.5 5.5 0 0 1 0 11H11",
  refazer: "M15 14l5-5-5-5 M20 9H9.5a5.5 5.5 0 0 0 0 11H13",
  cadeado: "M6 11h12v9H6z M8.5 11V8a3.5 3.5 0 0 1 7 0v3",
  link: "M10 14a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1 1 M14 10a4 4 0 0 0-5.7 0l-3 3a4 4 0 0 0 5.7 5.7l1-1",
  sonda: "M4 20l5.5-5.5 M9.5 14.5l2 2 7.5-7.5-2-2-7.5 7.5z M15.5 5.5l3 3",
  pulso: "M3 12h4l3-8 4 16 3-8h4",
  expandir: "M4 9V4h5 M20 9V4h-5 M4 15v5h5 M20 15v5h-5",
  mira: "M12 4a8 8 0 1 0 0 16 8 8 0 0 0 0-16z M12 2v4 M12 18v4 M2 12h4 M18 12h4",
  livro: "M5 4.5h11a3 3 0 0 1 3 3V20H8a3 3 0 0 1-3-3z M5 17a3 3 0 0 1 3-3h11",
  raio: "M13 2L4 14h7l-1 8 9-12h-7z",
  imagem: "M4 5h16v14H4z M4 16l5-5 4 4 3-3 4 4 M15 9h.2",
  energia: "M12 3v8 M6.3 7a8 8 0 1 0 11.4 0",
  alca: "M9 6h.2 M9 12h.2 M9 18h.2 M15 6h.2 M15 12h.2 M15 18h.2",
  copiar: "M8 8h11v12H8z M5 16V4h11",
  mais_h: "M5 12h.2 M12 12h.2 M19 12h.2",
  ligar: "M7 12h10 M12 7v10",
  pino: "M9 3h6 M10 3v6l-3 4h10l-3-4V3 M12 13v8",
  escudo: "M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6z M9 12l2 2 4-4",
  pagina: "M6 3h9l4 4v14H6z M15 3v4h4",
  paleta: "M12 3a9 9 0 1 0 0 18c1.2 0 1.5-.8 1.5-1.5 0-1.2-1-1.5-1-2.5S13.3 15 14.5 15H17a4 4 0 0 0 4-4c0-4.4-4-8-9-8z M7.5 11h.2 M10 7h.2 M14.5 7h.2",
};

function desenharIcones(raiz = document) {
  raiz.querySelectorAll("i[data-i]").forEach((el) => {
    const d = ICONES[el.dataset.i];
    if (!d) return;
    const tam = el.dataset.t || 16;
    const grosso = el.dataset.i === "mais_h" ? 3 : 1.8;
    el.style.width = el.style.height = tam + "px";
    el.innerHTML = `<svg viewBox="0 0 24 24" width="${tam}" height="${tam}" fill="none" stroke="currentColor"
      stroke-width="${grosso}" stroke-linecap="round" stroke-linejoin="round"><path d="${d}"/></svg>`;
  });
}

// ------------------------------------------------------------------ sinais sintéticos (determinísticos)
function aleatorio(semente) {
  let s = semente >>> 0;
  return () => ((s = (Math.imul(s, 1664525) + 1013904223) >>> 0) / 4294967296);
}
const TAU = 2 * Math.PI;

// Tensão de fase: 127 V RMS, uma variação lenta e um afundamento aos 1263 s; supraharmônicos na metade negativa.
function amplitudeTensao(t) {
  let a = 179.6 * (1 + 0.012 * Math.sin(TAU * t / 700) + 0.006 * Math.sin(TAU * t / 97));
  if (t > 1262.9 && t < 1263.35) a *= 0.71;
  return a;
}
function tensao(t, r) {
  const fase = Math.sin(TAU * 60 * t);
  const sh = (fase < 0 ? 5.2 : 1.1) * Math.sin(TAU * 20000 * t) + 1.6 * Math.sin(TAU * 40040 * t);
  return amplitudeTensao(t) * fase + sh + (r ? (r() - 0.5) * 1.2 : 0);
}
// Corrente de uma carga eletrônica: degraus de carga e uma partida aos 1263 s.
function amplitudeCorrente(t) {
  let a = 14 + (t > 600 ? 6 : 0) + (t > 2400 ? -9 : 0) + 1.5 * Math.sin(TAU * t / 180);
  if (t > 1263.0 && t < 1266) a *= 1 + 1.6 * Math.exp(-(t - 1263) / 0.8);
  return a;
}
function corrente(t, r) {
  const a = amplitudeCorrente(t);
  const i = a * (Math.sin(TAU * 60 * t - 0.35) + 0.32 * Math.sin(3 * TAU * 60 * t + 0.4) + 0.12 * Math.sin(5 * TAU * 60 * t));
  return i + 0.9 * Math.sin(TAU * 20000 * t) + (r ? (r() - 0.5) * 0.25 : 0);
}

// ------------------------------------------------------------------ utilidades de eixo
function ticks(a, b, n = 6) {
  const passoBruto = (b - a) / n;
  const p10 = Math.pow(10, Math.floor(Math.log10(passoBruto)));
  const passo = [1, 2, 2.5, 5, 10].map((m) => m * p10).find((p) => p >= passoBruto) || p10 * 10;
  const out = [];
  for (let v = Math.ceil(a / passo) * passo; v <= b + passo * 1e-9; v += passo) out.push(+v.toFixed(10));
  return out;
}
const br = (v, casas = 0) => v.toLocaleString("pt-BR", { minimumFractionDigits: casas, maximumFractionDigits: casas });
const cssVar = (el, nome) => getComputedStyle(el).getPropertyValue(nome).trim();
const NS = "http://www.w3.org/2000/svg";
function svgEl(tag, attrs, pai) {
  const e = document.createElementNS(NS, tag);
  for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, v);
  if (pai) pai.appendChild(e);
  return e;
}

/* Gráfico no tempo, com faixas empilhadas (lanes) que dividem o eixo x.
   cfg = { x0, x1, fmtX(v), unX, faixas: [{peso, y0, y1, unY, tracos: [{f(t,r)|env(ta,tb), cor, modo, larg, sel}]}],
           cursores: [{t, cor}], regiao: [t0, t1], margem: {l, r, t, b}, semGradeX } */
function grafico(el, cfg) {
  const W = el.clientWidth, H = el.clientHeight;
  const m = Object.assign({ l: 62, r: 16, t: 12, b: 28 }, cfg.margem || {});
  const svg = svgEl("svg", { viewBox: `0 0 ${W} ${H}` }, el);
  const larg = W - m.l - m.r;
  const pesoTotal = cfg.faixas.reduce((s, f) => s + (f.peso || 1), 0);
  const vao = cfg.vao ?? 14;
  const altUtil = H - m.t - m.b - vao * (cfg.faixas.length - 1);
  const xPix = (t) => m.l + ((t - cfg.x0) / (cfg.x1 - cfg.x0)) * larg;
  const grade = cssVar(el, "--grade"), eixo = cssVar(el, "--eixo"), gradeForte = cssVar(el, "--grade-forte");
  const tx = cfg.ticksX || ticks(cfg.x0, cfg.x1, Math.max(3, Math.round(larg / 140)));
  let y = m.t;
  const caixas = [];
  cfg.faixas.forEach((fx, k) => {
    const h = (altUtil * (fx.peso || 1)) / pesoTotal;
    const yPix = (v) => y + (1 - (v - fx.y0) / (fx.y1 - fx.y0)) * h;
    caixas.push({ y, h, yPix });
    svgEl("rect", { x: m.l, y, width: larg, height: h, fill: "none", stroke: gradeForte }, svg);
    for (const v of fx.ticksY || ticks(fx.y0, fx.y1, Math.max(2, Math.round(h / 55)))) {
      const yy = yPix(v);
      if (yy < y + 16 || yy > y + h - 1) continue;
      svgEl("line", { x1: m.l, x2: m.l + larg, y1: yy, y2: yy, stroke: Math.abs(v) < 1e-9 ? gradeForte : grade }, svg);
      const tl = svgEl("text", { x: m.l - 8, y: yy + 4, "text-anchor": "end", fill: eixo, "font-size": 11 }, svg);
      tl.textContent = fx.fmtY ? fx.fmtY(v) : br(v);
    }
    const un = svgEl("text", { x: m.l - 8, y: y + 11, "text-anchor": "end", fill: cssVar(el, "--mudo"), "font-size": 10.5, "font-weight": 600 }, svg);
    un.textContent = fx.unY || "";
    if (!cfg.semGradeX)
      for (const v of tx) {
        const xx = xPix(v);
        if (xx <= m.l + 1 || xx >= m.l + larg - 1) continue;
        svgEl("line", { x1: xx, x2: xx, y1: y, y2: y + h, stroke: grade }, svg);
      }
    if (cfg.regiao) {
      const a = xPix(cfg.regiao[0]), b = xPix(cfg.regiao[1]);
      svgEl("rect", { x: a, y, width: b - a, height: h, fill: cssVar(el, "--destaque"), opacity: 0.07 }, svg);
    }
    const clip = svgEl("clipPath", { id: `c${Math.random().toString(36).slice(2)}` }, svg);
    svgEl("rect", { x: m.l, y, width: larg, height: h }, clip);
    const g = svgEl("g", { "clip-path": `url(#${clip.id})` }, svg);
    for (const tr of fx.tracos) desenharTraco(g, tr, cfg, xPix, yPix, m.l, larg);
    y += h + vao;
  });
  // eixo x, embaixo da última faixa
  const yb = H - m.b;
  for (const v of tx) {
    const xx = xPix(v);
    if (xx < m.l - 1 || xx > m.l + larg + 1 || (cfg.unX && xx > m.l + larg - 30)) continue;
    const tl = svgEl("text", { x: xx, y: yb + 17, "text-anchor": "middle", fill: eixo, "font-size": 11 }, svg);
    tl.textContent = cfg.fmtX ? cfg.fmtX(v) : br(v);
  }
  if (cfg.unX) {
    const t = svgEl("text", { x: m.l + larg, y: yb + 17, "text-anchor": "end", fill: cssVar(el, "--mudo"), "font-size": 10.5, "font-weight": 600 }, svg);
    t.textContent = cfg.unX;
  }
  for (const c of cfg.cursores || []) {
    const xx = xPix(c.t);
    svgEl("line", { x1: xx, x2: xx, y1: m.t - 4, y2: yb, stroke: cssVar(el, "--destaque"), "stroke-width": 1.2, "stroke-dasharray": "5 3" }, svg);
  }
  return { xPix, caixas, m, larg, W, H };
}

function desenharTraco(g, tr, cfg, xPix, yPix, x0px, larg) {
  const r = aleatorio(tr.semente || 7);
  const cor = tr.corDireta || `var(${tr.cor})`;
  const dt = (cfg.x1 - cfg.x0) / larg;
  if (tr.modo === "banda") {
    const topo = [], base = [];
    for (let px = 0; px <= larg; px += 1) {
      const ta = cfg.x0 + px * dt, tb = ta + dt;
      let mn = Infinity, mx = -Infinity;
      if (tr.env) {
        [mn, mx] = tr.env(ta, tb, r);
      } else {
        for (let k = 0; k < 24; k++) {
          const v = tr.f(ta + (k / 24) * dt, r);
          mn = Math.min(mn, v);
          mx = Math.max(mx, v);
        }
      }
      topo.push(`${x0px + px},${yPix(mx).toFixed(1)}`);
      base.push(`${x0px + px},${yPix(mn).toFixed(1)}`);
    }
    const p = svgEl("polygon", { points: topo.concat(base.reverse()).join(" ") }, g);
    p.style.fill = cor;
    p.style.fillOpacity = tr.opac ?? 0.82;
    if (tr.sel) { p.style.stroke = cor; p.style.strokeWidth = 1; }
    return;
  }
  const pts = [];
  const passo = tr.passo || 0.5;
  for (let px = 0; px <= larg; px += passo) {
    const t = cfg.x0 + px * dt;
    pts.push(`${(x0px + px).toFixed(1)},${yPix(tr.f(t, r)).toFixed(1)}`);
  }
  if (tr.sel) {
    const halo = svgEl("polyline", { points: pts.join(" "), fill: "none" }, g);
    halo.style.stroke = cor;
    halo.style.strokeWidth = (tr.larg || 1.5) + 5;
    halo.style.strokeOpacity = 0.18;
    halo.style.strokeLinejoin = "round";
  }
  const l = svgEl("polyline", { points: pts.join(" "), fill: "none" }, g);
  l.style.stroke = cor;
  l.style.strokeWidth = tr.larg || 1.5;
  l.style.strokeLinejoin = "round";
  if (tr.traco) l.style.strokeDasharray = tr.traco;
  if (tr.opac) l.style.strokeOpacity = tr.opac;
}

// Envoltórias (mín, máx) analíticas para a captura vista de longe.
function envTensao(ta, tb, r) {
  let a = 0;
  for (let k = 0; k <= 6; k++) a = Math.max(a, amplitudeTensao(ta + ((tb - ta) * k) / 6));
  const ruido = 0.6 + r() * 0.9;
  return [-(a + 5.2 + ruido), a + 1.6 + ruido * 0.6];
}
function envCorrente(ta, tb, r) {
  let a = 0;
  for (let k = 0; k <= 6; k++) a = Math.max(a, amplitudeCorrente(ta + ((tb - ta) * k) / 6));
  const ruido = 0.2 + r() * 0.4;
  return [-(a * 1.16 + ruido), a * 1.2 + ruido];
}

/* Espectro em dB com eixo de frequência logarítmico (ou linear), o máximo por coluna de pixel (nenhum pico some).
   cfg = { f0, f1, log, y0, y1, tracos: [{cor, nivel, comb, semente, larg}], faixa: [fa, fb], marcadores: [{f, rot}] } */
function picosRede(base = 0, supra = 0) {
  const p = [];
  for (let k = 1; k <= 40; k++) p.push([60 * k, k === 1 ? 0 + base : -26 - 1.1 * k - (k % 2 === 0 ? 14 : 0) + base]);
  for (let n = -24; n <= 24; n++) p.push([20000 + 120 * n, -47 - Math.abs(n) * 0.75 + supra + base]);
  for (let n = -12; n <= 12; n++) p.push([40040 + 120 * n, -63 - Math.abs(n) * 0.9 + supra + base]);
  for (let n = -6; n <= 6; n++) p.push([60060 + 120 * n, -76 - Math.abs(n) + supra + base]);
  p.push([95000, -88 + supra + base]);
  return p;
}
function espectro(el, cfg) {
  const W = el.clientWidth, H = el.clientHeight;
  const m = Object.assign({ l: 56, r: 16, t: 12, b: 28 }, cfg.margem || {});
  const svg = svgEl("svg", { viewBox: `0 0 ${W} ${H}` }, el);
  const larg = W - m.l - m.r, alt = H - m.t - m.b;
  const fx = (f) => (cfg.log ? Math.log10(f / cfg.f0) / Math.log10(cfg.f1 / cfg.f0) : (f - cfg.f0) / (cfg.f1 - cfg.f0));
  const xPix = (f) => m.l + fx(f) * larg;
  const fDe = (px) => (cfg.log ? cfg.f0 * Math.pow(cfg.f1 / cfg.f0, px / larg) : cfg.f0 + (px / larg) * (cfg.f1 - cfg.f0));
  const yPix = (v) => m.t + (1 - (v - cfg.y0) / (cfg.y1 - cfg.y0)) * alt;
  const grade = cssVar(el, "--grade"), eixo = cssVar(el, "--eixo");
  svgEl("rect", { x: m.l, y: m.t, width: larg, height: alt, fill: "none", stroke: cssVar(el, "--grade-forte") }, svg);
  if (cfg.faixa) {
    const a = xPix(cfg.faixa[0]), b = xPix(cfg.faixa[1]);
    const f = svgEl("rect", { x: a, y: m.t, width: b - a, height: alt }, svg);
    f.style.fill = "var(--acento)";
    f.style.fillOpacity = 0.06;
    const t = svgEl("text", { x: a + 6, y: m.t + 14, "font-size": 10.5, "font-weight": 600 }, svg);
    t.style.fill = "var(--acento)";
    t.textContent = cfg.rotFaixa || "2–150 kHz";
  }
  const fticks = cfg.log ? [100, 200, 500, 1000, 2000, 5000, 10000, 20000, 50000, 100000, 150000].filter((f) => f >= cfg.f0 && f <= cfg.f1) : ticks(cfg.f0, cfg.f1, 7);
  for (const f of fticks) {
    const xx = xPix(f);
    svgEl("line", { x1: xx, x2: xx, y1: m.t, y2: m.t + alt, stroke: grade }, svg);
    if (xx > m.l + larg - 24) continue;
    const t = svgEl("text", { x: xx, y: H - m.b + 17, "text-anchor": "middle", fill: eixo, "font-size": 11 }, svg);
    t.textContent = f >= 1000 ? br(f / 1000) + "k" : br(f);
  }
  const ut = svgEl("text", { x: m.l + larg, y: H - m.b + 17, "text-anchor": "end", fill: cssVar(el, "--mudo"), "font-size": 10.5, "font-weight": 600 }, svg);
  ut.textContent = "Hz";
  for (const v of ticks(cfg.y0, cfg.y1, Math.round(alt / 50))) {
    const yy = yPix(v);
    svgEl("line", { x1: m.l, x2: m.l + larg, y1: yy, y2: yy, stroke: grade }, svg);
    if (yy < m.t + 16) continue;
    const t = svgEl("text", { x: m.l - 8, y: yy + 4, "text-anchor": "end", fill: eixo, "font-size": 11 }, svg);
    t.textContent = br(v);
  }
  const un = svgEl("text", { x: m.l - 8, y: m.t + 11, "text-anchor": "end", fill: cssVar(el, "--mudo"), "font-size": 10.5, "font-weight": 600 }, svg);
  un.textContent = cfg.unY || "dBV";
  const clip = svgEl("clipPath", { id: `e${Math.random().toString(36).slice(2)}` }, svg);
  svgEl("rect", { x: m.l, y: m.t, width: larg, height: alt }, clip);
  const g = svgEl("g", { "clip-path": `url(#${clip.id})` }, svg);
  for (const tr of cfg.tracos) {
    const r = aleatorio(tr.semente || 3);
    const picos = picosRede(tr.base || 0, tr.supra || 0);
    const pts = [];
    for (let px = 0; px <= larg; px += 1) {
      const fa = fDe(px), fb = fDe(px + 1);
      let v = (tr.piso ?? -112) + (tr.base || 0) + (r() - 0.5) * 7 + (fa > 14000 && fa < 26000 ? 8 : 0) * (tr.hump ?? 1) + (fa < 400 ? 6 : 0);
      for (const [fp, a] of picos) {
        const d = fp < fa ? fa - fp : fp > fb ? fp - fb : 0;
        v = Math.max(v, a - 60 * Math.log10(1 + d / 2) - (d > 0 ? 6 : 0));
      }
      pts.push(`${m.l + px},${yPix(Math.max(cfg.y0 - 5, v)).toFixed(1)}`);
    }
    const l = svgEl("polyline", { points: pts.join(" "), fill: "none" }, g);
    l.style.stroke = `var(${tr.cor})`;
    l.style.strokeWidth = tr.larg || 1.2;
    if (tr.opac) l.style.strokeOpacity = tr.opac;
  }
  for (const mk of cfg.marcadores || []) {
    const xx = xPix(mk.f), yy = yPix(mk.v);
    const c = svgEl("path", { d: `M${xx} ${yy - 6} l-4.5 -7 h9 z` }, svg);
    c.style.fill = "var(--destaque)";
    const t = svgEl("text", { x: xx + (mk.dx || 8), y: yy - 9, "font-size": 11, "font-weight": 600 }, svg);
    t.style.fill = "var(--texto)";
    t.textContent = mk.rot;
  }
  return { xPix, yPix, m };
}

// Espectrograma (tempo x frequência), num canvas, com um mapa de cores perceptual (inferno).
const INFERNO = [[0, [0, 0, 4]], [0.2, [40, 11, 84]], [0.4, [101, 21, 110]], [0.55, [159, 42, 99]], [0.7, [212, 72, 66]], [0.85, [245, 125, 21]], [0.95, [250, 193, 39]], [1, [252, 255, 164]]];
function corMapa(v) {
  v = Math.max(0, Math.min(1, v));
  for (let i = 1; i < INFERNO.length; i++) {
    const [a, ca] = INFERNO[i - 1], [b, cb] = INFERNO[i];
    if (v <= b) {
      const u = (v - a) / (b - a);
      return ca.map((x, k) => x + (cb[k] - x) * u);
    }
  }
  return INFERNO[INFERNO.length - 1][1];
}
function espectrograma(el, cfg) {
  const m = Object.assign({ l: 56, r: 16, t: 12, b: 28 }, cfg.margem || {});
  const W = el.clientWidth, H = el.clientHeight, larg = W - m.l - m.r, alt = H - m.t - m.b;
  const cv = document.createElement("canvas");
  cv.width = larg; cv.height = alt;
  cv.style.left = m.l + "px"; cv.style.top = m.t + "px"; cv.style.width = larg + "px"; cv.style.height = alt + "px";
  el.appendChild(cv);
  const ctx = cv.getContext("2d");
  const img = ctx.createImageData(larg, alt);
  const r = aleatorio(11);
  for (let x = 0; x < larg; x++) {
    const t = x / larg;
    const evento = Math.exp(-Math.pow((t - 0.42) / 0.012, 2));
    const carga = t > 0.2 && t < 0.78 ? 1 : 0.35;
    for (let y = 0; y < alt; y++) {
      const f = (1 - y / alt) * cfg.fmax;
      let v = 0.13 + r() * 0.11 + 0.18 * Math.exp(-f / 3000);
      const f1 = 20000 + 600 * Math.sin(TAU * t * 1.3);
      v = Math.max(v, 0.88 * carga * Math.exp(-Math.pow((f - f1) / 260, 2)));
      v = Math.max(v, 0.6 * carga * Math.exp(-Math.pow((f - 2 * f1) / 300, 2)) * (0.75 + 0.25 * Math.sin(TAU * t * 9)));
      v = Math.max(v, 0.45 * carga * Math.exp(-Math.pow((f - 3 * f1) / 340, 2)));
      v = Math.max(v, (0.55 + 0.2 * r()) * evento * Math.exp(-f / 60000));
      if (f > 14000 && f < 26000) v += 0.07 * carga;
      const [cr, cg, cb] = corMapa(v);
      const i = (y * larg + x) * 4;
      img.data[i] = cr; img.data[i + 1] = cg; img.data[i + 2] = cb; img.data[i + 3] = 255;
    }
  }
  ctx.putImageData(img, 0, 0);
  const svg = svgEl("svg", { viewBox: `0 0 ${W} ${H}` }, el);
  const eixo = cssVar(el, "--eixo");
  for (const f of ticks(0, cfg.fmax, Math.round(alt / 45))) {
    const yy = m.t + (1 - f / cfg.fmax) * alt;
    if (yy < m.t + 16) continue;
    const t = svgEl("text", { x: m.l - 8, y: yy + 4, "text-anchor": "end", fill: eixo, "font-size": 11 }, svg);
    t.textContent = f >= 1000 ? br(f / 1000) + "k" : br(f);
  }
  const un = svgEl("text", { x: m.l - 8, y: m.t + 11, "text-anchor": "end", fill: cssVar(el, "--mudo"), "font-size": 10.5, "font-weight": 600 }, svg);
  un.textContent = "Hz";
  for (const v of ticks(cfg.t0, cfg.t1, Math.round(larg / 140))) {
    const xx = m.l + ((v - cfg.t0) / (cfg.t1 - cfg.t0)) * larg;
    const t = svgEl("text", { x: xx, y: H - m.b + 17, "text-anchor": "middle", fill: eixo, "font-size": 11 }, svg);
    t.textContent = cfg.fmtX ? cfg.fmtX(v) : br(v);
  }
}

// Figura XY (tensão x corrente): o laço de um ciclo.
function lissajous(el, cfg) {
  const W = el.clientWidth, H = el.clientHeight;
  const m = Object.assign({ l: 56, r: 16, t: 12, b: 28 }, cfg.margem || {});
  const svg = svgEl("svg", { viewBox: `0 0 ${W} ${H}` }, el);
  const larg = W - m.l - m.r, alt = H - m.t - m.b;
  const xPix = (v) => m.l + ((v - cfg.x0) / (cfg.x1 - cfg.x0)) * larg;
  const yPix = (v) => m.t + (1 - (v - cfg.y0) / (cfg.y1 - cfg.y0)) * alt;
  const grade = cssVar(el, "--grade"), eixo = cssVar(el, "--eixo");
  svgEl("rect", { x: m.l, y: m.t, width: larg, height: alt, fill: "none", stroke: cssVar(el, "--grade-forte") }, svg);
  for (const v of ticks(cfg.x0, cfg.x1, 5)) {
    const xx = xPix(v);
    svgEl("line", { x1: xx, x2: xx, y1: m.t, y2: m.t + alt, stroke: grade }, svg);
    const t = svgEl("text", { x: xx, y: H - m.b + 17, "text-anchor": "middle", fill: eixo, "font-size": 11 }, svg);
    t.textContent = br(v);
  }
  for (const v of ticks(cfg.y0, cfg.y1, 4)) {
    const yy = yPix(v);
    svgEl("line", { x1: m.l, x2: m.l + larg, y1: yy, y2: yy, stroke: grade }, svg);
    const t = svgEl("text", { x: m.l - 8, y: yy + 4, "text-anchor": "end", fill: eixo, "font-size": 11 }, svg);
    t.textContent = br(v);
  }
  for (const [txt, x, y, anc] of [[cfg.unX, m.l + larg, H - m.b + 17, "end"], [cfg.unY, m.l - 8, m.t + 11, "end"]]) {
    const t = svgEl("text", { x, y, "text-anchor": anc, fill: cssVar(el, "--mudo"), "font-size": 10.5, "font-weight": 600 }, svg);
    t.textContent = txt;
  }
  for (const [k, cor, op] of [[0, "--t5", 0.25], [1, "--t5", 0.45], [2, "--t5", 1]]) {
    const r = aleatorio(5 + k);
    const pts = [];
    for (let i = 0; i <= 600; i++) {
      const t = 200 + k * 0.4 + i / 600 / 60;
      pts.push(`${xPix(tensao(t, r)).toFixed(1)},${yPix(corrente(t, r) * (1 - 0.05 * k)).toFixed(1)}`);
    }
    const l = svgEl("polyline", { points: pts.join(" "), fill: "none" }, svg);
    l.style.stroke = `var(${cor})`;
    l.style.strokeWidth = 1.3;
    l.style.strokeOpacity = op;
  }
}

document.addEventListener("DOMContentLoaded", () => desenharIcones());
