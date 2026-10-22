/* Own implementation; no FluxScout assets or invented orderflow. */
(() => {
  const panel=document.createElement('section');
  panel.className='glass-card rounded-xl p-4 my-4';
  const title=document.createElement('h2');title.className='text-cyan-400 font-bold';title.textContent='Anomali pasar';
  const note=document.createElement('p');note.className='text-xs text-gray-400 my-2';
  const content=document.createElement('div');content.className='overflow-x-auto';
  const history=document.createElement('details');
  const label=document.createElement('summary');label.textContent='Riwayat sinyal & hasil sejak deteksi';
  const ledger=document.createElement('pre');ledger.className='text-xs whitespace-pre-wrap my-2';history.append(label,ledger);
  panel.append(title,note,content,history);document.querySelector('#radar-mount').append(panel);
  async function refresh() {
    try {
      const response=await fetch('/api/radar/anomalies');
      if(!response.ok){note.textContent='Status tidak tersedia; login diperlukan.';return;}
      const data=await response.json();
      note.textContent=`${data.status}${data.source_error?` · sumber ${data.source_error} HTTP ${data.source_http_status??'?'}`:''}${data.stale?' · DATA BASI':''} · ${data.items?.length||0} anomali · ${data.total_calls||0} deteksi tersimpan. Skor bukan peluang cuan. SHORT hanya observasi, tidak dieksekusi di spot.`;
      content.replaceChildren();
      const table=document.createElement('table');table.className='w-full text-xs text-left';
      const head=document.createElement('tr');
      for(const text of ['CoinGecko ID','Arah / skor','1h','Vol/MC','Alasan','Orderbook']){const cell=document.createElement('th');cell.className='p-2';cell.textContent=text;head.append(cell);}table.append(head);
      for(const item of data.items||[]){
        const row=document.createElement('tr');
        const reasonNames={high_turnover_on_rising_price_hypothesis_not_manipulation_proof:'Volume relatif tinggi saat harga menguat',dip_with_observed_bid_imbalance_hypothesis:'Koreksi harga dengan dominasi bid teramati'};
        const values=[item.coin_id,`${item.signal} · ${item.score}`,`${item.change_1h_pct?.toFixed(2)}%`,`${item.volume_mc_ratio?.toFixed(2)}x`,reasonNames[item.reason]||item.reason,
          item.orderbook?`${item.orderbook.bid_ask_ratio?.toFixed(2)||'?'}x · ${item.orderbook.received_at}`:'Tidak ada konfirmasi orderbook'];
        for(const text of values){const cell=document.createElement('td');cell.className='p-2 border-t border-gray-800';cell.textContent=text;row.append(cell);}table.append(row);
      }
      content.append(table);
      if(!data.items?.length){const empty=document.createElement('p');empty.textContent='Belum ada anomali yang memenuhi syarat dari data tersedia.';content.append(empty);}
      const review=Object.entries(data.evaluation||{}).map(([h,groups]) => `${h}: `+Object.entries(groups).map(([direction,g])=>`${direction} ${g.observed} hasil / ${g.missed} terlewat · perubahan arah rata-rata ${g.mean_directional_change_pct?.toFixed(2)??'?'}%${g.sample_sufficient?'':' · sampel kecil'}`).join(' | ')).join('\n');
      ledger.textContent=review+'\n\n'+((data.calls||[]).map(c=>`${c.detected_at} · ${c.entry.coin_id} ${c.entry.signal} · ${c.state}\n`+
        Object.entries(c.outcomes).map(([h,o])=>`${h}: ${o.status}${o.status==='OBSERVED'?` · perubahan arah ${o.directional_change_pct.toFixed(2)}% · estimasi net LONG ${o.estimated_long_net_pct?.toFixed(2)??'tidak diketahui'}%`:''}`).join(' | ')).join('\n\n')||'Belum ada hasil matang. Tidak menggunakan riwayat milik pihak lain.');
    }catch{note.textContent='Koneksi/status anomali belum tersedia.';}
  }
  refresh();setInterval(refresh,60000);
})();
