"""Prospective, delayed-label online learning. No credentials or order API."""
import json
import math
import sqlite3
from pathlib import Path
import numpy as np
import pandas as pd
from engine.observed_paper import check_quote,depth_fill
from engine.research_lab import features

VERSION="online_v1"
DIM=9


def vector(frame):
    f=features(frame);r=f.iloc[-1];c=float(r.Close)
    x=np.array([1,(c/float(f.iloc[-3].Close)-1)*100,(float(r.ema9)/float(r.ema21)-1)*100,
        (float(r.ema21)/float(r.ema50)-1)*100,(float(r.rsi)-50)/50,
        float(r.rvol)-1,float(r.atr_pct),float(r.regime=="uptrend"),float(r.regime=="downtrend")])
    if len(x)!=DIM or not np.isfinite(x).all():raise ValueError("Invalid online features")
    return np.clip(x,-5,5).tolist()


def probability(weights,x):
    z=max(-30,min(30,sum(a*b for a,b in zip(weights,x))))
    return 1/(1+math.exp(-z))


def learn(model,x,label):
    # Predict-then-learn: caller records the old forecast before revealing label.
    p=probability(model["weights"],x)
    rate=.03/math.sqrt(1+model["labels"]/200)
    model["weights"]=[max(-5,min(5,w-rate*((p-label)*v+.001*w))) for w,v in zip(model["weights"],x)]
    model["labels"]+=1;model["positives"]+=int(label)


def connect(path):
    Path(path).parent.mkdir(parents=True,exist_ok=True)
    db=sqlite3.connect(path,timeout=30);db.row_factory=sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("CREATE TABLE IF NOT EXISTS state (id TEXT PRIMARY KEY,payload TEXT)")
    db.execute("CREATE TABLE IF NOT EXISTS predictions (id TEXT PRIMARY KEY,symbol TEXT,issued_at TEXT,due_at TEXT,status TEXT,payload TEXT)")
    db.execute("CREATE INDEX IF NOT EXISTS prediction_due ON predictions(status,due_at)")
    db.commit();return db


def get_model(db):
    row=db.execute("SELECT payload FROM state WHERE id=?",(VERSION,)).fetchone()
    return json.loads(row[0]) if row else {"version":VERSION,"weights":[0.0]*DIM,"labels":0,"positives":0}


def save_model(db,model):
    db.execute("INSERT OR REPLACE INTO state VALUES (?,?)",(VERSION,json.dumps(model,allow_nan=False)))


def issue(db,symbol,slot,x,book,now,buy_fee=.001,sell_fee=.001,fee_source="assumed_0.1pct"):
    now=pd.Timestamp(now)
    if len(x)!=DIM or not all(math.isfinite(float(v)) and abs(v)<=5 for v in x):raise ValueError("Invalid online vector")
    if not all(math.isfinite(v) and 0<=v<1 for v in (buy_fee,sell_fee)):raise ValueError("Invalid online fees")
    if check_quote(book,now):return False
    if not 0<=(now-pd.Timestamp(slot)).total_seconds()<=90:return False
    model=get_model(db)
    fill=depth_fill(book["asks"],quote=50/(1+buy_fee))
    if not fill:return False
    key=VERSION+":"+symbol+":"+pd.Timestamp(slot).isoformat()
    payload={"x":x,"probability":probability(model["weights"],x),
        "baseline_probability":(model["positives"]+1)/(model["labels"]+2),
        "model_labels_at_issue":model["labels"],"quantity":fill["quantity"],"entry_price":fill["price"],
        "buy_fee":buy_fee,"sell_fee":sell_fee,"fee_source":fee_source,"slot":pd.Timestamp(slot).isoformat(),
        "quote_received_at":book["received_at"],"latency_ms":book["latency_ms"],"size":50}
    with db:
        cur=db.execute("INSERT OR IGNORE INTO predictions VALUES (?,?,?,?,?,?)",
            (key,symbol,now.isoformat(),(now+pd.Timedelta(minutes=30)).isoformat(),"pending",json.dumps(payload,allow_nan=False)))
    return cur.rowcount==1


