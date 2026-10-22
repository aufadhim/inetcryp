/* Read-only research progress and isolated paper tournament. */
(() => {
  const panel = document.createElement('section');
  panel.className = 'glass-card rounded-xl p-4 space-y-3';
  const title = document.createElement('h2');
  title.className = 'text-cyan-400 font-bold';
  title.textContent = 'Evaluasi & pembelajaran';
  const body = document.createElement('pre');
  body.className = 'text-xs text-gray-300 whitespace-pre-wrap';
  body.textContent = 'Memuat status riset…';
  const metrics=document.createElement('div');metrics.className='workspace-metrics';
  const details=document.createElement('details');details.className='technical-details';
  const summary=document.createElement('summary');summary.textContent='Lihat detail teknis & diagnostik';
  details.append(summary,body);panel.append(title,metrics,details);
  document.querySelector('#research-mount').append(panel);
  async function refresh() {
    try {
      const response = await fetch('/api/research/status');
      if (!response.ok) { body.textContent = 'Login dashboard diperlukan untuk melihat hasil riset.'; return; }
      const data = await response.json();
      window.dispatchEvent(new CustomEvent('inetcryp:research',{detail:data}));
      metrics.replaceChildren();
      const statusNames={rejected_validation:'Belum lolos',completed:'Selesai',awaiting_fresh_holdout:'Menunggu data baru',running:'Berjalan',insufficient_data:'Data belum cukup'};
      for(const [label,value] of [['Eksperimen',statusNames[data.research?.status]||'Menunggu'],['Label pembelajaran',data.online_learning?.trained_labels??0],['Uji harian',`${data.daily_research?.results?.length||0}/6`],['Champion',data.tournament?.champion||'Belum lolos']]){
        const card=document.createElement('div');card.className='metric-card';const name=document.createElement('span');name.textContent=label;const val=document.createElement('strong');val.textContent=value;card.append(name,val);metrics.append(card);
      }
      const research = data.research || {};
      const tournament = data.tournament || {};
      const lines = [
        `Worker: ${data.status}${data.stale ? ' · data kedaluwarsa' : ''} | ${data.phase || ''}`,
        ...Object.entries(data.workers || {}).map(([name,w]) => `${name}: ${w.status}${w.stale ? ' · heartbeat basi' : ''}`),
        `Diperbarui: ${data.at || '-'} | ${data.symbols?.length || 0} koin`,
        `Eksperimen: ${research.status || 'berjalan / menunggu data'} · kandidat ${research.development?.length || 0}/12`,
        `Progress: ${data.progress?.phase || '-'} ${data.progress?.completed || 0}/${data.progress?.total || 12}`,
        `Riset harian WIB: ${data.daily_research?.status || 'menunggu'} · ${data.daily_research?.results?.length || 0}/6 uji · menjanjikan ${data.daily_research?.promising ?? '-'} (eksplorasi, belum lolos validasi)`,
        `Evaluasi biaya & 3 periode: ${data.daily_review?.status || 'menunggu'} · ${data.daily_review?.candidates?.length || 0} ditinjau · layak uji baru ${data.daily_review?.worth_fresh_validation ?? '-'}`,
        `Uji exit fixed / SL+ / trailing: ${data.exit_research?.status || 'menunggu'} · ${data.exit_research?.results?.length || 0}/2 kandidat · diagnostik berpasangan, bukan return portofolio`,
        `Online learner: ${data.online_learning?.status || 'menunggu'} · ${data.online_learning?.trained_labels || 0} pembaruan · ${data.online_learning?.counts?.pending || 0} prediksi menunggu hasil 30 menit`,
        `Radar lintas koin: ${data.opportunity_radar?.binance?.length || 0} Binance · ${data.opportunity_radar?.dex?.length || 0} DEX (observe-only) · ${data.opportunity_radar?.recorded_calls || 0} deteksi tersimpan`,
        `Watchlist Binance: ${(data.opportunity_radar?.binance || []).map(r => r.symbol).join(', ') || '-'}`,
        `Learner radar (model terpisah): ${data.online_radar_learning?.trained_labels || 0} label · ${data.online_radar_learning?.counts?.pending || 0} menunggu · bukan rekomendasi beli`,
        ...Object.entries(data.opportunity_radar?.outcomes || {}).map(([h,v]) => `Hasil radar ${h}: ${v.observed} teramati · ${v.missed} terlewat (tidak direkonstruksi)`),
        ...(data.opportunity_radar?.dex || []).slice(0,3).map(r => `DEX ${r.chain}:${r.pair.slice(0,12)}… · liquidity ${r.liquidity ?? '?'} USD · biaya/kemampuan jual belum terverifikasi`),
        `Prediksi berikut: ${data.online_learning?.next_forecast_slot || '-'} · hasil berikut: ${data.online_learning?.next_outcome_due || '-'} (timestamp UTC)`,
        `Kualitas prediksi (lebih kecil lebih baik): Brier ${data.online_learning?.brier?.toFixed(4) ?? '-'} vs baseline ${data.online_learning?.baseline_brier?.toFixed(4) ?? '-'} · hanya pengamatan, belum boleh trading`,
        ...(data.exit_research?.results || []).map(r => `${r.candidate.parameters.family} · ${r.normal.policies.fixed.trades} trade berpasangan $50: fixed ${r.normal.policies.fixed.net_pnl_sum.toFixed(2)} | SL+ ${r.normal.policies.sl_plus.net_pnl_sum.toFixed(2)} | trailing ${r.normal.policies.trailing.net_pnl_sum.toFixed(2)} USDT (jumlah PnL trade, bukan return porto)`),
        `Verifikasi komisi: ${data.commission_audit?.status || 'menunggu'} · mode ${data.commission_audit?.mode || '-'} · tarif aktual saat ini, bukan historis`,
        `Terpilih: ${research.selected?.parameters?.family || '-'} | lolos backtest: ${research.gate?.eligible ?? 'belum selesai'}`,
        `Holdout baru: ${research.holdout_start || '-'} sampai ${research.end || '-'} · ${research.holdout_policy || 'legacy'}`,
        `CoinGecko: ${data.sources?.coingecko?.status || 'belum diperiksa'} · ${data.sources?.coingecko?.coins || 0} metadata koin`,
        `Funding/OI: ${JSON.stringify(data.sources?.derivatives || {})}`,
        ...(research.gate?.reasons || []),
        `Champion paper: ${tournament.champion || 'belum ada kandidat lolos'}`,
        ...(tournament.accounts || []).map(a => `${a.family}: ${a.status} · equity $${a.equity.toFixed(2)} · ${a.trades} trades · PF ${a.profit_factor.toFixed(2)} · DD ${a.max_drawdown_pct.toFixed(2)}% · forward ${a.days.toFixed(1)} hari`),
        `Gemini researcher: ${data.adviser?.status || 'menunggu evaluasi'}`,
        `Cost-flipped winners: ${data.diagnosis?.validation?.cost_flipped_winners ?? '-'} · kelompok di bawah 20 trade belum kuat`,
        `Baseline validation: cash ${data.research?.baselines?.cash?.net_pnl?.toFixed(2) ?? '-'} | EMA ${data.research?.baselines?.ema_cross?.net_pnl?.toFixed(2) ?? '-'} | buy-hold capped ${data.research?.baselines?.buy_hold_capped?.net_pnl?.toFixed(2) ?? '-'}`,
        'Forward paper: quote orderbook teramati; sinyal terlambat >90 detik ditolak. Riset, collector dan monitor berjalan terpisah.',
        'Lab memakai akun paper terpisah; porto lama tetap dipertahankan.'
      ];
      body.textContent = lines.join('\n');
    } catch { body.textContent = 'Status riset belum tersedia.'; }
  }
  setTimeout(refresh, 1500);
  setInterval(refresh, 60000);
})();
