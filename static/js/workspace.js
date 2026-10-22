/* Presentation only. Existing data sources and trading controls are unchanged. */
(() => {
  const mount=document.getElementById('overview-content');
  mount.innerHTML=`<div class="page-heading"><div><p class="eyebrow">YOUR MARKET WORKSPACE</p><h2>Gambaran pasar, lebih jelas.</h2><p>Temukan peluang. Periksa buktinya. Kelola risiko sebelum mengambil keputusan.</p><div id="overview-time" class="overview-time">Menunggu pembaruan data…</div></div><span class="mode-pill">PAPER MODE</span></div>
    <div class="workspace-metrics">
      <article class="metric-card"><span>Ekuitas simulasi</span><strong id="ov-equity" class="metric-skeleton">—</strong><small id="ov-return">Portofolio virtual, bukan saldo Binance</small></article>
      <article class="metric-card"><span>Peluang terpantau</span><strong id="ov-opportunities" class="metric-skeleton">—</strong><small id="ov-coverage">Binance & DEX · bukan rekomendasi beli</small></article>
      <article class="metric-card"><span>Hasil yang dipelajari</span><strong id="ov-labels" class="metric-skeleton">—</strong><small>Label nyata setelah prediksi matang</small></article>
      <article class="metric-card"><span>Kesiapan strategi</span><strong id="ov-ready" class="metric-skeleton">—</strong><small id="ov-ready-note">Melewati validasi sebelum dipromosikan</small></article>
    </div>
    <div class="overview-columns">
      <section class="workspace-card"><h3>Market watchlist</h3><p class="subtitle" id="ov-watch-note">Shortlist likuiditas & momentum dari data publik Binance. Peringkat bukan peluang profit.</p><div style="overflow-x:auto"><table class="workspace-table"><thead><tr><th>ASET</th><th>24 JAM</th><th>VOLUME USDT</th><th>SKOR</th></tr></thead><tbody id="ov-watchlist"></tbody></table></div><div id="ov-watch-empty" class="empty-state">Memuat watchlist…</div><button class="workspace-link" data-go="radar">Lihat radar anomali <span aria-hidden="true">↗</span></button></section>
      <section class="workspace-card"><h3>Di balik layar</h3><p class="subtitle">Status proses, bukan janji hasil trading.</p><div id="ov-activity"><p class="empty-state">Menunggu status sistem…</p></div><button class="workspace-link" data-go="research">Buka research lab <span aria-hidden="true">↗</span></button></section>
    </div>
    <div class="workspace-banner"><strong>Riset dulu. Eksekusi setelah terbukti.</strong> PnL simulasi, perubahan harga token, dan performa model adalah metrik berbeda. Tidak ada order uang asli yang diaktifkan oleh dashboard ini.</div>`;
  mount.querySelectorAll('[data-go]').forEach(button=>button.addEventListener('click',()=>switchTab(button.dataset.go)));
  const put=(id,text)=>{const node=document.getElementById(id);node.textContent=text;node.classList.remove('metric-skeleton');};
  const num=n=>typeof n==='number'&&Number.isFinite(n);
  const compact=n=>num(n)?new Intl.NumberFormat('en-US',{notation:'compact',maximumFractionDigits:1}).format(n):'—';
  window.addEventListener('inetcryp:paper',({detail:d})=>{
    put('ov-equity',num(d.equity)?new Intl.NumberFormat('en-US',{style:'currency',currency:'USD',maximumFractionDigits:2}).format(d.equity):'—');
    if(num(d.net_return_pct)){
      const node=document.getElementById('ov-return');node.textContent=`${d.net_return_pct>=0?'+':''}${d.net_return_pct.toFixed(2)}% total return · simulasi`;
      node.className=d.net_return_pct<0?'negative':'positive';
    }
  });
  window.addEventListener('inetcryp:research',({detail:d})=>{
    const radar=d.opportunity_radar||{},fixed=d.online_learning||{},dynamic=d.online_radar_learning||{};
    put('ov-opportunities',String((radar.binance?.length||0)+(radar.dex?.length||0)));
    put('ov-coverage',`${radar.binance?.length||0} Binance · ${radar.dex?.length||0} pasangan DEX`);
    put('ov-labels',compact((fixed.trained_labels||0)+(dynamic.trained_labels||0)));
    const champion=d.tournament?.champion;
    put('ov-ready',champion?'Paper champion':'Dalam riset');
    document.getElementById('ov-ready').style.fontSize='21px';
    put('ov-ready-note',champion?'Model terpilih untuk paper, bukan live':'Belum ada champion yang lolos');
    const stamp=new Date(d.at);put('overview-time',Number.isNaN(stamp.getTime())?'Waktu pembaruan tidak tersedia':`Diperbarui ${stamp.toLocaleString('id-ID',{timeZone:'Asia/Jakarta',day:'2-digit',month:'short',hour:'2-digit',minute:'2-digit'})} WIB${d.stale?' · status kedaluwarsa':''}`);
    const body=document.getElementById('ov-watchlist');body.replaceChildren();
    for(const r of (radar.binance||[]).slice(0,8)){
      const row=document.createElement('tr'),asset=document.createElement('td');
      const mark=document.createElement('span');mark.className='coin-monogram';mark.textContent=r.symbol?.slice(0,2)||'?';
      asset.append(mark,document.createTextNode(r.symbol||'Unknown'));row.append(asset);
      for(const [value,kind] of [[num(r.change_24h_pct)?`${r.change_24h_pct>=0?'+':''}${r.change_24h_pct.toFixed(2)}%`:'—',num(r.change_24h_pct)?(r.change_24h_pct>=0?'positive':'negative'):''],[compact(r.quote_volume_24h),''],[num(r.score)?r.score.toFixed(1):'—','']]){
        const cell=document.createElement('td');cell.textContent=value;cell.className=kind;row.append(cell);
      }body.append(row);
    }
    const empty=document.getElementById('ov-watch-empty');empty.hidden=Boolean(radar.binance?.length);empty.textContent='Belum ada kandidat dari data tersedia.';
    if(radar.as_of){const age=Date.now()-new Date(radar.as_of).getTime();document.getElementById('ov-watch-note').textContent=`Shortlist likuiditas & momentum Binance. ${age>900000?'Data lebih dari 15 menit—jangan anggap terkini.':'Peringkat bukan peluang profit.'}`;}
    const activity=document.getElementById('ov-activity');activity.replaceChildren();
    const workers=d.workers||{};
    const states={sleeping:'Aktif · jeda',running:'Berjalan',error:'Perlu diperiksa'};
    const stages=[['Pengumpulan data',workers.collector?.stale?'Perlu diperiksa':states[workers.collector?.status]||'Menunggu','Snapshot harga, likuiditas, dan metadata'],['Pembelajaran model',fixed.status==='collecting_labels'?'Mengumpulkan hasil':fixed.status||'Menunggu',`${fixed.trained_labels||0} label kontrol · ${dynamic.trained_labels||0} label radar`],['Eksperimen harian',d.daily_research?.status==='completed'?'Selesai':d.daily_research?.status||'Menunggu',`${d.daily_research?.results?.length||0}/6 kandidat dievaluasi`],['Trading uang asli','Tidak aktif','Observasi dan paper trading saja']];
    for(const [name,state,description] of stages){const row=document.createElement('div');row.className='activity-row';const info=document.createElement('span');info.textContent=name;const small=document.createElement('small');small.textContent=description;info.append(small);const value=document.createElement('strong');value.textContent=state;if(state==='Perlu diperiksa'||state==='error')value.style.color='#fbbf24';row.append(info,value);activity.append(row);}
  });
})();
