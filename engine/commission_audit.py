"""Read-only commission observations. Never writes orders or stores credentials."""
import math
from datetime import datetime, timezone


def commission_rates(payload):
    totals={}
    for role in ("maker","taker"):
        for side,side_field in (("buy","buyer"),("sell","seller")):
            total=0
            for group in ("standardCommission","specialCommission","taxCommission"):
                fields=payload.get(group,{})
                if group=="standardCommission" and not fields:raise ValueError("Missing standard commission")
                total+=float(fields.get(role,0))+float(fields.get(side_field,0))
            if not math.isfinite(total) or not 0<=total<1:raise ValueError("Invalid commission")
            totals[role+"_"+side]=total
    discount=payload.get("discount",{})
    # Enabled does not prove sufficient BNB at execution time. Do not assume it.
    return {"undiscounted_rates":totals,"bnb_discount_enabled":bool(discount.get("enabledForAccount") and discount.get("enabledForSymbol")),
            "policy":"No BNB discount assumed; balance, pair and execution currency matter"}


def audit_commissions(client,symbols):
    result={"observed_at":datetime.now(timezone.utc).isoformat(),"mode":"production_read_only","configured_trading_mode":client.mode,
            "status":"ok","symbols":{},"historical_policy":"Current fees are not historical fees; existing experiment costs unchanged"}
    for symbol in list(dict.fromkeys(symbols))[:8]:
        try:
            payload=client.get_account_commission(symbol,production_read_only=True)
            if not payload:raise ValueError("Unavailable")
            result["symbols"][symbol]={"status":"verified",**commission_rates(payload)}
        except Exception:
            result["symbols"][symbol]={"status":"unavailable","reason":"Could not verify commission; keep explicit simulation assumption"}
    if not result["symbols"] or any(v["status"]!="verified" for v in result["symbols"].values()):result["status"]="incomplete"
    return result
