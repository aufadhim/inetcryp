"""Generate a secret-free HTML report for the current paper portfolio."""
import html
import os
from datetime import datetime, timezone
from typing import Any, Dict, List


def generate_report(summary: Dict[str, Any], signals: List[Dict[str, Any]] | None = None, title: str = "INETCRYP Crypto Report") -> str:
    signals = signals or []
    rows = "".join(
        f"<tr><td>{html.escape(str(item.get('symbol', '-')))}</td>"
        f"<td>{html.escape(str(item.get('label', '-')))}</td>"
        f"<td>{float(item.get('score', 0)):.1f}</td>"
        f"<td>{float(item.get('confidence_pct', 0)):.1f}%</td>"
        f"<td>{html.escape(', '.join(item.get('reasons', [])))}</td></tr>"
        for item in signals
    ) or '<tr><td colspan="5">Belum ada sinyal</td></tr>'
    generated = datetime.now(timezone.utc).isoformat()
    return f"""<!doctype html>
<html lang="id"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(title)}</title><style>
body{{font-family:Arial,sans-serif;background:#0b1220;color:#e5e7eb;margin:0;padding:24px}}
.wrap{{max-width:1000px;margin:auto}}.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:12px}}
.card{{background:#111c31;border:1px solid #263653;border-radius:12px;padding:16px}}
table{{width:100%;border-collapse:collapse;margin-top:20px;background:#111c31}}th,td{{padding:11px;border-bottom:1px solid #263653;text-align:left}}th{{color:#67e8f9}}
.muted{{color:#94a3b8;font-size:12px}}h1{{color:#67e8f9}}
</style></head><body><div class="wrap"><h1>🐋 INETCRYP</h1>
<div class="muted">{html.escape(title)} · Generated {html.escape(generated)} · Crypto market 24/7</div>
<div class="grid" style="margin-top:20px"><div class="card"><div class="muted">Equity</div><h2>${float(summary.get('equity',0)):,.2f}</h2></div>
<div class="card"><div class="muted">Cash</div><h2>${float(summary.get('cash_usdt',0)):,.2f}</h2></div>
<div class="card"><div class="muted">Return</div><h2>{float(summary.get('net_return_pct',0)):+.2f}%</h2></div>
<div class="card"><div class="muted">Open Positions</div><h2>{int(summary.get('open_positions_count',0))}</h2></div></div>
<h2>Signal Radar</h2><table><thead><tr><th>Pair</th><th>Label</th><th>Score</th><th>Confidence</th><th>Reasons</th></tr></thead><tbody>{rows}</tbody></table>
</div></body></html>"""


def write_latest_report(summary: Dict[str, Any], signals: List[Dict[str, Any]] | None = None, report_dir: str = "data/reports") -> str:
    os.makedirs(report_dir, exist_ok=True)
    path = os.path.join(report_dir, "latest.html")
    temp = path + ".tmp"
    with open(temp, "w", encoding="utf-8") as handle:
        handle.write(generate_report(summary, signals))
    os.replace(temp, path)
    return path
