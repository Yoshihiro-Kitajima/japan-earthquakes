// このページ用の小さな読み込み・描画の仕組み（データファイルを読み、各図を描き直す）
(() => {
  const sources = {
    yearly: { url: 'data/yearly.csv', type: 'csv' },
    big: { url: 'data/big.csv', type: 'csv' },
    land: { url: 'data/japan_land.json', type: 'json' },
  };
  const D = {};
  Object.keys(sources).forEach((k) => { D[k] = { status: 'loading', data: [], v: 0 }; });
  const calcs = {}, cache = {}, draws = {};

  const run = (name) => {
    document.querySelectorAll(`[data-draw="${name}"]`).forEach((el) => {
      if (el.closest('[hidden]')) return;
      try { draws[name](el); } catch (e) { console.error(`描画 ${name}`, e); }
    });
  };
  const runAll = () => Object.keys(draws).forEach(run);

  window.dash = {
    colors: ['var(--series-1)'],
    data(id) {
      const c = calcs[id];
      if (c) {
        const ins = c.inputs.map((i) => D[i] || { status: 'missing' });
        if (ins.some((x) => x.status === 'error')) return { status: 'error', data: null };
        if (ins.some((x) => x.status !== 'ok')) return { status: 'loading', data: null };
        const key = ins.map((x) => x.v).join(',');
        if (!cache[id] || cache[id].key !== key) cache[id] = { key, data: c.fn(...ins.map((x) => x.data)) };
        return { status: 'ok', data: cache[id].data };
      }
      return D[id] || { status: 'missing', data: [] };
    },
    calc(id, o) { calcs[id] = o; },
    draw(name, fn) { if (fn) { draws[name] = fn; return; } run(name); },
  };

  const load = async (k) => {
    const s = sources[k];
    try {
      const res = await fetch(s.url, { cache: 'no-cache' });
      if (!res.ok) throw new Error(`${s.url}: ${res.status}`);
      const text = await res.text();
      D[k] = { status: 'ok', data: s.type === 'csv' ? d3.csvParse(text) : JSON.parse(text), v: Date.now() };
    } catch (e) {
      console.error(e);
      D[k] = { status: 'error', data: [], v: Date.now() };
    }
  };

  window.addEventListener('DOMContentLoaded', async () => {
    runAll();
    await Promise.all(Object.keys(sources).map(load));
    runAll();
    let w = document.getElementById('dash-root').clientWidth, t = null;
    new ResizeObserver(() => {
      const nw = document.getElementById('dash-root').clientWidth;
      if (nw === w) return;
      w = nw;
      clearTimeout(t);
      t = setTimeout(runAll, 150);
    }).observe(document.getElementById('dash-root'));
  });
})();
