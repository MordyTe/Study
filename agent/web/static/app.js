/* Dashboard frontend: live chart with signal markers + state/stats panels. */
(() => {
  const chartEl = document.getElementById('chart');
  const chart = LightweightCharts.createChart(chartEl, {
    layout: { background: { color: '#161b22' }, textColor: '#8b949e' },
    grid: { vertLines: { color: '#21262d' }, horzLines: { color: '#21262d' } },
    timeScale: { timeVisible: true, secondsVisible: false, borderColor: '#30363d' },
    rightPriceScale: { borderColor: '#30363d' },
    crosshair: { mode: 0 },
    autoSize: true,
  });
  const series = chart.addCandlestickSeries({
    upColor: '#2ea043', downColor: '#f85149',
    wickUpColor: '#2ea043', wickDownColor: '#f85149', borderVisible: false,
  });

  let currentTf = '5';
  let priceLines = [];
  let markers = [];

  async function loadCandles(tf) {
    const res = await fetch(`/api/candles?tf=${tf}&limit=500`);
    const bars = await res.json();
    series.setData(bars);
    chart.timeScale().fitContent();
  }

  function clearOverlays() {
    priceLines.forEach(l => series.removePriceLine(l));
    priceLines = [];
  }

  function drawSignal(sig) {
    if (['win', 'win_partial', 'loss', 'expired_unfilled', 'expired_active', 'invalidated', 'rejected'].includes(sig.state)) return;
    const color = sig.direction === 'long' ? '#2ea043' : '#f85149';
    priceLines.push(series.createPriceLine({ price: (sig.entry_lo + sig.entry_hi) / 2, color, lineStyle: 0, title: `entry #${sig.id}` }));
    priceLines.push(series.createPriceLine({ price: sig.sl, color: '#f85149', lineStyle: 2, title: 'SL' }));
    [sig.tp1, sig.tp2, sig.tp3].forEach((tp, i) => {
      priceLines.push(series.createPriceLine({ price: tp, color: '#58a6ff', lineStyle: 3, title: `TP${i + 1}` }));
    });
    markers.push({
      time: Math.floor(sig.created_ts / 1000), position: sig.direction === 'long' ? 'belowBar' : 'aboveBar',
      color, shape: sig.direction === 'long' ? 'arrowUp' : 'arrowDown', text: `${sig.style} ${sig.direction}`,
    });
    markers.sort((a, b) => a.time - b.time);
    series.setMarkers(markers);
  }

  const fmtTs = ts => new Date(ts).toISOString().slice(5, 16).replace('T', ' ');

  async function loadSignals() {
    const res = await fetch('/api/signals?limit=50');
    const sigs = await res.json();
    const tbody = document.querySelector('#signals-table tbody');
    tbody.innerHTML = '';
    clearOverlays(); markers = [];
    sigs.forEach(sig => {
      const tr = document.createElement('tr');
      tr.className = sig.direction;
      const stateCls = sig.state.includes('win') ? 'state-win' : sig.state === 'loss' ? 'state-loss' : `state-${sig.state}`;
      tr.innerHTML = `
        <td>${fmtTs(sig.created_ts)}</td><td>${sig.style}</td>
        <td>${sig.direction === 'long' ? '🟢 L' : '🔴 S'}</td>
        <td>${sig.entry_lo}–${sig.entry_hi}</td><td>${sig.sl}</td>
        <td>${sig.tp1} / ${sig.tp2} / ${sig.tp3}</td>
        <td>${sig.rr ?? sig.rr_tp2 ?? ''}</td>
        <td>${Math.round((sig.confidence || 0) * 100)}%</td>
        <td>${sig.llm_verdict || '–'}</td>
        <td class="${stateCls}">${sig.state}</td>
        <td class="${(sig.realized_r || 0) > 0 ? 'pos' : (sig.realized_r || 0) < 0 ? 'neg' : ''}">${sig.realized_r ?? ''}</td>`;
      tbody.appendChild(tr);
      drawSignal(sig);
    });
  }

  const kv = (k, v, cls = '') => `<div><span class="k">${k}</span><span class="${cls}">${v}</span></div>`;

  async function loadState() {
    try {
      const s = await (await fetch('/api/state')).json();
      let html = '';
      html += kv('price', s.price ? s.price.toFixed(2) : '–');
      for (const [tf, b] of Object.entries(s.biases || {}))
        html += kv(`bias ${tf}`, b, b === 'bull' ? 'pos' : b === 'bear' ? 'neg' : '');
      const d = s.deriv || {};
      if (d.funding_rate != null) html += kv('funding', (d.funding_rate * 100).toFixed(4) + '%', d.funding_rate > 0 ? 'pos' : 'neg');
      if (d.oi_change_1h_pct != null) html += kv('OI Δ1h', d.oi_change_1h_pct.toFixed(2) + '%');
      if (d.ls_ratio != null) html += kv('L/S ratio', d.ls_ratio.toFixed(2));
      if (d.long_liq_5m_usd) html += kv('long liqs 5m', '$' + (d.long_liq_5m_usd / 1e6).toFixed(2) + 'M', 'neg');
      if (d.short_liq_5m_usd) html += kv('short liqs 5m', '$' + (d.short_liq_5m_usd / 1e6).toFixed(2) + 'M', 'pos');
      if (s.cvd_30m != null) html += kv('CVD 30m', s.cvd_30m.toFixed(1), s.cvd_30m > 0 ? 'pos' : 'neg');
      document.getElementById('state-body').innerHTML = html || 'warming up…';
    } catch (e) { /* server warming up */ }
  }

  async function loadStats() {
    try {
      const s = await (await fetch('/api/stats')).json();
      let html = '';
      html += kv('resolved', s.resolved ?? 0);
      html += kv('win rate', s.win_rate != null ? s.win_rate + '%' : '–');
      html += kv('total R', s.total_r ?? 0, (s.total_r || 0) >= 0 ? 'pos' : 'neg');
      html += kv('expectancy', s.expectancy_r != null ? s.expectancy_r + 'R' : '–');
      html += kv('profit factor', s.profit_factor ?? '–');
      html += kv('open', s.open ?? 0);
      document.getElementById('stats-body').innerHTML = html;
    } catch (e) { /* ignore */ }
  }

  // Live updates: WebSocket locally, polling fallback on serverless (Vercel)
  let wsFailures = 0;
  let pollTimer = null;

  function startPolling() {
    if (pollTimer) return;
    const badge = document.getElementById('conn');
    badge.textContent = 'cloud · polling';
    badge.className = 'badge on';
    pollTimer = setInterval(async () => {
      try {
        const bars = await (await fetch(`/api/candles?tf=${currentTf}&limit=2`)).json();
        bars.forEach(b => series.update(b));
      } catch (e) { /* transient */ }
    }, 20000);
    setInterval(() => { loadSignals(); }, 60000);
  }

  function connectWs() {
    const proto = location.protocol === 'https:' ? 'wss' : 'ws';
    const badge = document.getElementById('conn');
    let ws;
    try { ws = new WebSocket(`${proto}://${location.host}/ws`); }
    catch (e) { startPolling(); return; }
    ws.onopen = () => { wsFailures = 0; badge.textContent = 'live'; badge.className = 'badge on'; };
    ws.onclose = () => {
      wsFailures += 1;
      if (wsFailures >= 2) { startPolling(); return; }  // serverless: no WS — poll instead
      badge.textContent = 'reconnecting…'; badge.className = 'badge off';
      setTimeout(connectWs, 3000);
    };
    ws.onmessage = ev => {
      const msg = JSON.parse(ev.data);
      if (msg.type === 'candle' && msg.tf === currentTf) series.update(msg.bar);
      if (msg.type === 'signal' || msg.type === 'signal_event') { loadSignals(); loadStats(); }
    };
    setInterval(() => { if (ws.readyState === 1) ws.send('ping'); }, 25000);
  }

  document.querySelectorAll('#tf-switch button').forEach(btn => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('#tf-switch button').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      currentTf = btn.dataset.tf;
      loadCandles(currentTf).then(loadSignals);
    });
  });

  loadCandles(currentTf).then(loadSignals);
  loadState(); loadStats();
  setInterval(loadState, 10000);
  setInterval(loadStats, 30000);
  connectWs();
})();