def settle(db,row,book,now):
    now=pd.Timestamp(now);due=pd.Timestamp(row["due_at"])
    if now<due or check_quote(book,now):return False
    payload=json.loads(row["payload"])
    fill=depth_fill(book["bids"],quantity=payload["quantity"])
    if not fill:return False
    net=fill["notional"]*(1-payload["sell_fee"])-payload["size"]
    timely=(now-due).total_seconds()<=90
    status="scored" if timely else "late_discarded"
    payload.update(settled_at=now.isoformat(),exit_price=fill["price"],net_pnl_50=net,
                   exit_quote_received_at=book["received_at"],exit_latency_ms=book["latency_ms"])
    if timely:
        label=int(net>0);payload["label"]=label
        payload["brier"]=(payload["probability"]-label)**2
        payload["baseline_brier"]=(payload["baseline_probability"]-label)**2
    with db:
        # One committed outcome and one model update, even after crashes/retries.
        cur=db.execute("UPDATE predictions SET status=?,payload=? WHERE id=? AND status='pending'",
                       (status,json.dumps(payload,allow_nan=False),row["id"]))
        if cur.rowcount!=1:return False
        if timely:
            model=get_model(db);learn(model,payload["x"],label);save_model(db,model)
    return True


def summary(db,now):
    counts=dict(db.execute("SELECT status,count(*) FROM predictions GROUP BY status").fetchall())
    records=[json.loads(r[0]) for r in db.execute("SELECT payload FROM predictions WHERE status='scored' ORDER BY issued_at DESC LIMIT 2000")]
    n=len(records)
    brier=sum(r["brier"] for r in records)/n if n else None
    baseline=sum(r["baseline_brier"] for r in records)/n if n else None
    selected=[r for r in records if r["probability"]>=.6 and r["model_labels_at_issue"]>=200]
    days=db.execute("SELECT count(DISTINCT substr(issued_at,1,10)) FROM predictions WHERE status='scored'").fetchone()[0]
    recent=records[:100]
    drift=len(recent)>=100 and sum(r["brier"]-r["baseline_brier"] for r in recent)/len(recent)>.02
    reasons=[]
    if n<200:reasons.append("fewer_than_200_prospective_labels")
    if days<30:reasons.append("fewer_than_30_observed_UTC_days")
    if brier is None or brier>=baseline:reasons.append("not_better_than_prequential_base_rate")
    if len(selected)<50:reasons.append("fewer_than_50_confident_forecasts_after_warmup")
    if not selected or sum(r["net_pnl_50"] for r in selected)<=0:reasons.append("no_positive_cost_adjusted_signal_sample")
    if drift:reasons.append("recent_prediction_deterioration")
    return {"version":VERSION,"at":pd.Timestamp(now).isoformat(),"status":"collecting_labels" if n<200 else ("drift_warning" if drift else "learning"),
        "last_prediction_at":db.execute("SELECT max(issued_at) FROM predictions").fetchone()[0],
        "next_outcome_due":db.execute("SELECT min(due_at) FROM predictions WHERE status='pending'").fetchone()[0],
        "next_forecast_slot":(pd.Timestamp(now).floor("30min")+pd.Timedelta(minutes=30)).isoformat(),
        "counts":counts,"trained_labels":get_model(db)["labels"],"scored_window":n,"observed_days":days,
        "brier":brier,"baseline_brier":baseline,"confident_forecasts":len(selected),
        "diagnostic_net_pnl_sum":sum(r["net_pnl_50"] for r in selected),
        "review_ready":not reasons,"gate_reasons":reasons,"live_trading":False,"paper_admission":False,
        "scope":"Prospective prediction diagnostics, not a portfolio or guaranteed return; promotion requires independent paper evaluation",
        "horizon_minutes":30,"fee_policy":"Frozen at prediction; taker commission, actual ask/bid depth; no BNB discount assumed"}


