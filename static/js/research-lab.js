/* Read-only research progress and isolated paper tournament. */
(() => {
  const panel = document.createElement('section');
  panel.className = 'glass-card rounded-xl p-4 space-y-3';
  const title = document.createElement('h2');
  title.className = 'text-cyan-400 font-bold';
  title.textContent = 'Research Lab · Autonomous Paper Tournament';
  const body = document.createElement('pre');
  body.className = 'text-xs text-gray-300 whitespace-pre-wrap';
  body.textContent = 'Memuat status riset…';
  panel.append(title, body);
  document.querySelector('main').prepend(panel);
  async function refresh() {
    try {
      const response = await fetch('/api/research/status');
      if (!response.ok) { body.textContent = 'Login dashboard diperlukan untuk melihat hasil riset.'; return; }
      const data = await response.json();
      const research = data.research || {};
      const tournament = data.tournament || {};
      const lines = [
        `Worker: ${data.status}${data.stale ? ' · data kedaluwarsa' : ''} | ${data.phase || ''}`,
        `Diperbarui: ${data.at || '-'} | ${data.symbols?.length || 0} koin`,
        `Eksperimen: ${research.status || 'berjalan / menunggu data'} · kandidat ${research.development?.length || 0}/12`,
        `Progress: ${data.progress?.phase || '-'} ${data.progress?.completed || 0}/${data.progress?.total || 12}`,
        `Terpilih: ${research.selected?.parameters?.family || '-'} | lolos backtest: ${research.gate?.eligible ?? 'belum selesai'}`,
        `Holdout baru: ${research.holdout_start || '-'} sampai ${research.end || '-'} · ${research.holdout_policy || 'legacy'}`,
        `CoinGecko: ${data.sources?.coingecko?.status || 'belum diperiksa'} · ${data.sources?.coingecko?.coins || 0} metadata koin`,
        `Funding/OI: ${JSON.stringify(data.sources?.derivatives || {})}`,
        ...(research.gate?.reasons || []),
        `Champion paper: ${tournament.champion || 'belum ada kandidat lolos'}`,
        ...(tournament.accounts || []).map(a => `${a.family}: ${a.status} · equity $${a.equity.toFixed(2)} · ${a.trades} trades · PF ${a.profit_factor.toFixed(2)} · DD ${a.max_drawdown_pct.toFixed(2)}% · forward ${a.days.toFixed(1)} hari`),
        `Gemini researcher: ${data.adviser?.status || 'menunggu evaluasi'}`,
        'Lab memakai akun paper terpisah; porto lama tetap dipertahankan.'
      ];
      body.textContent = lines.join('\n');
    } catch { body.textContent = 'Status riset belum tersedia.'; }
  }
  setTimeout(refresh, 1500);
  setInterval(refresh, 60000);
})();
