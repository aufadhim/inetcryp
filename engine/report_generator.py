"""Generate a secret-free HTML report for the current paper portfolio."""
import html
import json
import os
from datetime import datetime
from typing import Any, Dict, List
from zoneinfo import ZoneInfo


def _num(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _control_status() -> Dict[str, Any]:
    try:
        with open("data/trading_control.json", encoding="utf-8") as handle:
            data = json.load(handle)
        return {
            "mode": str(data.get("mode", "unknown")),
            "entries": bool(data.get("paper_new_entries_enabled", False)),
            "reason": str(data.get("reason", "Tidak ada alasan tercatat.")),
        }
    except (OSError, ValueError, TypeError):
        return {"mode": "unknown", "entries": False, "reason": "Trading control tidak dapat dibaca; entry ditahan."}


def generate_report(summary: Dict[str, Any], signals: List[Dict[str, Any]] | None = None, title: str = "INETCRYP Crypto Report") -> str:
    signals = sorted(signals or [], key=lambda item: _num(item.get("score")), reverse=True)
    control = _control_status()
    signal_rows = "".join(
        f"<tr><td><strong>{html.escape(str(item.get('symbol', '-')))}</strong></td>"
        f"<td><span class='badge {('bull' if item.get('label') == 'BULLISH_SETUP' else 'risk' if item.get('label') == 'BEARISH_RISK' else 'wait')}'>{html.escape(str(item.get('label', '-')).replace('_', ' '))}</span></td>"
        f"<td><div class='score'><i style='width:{max(0,min(100,_num(item.get('score'))))}%'></i></div><small>{_num(item.get('score')):.1f}/100</small></td>"
        f"<td>{_num(item.get('confidence_pct')):.1f}%</td>"
        f"<td>{html.escape(', '.join(item.get('reasons', [])) or 'Belum ada konfirmasi kuat')}</td></tr>"
        for item in signals
    ) or '<tr><td colspan="5" class="empty">Belum ada pair yang lolos radar saat laporan dibuat.</td></tr>'
    positions = summary.get("open_positions", {}) or {}
    position_rows = "".join(
        f"<tr><td><strong>{html.escape(str(symbol))}</strong></td><td>${_num(pos.get('entry_price')):,.6f}</td>"
        f"<td>${_num(pos.get('mark_price', pos.get('entry_price'))):,.6f}</td><td class='{('pos' if _num(pos.get('pnl_usd')) >= 0 else 'neg')}'>{_num(pos.get('pnl_usd')):+.2f} USDT</td>"
        f"<td>{html.escape(str(pos.get('strategy', '-')))}</td></tr>" for symbol, pos in positions.items()
    ) or '<tr><td colspan="5" class="empty">Tidak ada posisi terbuka. Modal berada dalam cash.</td></tr>'
    trades = list(summary.get("history", []) or [])[-10:][::-1]
    trade_rows = "".join(
        f"<tr><td>{html.escape(str(t.get('exit_time','-'))[:19].replace('T',' '))}</td><td><strong>{html.escape(str(t.get('symbol','-')))}</strong></td>"
        f"<td>{html.escape(str(t.get('strategy','-')))}</td><td class='{('pos' if _num(t.get('pnl_usd')) > 0 else 'neg')}'>{_num(t.get('pnl_usd')):+.2f}</td>"
        f"<td>{_num(t.get('pnl_pct')):+.2f}%</td><td>{html.escape(str(t.get('reason','-')))}</td></tr>" for t in trades
    ) or '<tr><td colspan="6" class="empty">Belum ada transaksi yang ditutup.</td></tr>'
    generated = datetime.now(ZoneInfo("Asia/Jakarta")).strftime("%d %b %Y · %H:%M WIB")
    ret = _num(summary.get("net_return_pct"))
    entries_text = "ENTRY AKTIF" if control["entries"] else "RESEARCH QUARANTINE"
    status_class = "live" if control["entries"] else "quarantine"
    return f"""<!doctype html>
<html lang="id"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(title)}</title><style>
:root{{--bg:#07101e;--panel:#0e1b30;--panel2:#12233d;--line:#233958;--text:#eef6ff;--muted:#91a6c4;--cyan:#32d6ff;--green:#39e58c;--red:#ff6b7a;--amber:#f7bd52}}
*{{box-sizing:border-box}}body{{font-family:Inter,Segoe UI,Arial,sans-serif;background:radial-gradient(circle at 80% -10%,#123159 0,transparent 38%),var(--bg);color:var(--text);margin:0}}
.wrap{{max-width:1240px;margin:auto;padding:28px 20px 56px}}header{{display:flex;justify-content:space-between;gap:20px;align-items:center;margin-bottom:22px}}h1{{margin:0;color:var(--cyan);font-size:30px;letter-spacing:.5px}}h2{{font-size:19px;margin:28px 0 12px}}.muted{{color:var(--muted);font-size:12px}}.status{{padding:9px 13px;border-radius:999px;font-size:12px;font-weight:800;letter-spacing:.4px}}.quarantine{{color:#ffd78a;background:#3a2a12;border:1px solid #76511b}}.live{{color:#8affbc;background:#103521;border:1px solid #236742}}
.notice{{background:linear-gradient(90deg,#2e2110,#151c2c);border:1px solid #68491b;border-radius:14px;padding:15px 17px;margin-bottom:18px}}.notice strong{{color:var(--amber)}}
.grid{{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px}}.card{{background:linear-gradient(145deg,var(--panel2),var(--panel));border:1px solid var(--line);border-radius:15px;padding:17px;min-height:105px}}.card b{{font-size:24px;display:block;margin-top:12px}}.card small{{color:var(--muted)}}.pos{{color:var(--green)}}.neg{{color:var(--red)}}
.split{{display:grid;grid-template-columns:1.2fr .8fr;gap:15px}}.panel{{background:rgba(14,27,48,.86);border:1px solid var(--line);border-radius:15px;padding:17px;overflow:hidden}}.statline{{display:flex;justify-content:space-between;padding:11px 0;border-bottom:1px solid var(--line)}}.statline:last-child{{border:0}}
.tablewrap{{overflow:auto;border:1px solid var(--line);border-radius:14px}}table{{width:100%;border-collapse:collapse;background:rgba(14,27,48,.88);min-width:720px}}th,td{{padding:12px;border-bottom:1px solid var(--line);text-align:left;font-size:13px}}th{{color:var(--cyan);background:#10213a;font-size:11px;text-transform:uppercase;letter-spacing:.5px}}tr:last-child td{{border:0}}.empty{{color:var(--muted);text-align:center;padding:24px}}
.badge{{display:inline-block;padding:5px 8px;border-radius:7px;font-size:10px;font-weight:800}}.bull{{color:#7dffb2;background:#103925}}.risk{{color:#ff9ca6;background:#401a24}}.wait{{color:#bdd1ec;background:#22334b}}.score{{height:5px;background:#263750;border-radius:9px;width:100px;margin-bottom:5px}}.score i{{display:block;height:100%;background:linear-gradient(90deg,#2ea9ff,#39e58c);border-radius:9px}}footer{{margin-top:30px;padding-top:16px;border-top:1px solid var(--line);color:var(--muted);font-size:11px;line-height:1.6}}
@media(max-width:850px){{.grid{{grid-template-columns:repeat(2,1fr)}}.split{{grid-template-columns:1fr}}header{{align-items:flex-start;flex-direction:column}}}}@media(max-width:480px){{.wrap{{padding:20px 12px 40px}}.grid{{grid-template-columns:1fr 1fr}}.card b{{font-size:20px}}}}
</style></head><body><div class="wrap"><header><div><h1>🐋 INETCRYP</h1><div class="muted">24/7 Crypto Intelligence · Paper Trading · {html.escape(generated)}</div></div><span class="status {status_class}">{entries_text}</span></header>
<div class="notice"><strong>Mode: {html.escape(control['mode'])}</strong><br><span class="muted">{html.escape(control['reason'])} Ini laporan riset dan paper trading, bukan rekomendasi investasi.</span></div>
<section class="grid"><div class="card"><small>Paper Equity</small><b>${_num(summary.get('equity')):,.2f}</b><small>Modal awal ${_num(summary.get('initial_balance')):,.2f}</small></div>
<div class="card"><small>Net PnL</small><b class="{('pos' if ret >= 0 else 'neg')}">${_num(summary.get('net_pnl_usd')):+,.2f}</b><small>{ret:+.2f}% return</small></div>
<div class="card"><small>Win Rate</small><b>{_num(summary.get('win_rate_pct')):.1f}%</b><small>{int(summary.get('winning_trades_count',0))} win · {int(summary.get('losing_trades_count',0))} loss</small></div>
<div class="card"><small>Open Positions</small><b>{int(summary.get('open_positions_count',0))}</b><small>Cash ${_num(summary.get('cash_usdt')):,.2f}</small></div></section>
<h2>Performance & Risk</h2><div class="split"><div class="panel"><div class="statline"><span>Closed trades</span><strong>{int(summary.get('closed_trades_count',0))}</strong></div><div class="statline"><span>Realized PnL</span><strong class="{('pos' if _num(summary.get('realized_pnl_usd')) >= 0 else 'neg')}">{_num(summary.get('realized_pnl_usd')):+.2f} USDT</strong></div><div class="statline"><span>Unrealized PnL</span><strong>{_num(summary.get('unrealized_pnl_usd')):+.2f} USDT</strong></div></div><div class="panel"><div class="statline"><span>Profit factor</span><strong>{_num(summary.get('profit_factor')):.2f}</strong></div><div class="statline"><span>Max drawdown</span><strong>{_num(summary.get('max_drawdown_pct')):.2f}%</strong></div><div class="statline"><span>Last scan</span><strong class="muted">{html.escape(str(summary.get('last_scan_time','-'))[:19].replace('T',' '))}</strong></div></div></div>
<h2>Open Positions</h2><div class="tablewrap"><table><thead><tr><th>Pair</th><th>Entry</th><th>Mark</th><th>Net PnL</th><th>Strategy</th></tr></thead><tbody>{position_rows}</tbody></table></div>
<h2>Signal Radar</h2><div class="tablewrap"><table><thead><tr><th>Pair</th><th>Status</th><th>Score</th><th>Confidence</th><th>Evidence</th></tr></thead><tbody>{signal_rows}</tbody></table></div>
<h2>10 Closed Trades Terbaru</h2><div class="tablewrap"><table><thead><tr><th>Exit (UTC)</th><th>Pair</th><th>Strategy</th><th>PnL USDT</th><th>PnL</th><th>Exit reason</th></tr></thead><tbody>{trade_rows}</tbody></table></div>
<footer>Data berasal dari paper journal dan market screener INETCRYP. Orderbook bersifat snapshot dan dapat berubah cepat. Tidak ada transaksi live yang dilakukan oleh report ini. Jangan menganggap skor sebagai kepastian profit.</footer>
</div></body></html>"""


def write_latest_report(summary: Dict[str, Any], signals: List[Dict[str, Any]] | None = None, report_dir: str = "data/reports") -> str:
    os.makedirs(report_dir, exist_ok=True)
    path = os.path.join(report_dir, "latest.html")
    temp = path + ".tmp"
    with open(temp, "w", encoding="utf-8") as handle:
        handle.write(generate_report(summary, signals))
    os.replace(temp, path)
    return path