def cycle(public,root,now=None,radar=False):
    now=pd.Timestamp(now) if now is not None else pd.Timestamp.now(tz="UTC")
    root=Path(root);db=connect(root/("online-radar-learning.sqlite" if radar else "online-learning.sqlite"))
    errors=[]
    def book(symbol):
        import time
        started=time.perf_counter();raw=public("depth",symbol=symbol,limit=20)
        return {"bids":raw["bids"],"asks":raw["asks"],"latency_ms":(time.perf_counter()-started)*1000,
                "received_at":pd.Timestamp.now(tz="UTC").isoformat()}
    try:
        # No financial positions exist here: discard missed deadlines without
        # fetching a backlog of prices or inventing historical settlements.
        with db:
            db.execute("UPDATE predictions SET status='late_discarded' WHERE status='pending' AND due_at<?",
                       ((now-pd.Timedelta(seconds=90)).isoformat(),))
        for row in db.execute("SELECT * FROM predictions WHERE status='pending' AND due_at<=? ORDER BY due_at LIMIT 24",(now.isoformat(),)).fetchall():
            try:
                quote=book(row["symbol"]);settle(db,row,quote,pd.Timestamp.now(tz="UTC"))
            except Exception as exc:errors.append({"phase":"settle","symbol":row["symbol"],"error_type":type(exc).__name__})
        slot=now.floor("30min")
        if (now-slot).total_seconds()<=90:
            selected=["BTCUSDT","ETHUSDT","SOLUSDT"]
            if radar:
                # Separate model/database; never mix selected momentum with the control group.
                selection_key="radar_selection:"+slot.isoformat()
                frozen=db.execute("SELECT payload FROM state WHERE id=?",(selection_key,)).fetchone()
                if frozen:selected=json.loads(frozen[0])["symbols"]
                else:
                    selected=[]
                    path=root/"opportunity-radar.json"
                    if path.exists():
                        snapshot=json.loads(path.read_text(encoding="utf-8"))
                        age=(now-pd.Timestamp(snapshot["as_of"])).total_seconds()
                        if 0<=age<=900:
                            import re
                            selected=list(dict.fromkeys(r["symbol"] for r in snapshot.get("binance",[])
                                if re.fullmatch(r"[A-Z0-9]{3,20}",r.get("symbol","")) and r["symbol"] not in {"BTCUSDT","ETHUSDT","SOLUSDT"}))[:3]
                    if selected:
                        with db:db.execute("INSERT OR IGNORE INTO state VALUES (?,?)",(selection_key,json.dumps({"symbols":selected,"frozen_at":now.isoformat()})))
            for symbol in selected:
                key=VERSION+":"+symbol+":"+slot.isoformat()
                if db.execute("SELECT 1 FROM predictions WHERE id=?",(key,)).fetchone():continue
                try:
                    raw=public("klines",symbol=symbol,interval="15m",limit=120)
                    closed=[r for r in raw if pd.Timestamp(int(r[0]),unit="ms",tz="UTC")+pd.Timedelta(minutes=15)<=now]
                    frame=pd.DataFrame({name:[float(r[i]) for r in closed] for name,i in (("Open",1),("High",2),("Low",3),("Close",4),("Volume",5))},
                        index=pd.to_datetime([r[0] for r in closed],unit="ms",utc=True))
                    if frame.empty or frame.index[-1]+pd.Timedelta(minutes=15)!=slot:raise ValueError("Stale prediction candle")
                    x=vector(frame);quote=book(symbol)
                    fees={}
                    fee_path=root/"commission-audit.json"
                    if fee_path.exists():
                        audit=json.loads(fee_path.read_text(encoding="utf-8"))
                        age=(now-pd.Timestamp(audit["observed_at"])).total_seconds()
                        item=audit.get("symbols",{}).get(symbol,{})
                        if 0<=age<=21600 and audit.get("mode")=="production_read_only" and item.get("status")=="verified":
                            rates=item["undiscounted_rates"]
                            fees={"buy_fee":rates["taker_buy"],"sell_fee":rates["taker_sell"],"fee_source":"verified_current_undiscounted"}
                    issue(db,symbol,slot,x,quote,pd.Timestamp.now(tz="UTC"),**fees)
                except Exception as exc:errors.append({"phase":"issue","symbol":symbol,"error_type":type(exc).__name__})
        result=summary(db,pd.Timestamp.now(tz="UTC"));result["errors"]=errors
        result["population"]="radar_dynamic_separate_model" if radar else "fixed_control_BTC_ETH_SOL"
        return result
    finally:db.close()
