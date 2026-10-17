import os
import json
import time
import math
from datetime import datetime, timezone
from threading import RLock
from typing import Dict, Any, List, Optional
from engine.binance_client import BinanceClient
from engine.metrics import calculate_crypto_metrics
from engine.intraday import entry_signal as technical_entry, market_regime, STRATEGY


class CryptoPaperTrader:
    def __init__(self, data_file: str = "data/paper_trading_journal.json", client: Optional[BinanceClient] = None, *, persist=True, clock=None, control_file: Optional[str] = None):
        self.persist = persist
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.data_file = data_file
        # A custom journal (tests/research) must not inherit production's
        # global trading quarantine. Production keeps the established path.
        if control_file is not None:
            self.control_file = control_file
        elif os.path.normpath(data_file) == os.path.normpath("data/paper_trading_journal.json"):
            self.control_file = "data/trading_control.json"
        else:
            self.control_file = os.path.join(os.path.dirname(data_file), "trading_control.json")
        self.client = client or BinanceClient()
        self.profile = os.getenv("PAPER_PROFILE", "active").lower().strip()
        self.tp_pct = float(os.getenv("TARGET_PROFIT_PCT", 3.0))
        self.sl_pct = float(os.getenv("STOP_LOSS_PCT", 1.5))
        self.max_alloc = float(os.getenv("MAX_ALLOCATION_PER_TRADE_USDT", 50.0))
        default_trigger = "0.6" if self.profile == "active" else "0.8"
        default_trail = "0.5" if self.profile == "active" else "0.6"
        default_hold = "240" if self.profile == "active" else "360"
        self.sl_plus_trigger_pct = float(os.getenv("SL_PLUS_TRIGGER_PCT", default_trigger))
        self.sl_plus_lock_pct = float(os.getenv("SL_PLUS_LOCK_PCT", 0.1))
        self.sl_plus_trail_pct = float(os.getenv("SL_PLUS_TRAIL_PCT", default_trail))
        self.max_hold_minutes = int(os.getenv("MAX_HOLD_MINUTES", default_hold))
        self.cooldown_minutes = int(os.getenv("LOSS_COOLDOWN_MINUTES", 30))
        self.strategy_pause_hours = int(os.getenv("STRATEGY_PAUSE_HOURS", 6))
        self.max_loss_streak = int(os.getenv("MAX_STRATEGY_LOSS_STREAK", 3))
        self.risk_per_trade_pct = float(os.getenv("PAPER_RISK_PER_TRADE_PCT", 0.25))
        self.daily_loss_limit_pct = float(os.getenv("PAPER_DAILY_LOSS_LIMIT_PCT", 1.0))
        self.new_entries_enabled = os.getenv("PAPER_NEW_ENTRIES_ENABLED", "true").lower() == "true"
        self.init_balance = float(os.getenv("PAPER_TRADING_BALANCE", 1000.0))
        self.fee_pct = 0.1
        self.slippage_pct = 0.05
        if self.persist:
            self._ensure_data_dir()
        self._lock = RLock()
        self.state = self._load_state()

    def _ensure_data_dir(self):
        os.makedirs(os.path.dirname(self.data_file), exist_ok=True)

    def _load_state(self) -> Dict[str, Any]:
        if self.persist and os.path.exists(self.data_file):
            try:
                with open(self.data_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return {
            "initial_balance": self.init_balance,
            "cash_usdt": self.init_balance,
            "equity": self.init_balance,
            "open_positions": {},
            "history": [],
            "strategy_state": {},
            "last_scan_time": ""
        }

    def _save_state(self):
        if not self.persist:
            return
        try:
            temp_file = self.data_file + ".tmp"
            with open(temp_file, "w", encoding="utf-8") as f:
                json.dump(self.state, f, indent=2)
            os.replace(temp_file, self.data_file)
        except Exception:
            pass

    def reset_state(self, initial_balance: float = 1000.0) -> Dict[str, Any]:
        if initial_balance <= 0:
            raise ValueError("initial_balance harus lebih besar dari nol")
        with self._lock:
            self.state = {
            "initial_balance": initial_balance,
            "cash_usdt": initial_balance,
            "equity": initial_balance,
            "open_positions": {},
            "history": [],
            "strategy_state": {},
                "last_scan_time": datetime.now(timezone.utc).isoformat()
            }
            self._save_state()
            return self.get_summary()

    def run_eval_cycle(self, symbols: Optional[List[str]] = None, timeframe: str = "15m") -> Dict[str, Any]:
        """Run one forward testing cycle across symbols."""
        if symbols is None:
            # Top liquid watch symbols
            symbols = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "DOGEUSDT", "SUIUSDT", "PEPEUSDT", "AVAXUSDT"]

        with self._lock:
            return self._run_eval_cycle_locked(symbols, timeframe)

    def _run_eval_cycle_locked(self, symbols: Optional[List[str]], timeframe: str) -> Dict[str, Any]:
        now_str = self.clock().isoformat()
        self.state["last_scan_time"] = now_str
        notifications = []

        # 1. Manage Existing Open Positions
        positions_to_close = []
        total_open_value = 0.0

        for sym, pos in self.state["open_positions"].items():
            try:
                df = self.client.get_klines(sym, interval=timeframe, limit=201)
                if len(df) < 2:
                    continue
                df_calc = getattr(self, "metrics_fn", calculate_crypto_metrics)(df.iloc[:-1])
                last_bar = df_calc.iloc[-1]
                curr_price = float(df.iloc[-1]["Close"])
                if not math.isfinite(curr_price) or curr_price <= 0:
                    continue
                entry_price = float(pos["entry_price"])
                pnl_pct = ((curr_price - entry_price) / entry_price) * 100.0

                # SL+ layer: move the protective stop from loss, to breakeven,
                # then trail locked profit as the position makes a new high.
                pos["highest_price"] = max(float(pos.get("highest_price", entry_price)), curr_price)
                stop_price = float(pos.get("stop_price", entry_price * (1 - self.sl_pct / 100.0)))
                if pnl_pct >= self.sl_plus_trigger_pct:
                    stop_price = max(stop_price, entry_price * (1 + self.sl_plus_lock_pct / 100.0))
                if pnl_pct >= self.sl_plus_trigger_pct * 2:
                    stop_price = max(stop_price, pos["highest_price"] * (1 - self.sl_plus_trail_pct / 100.0))
                pos["stop_price"] = stop_price

                current_val = pos["size_usd"] * (1 + (pnl_pct / 100.0))
                total_open_value += current_val

                exit_reason = None
                age_minutes = 0.0
                try:
                    age_minutes = (self.clock() - datetime.fromisoformat(pos["entry_time"])).total_seconds() / 60
                except Exception:
                    pass
                if pnl_pct >= self.tp_pct:
                    exit_reason = f"🎯 TP Terpenuhi (+{pnl_pct:.2f}%)"
                elif curr_price <= stop_price:
                    exit_reason = f"🛡️ SL+ Terpukul ({pnl_pct:+.2f}%)"
                elif age_minutes >= self.max_hold_minutes and pnl_pct < self.sl_plus_trigger_pct:
                    exit_reason = f"⏱️ Time Stop ({age_minutes:.0f}m)"
                elif pos.get("strategy") == STRATEGY and last_bar.get("EMA9", float("inf")) < last_bar.get("EMA21", 0):
                    exit_reason = "EMA9 below EMA21 (closed candle)"
                elif pos.get("strategy") != STRATEGY and last_bar.get("Divergence") == "BEARISH_DIVERGENCE":
                    exit_reason = "⚠️ Cuci Piring (Bearish Div)"
                elif pos.get("strategy") != STRATEGY and last_bar.get("Slipstream") == "SLIPSTREAM_BEAR" and pnl_pct < 0:
                    exit_reason = "Slipstream Bear Cross"

                if exit_reason:
                    positions_to_close.append((sym, curr_price, pnl_pct, exit_reason))
            except Exception:
                if not self.persist:
                    raise
                continue

        # Execute Closes
        for sym, exit_price, pnl_pct, reason in positions_to_close:
            pos = self.state["open_positions"].pop(sym)
            proceeds = self.liquidation_value(pos, exit_price)
            realized_pnl_usd = proceeds - pos["size_usd"]
            pnl_pct = realized_pnl_usd / pos["size_usd"] * 100
            self.state["cash_usdt"] += proceeds
            trade_record = {
                "symbol": sym,
                "strategy": pos.get("strategy", "legacy"),
                "accounting_version": pos.get("accounting_version", "legacy_gross"),
                "entry_time": pos["entry_time"],
                "exit_time": now_str,
                "entry_price": pos["entry_price"],
                "exit_price": exit_price,
                "pnl_pct": round(pnl_pct, 2),
                "pnl_usd": round(realized_pnl_usd, 2),
                "reason": reason
            }
            self.state["history"].append(trade_record)
            strategy = trade_record["strategy"]
            strategy_state = self.state.setdefault("strategy_state", {}).setdefault(strategy, {})
            if pnl_pct < 0:
                streak = int(strategy_state.get("loss_streak", 0)) + 1
                strategy_state["loss_streak"] = streak
                if streak >= self.max_loss_streak:
                    strategy_state["paused_until"] = datetime.fromtimestamp(
                        self.clock().timestamp() + self.strategy_pause_hours * 3600,
                        timezone.utc,
                    ).isoformat()
                    notifications.append(f"⏸️ {strategy} dipause {self.strategy_pause_hours} jam setelah {streak} loss beruntun.")
            else:
                strategy_state["loss_streak"] = 0
                strategy_state.pop("paused_until", None)
            notifications.append(f"🚪 CLOSED {sym}: {reason} | PnL: {pnl_pct:+.2f}% (${realized_pnl_usd:+.2f})")

        # 2. Scan For New Entries
        if not self._entries_allowed() or self._daily_loss_limit_hit():
            self.state["equity"] = self.get_summary(timeframe=timeframe)["equity"]
            self._save_state()
            return {"summary": self.get_summary(timeframe=timeframe), "notifications": notifications}
        strategy_state = self.state.setdefault("strategy_state", {}).setdefault(STRATEGY, {})
        paused_until = strategy_state.get("paused_until")
        if paused_until:
            try:
                if self.clock() < datetime.fromisoformat(paused_until):
                    self.state["equity"] = self.get_summary(timeframe=timeframe)["equity"]
                    self._save_state()
                    return {"summary": self.get_summary(timeframe=timeframe), "notifications": notifications}
                strategy_state.pop("paused_until", None)
                strategy_state["loss_streak"] = 0
            except (TypeError, ValueError):
                strategy_state.pop("paused_until", None)
        for sym in symbols:
            if len(self.state["open_positions"]) >= getattr(self, "max_open_positions", 1000000):
                break
            # Skip if already open
            if sym in self.state["open_positions"]:
                continue
            if self.state["cash_usdt"] < self.max_alloc:
                break  # Not enough free cash

            try:
                df = self.client.get_klines(sym, interval=timeframe, limit=201)
                if len(df) < 101:
                    continue
                # Exclude the current, potentially unfinished candle from signals.
                df_calc = getattr(self, "metrics_fn", calculate_crypto_metrics)(df.iloc[:-1])
                last_bar = df_calc.iloc[-1]
                curr_price = float(df.iloc[-1]["Close"])
                if not math.isfinite(curr_price) or curr_price <= 0:
                    continue
                # All new entries use the versioned intraday rule; legacy positions
                # retain their existing stops and allocation.
                entry_signal = technical_entry(df_calc)
                regime = market_regime(df_calc)
                candle_id = str(df_calc.index[-1])
                if self.state.get("last_entry_candle", {}).get(sym) == candle_id:
                    entry_signal = None
                if entry_signal and abs(curr_price - float(last_bar["Close"])) > 0.5 * float(last_bar["ATR14"]):
                    entry_signal = None
                if entry_signal:
                    self.state.setdefault("last_entry_candle", {})[sym] = candle_id
                    equity = float(self.get_summary(refresh=False, timeframe=timeframe)["equity"])
                    risk_budget = equity * self.risk_per_trade_pct / 100.0
                    risk_sized_alloc = risk_budget / (self.sl_pct / 100.0)
                    alloc = min(self.max_alloc, risk_sized_alloc, self.state["cash_usdt"])
                    if alloc <= 0:
                        continue
                    self.state["cash_usdt"] -= alloc
                    self.state["open_positions"][sym] = {
                        "entry_time": now_str,
                        "entry_price": curr_price * (1 + self.slippage_pct / 100),
                        "quantity": alloc / (1 + self.fee_pct / 100) / (curr_price * (1 + self.slippage_pct / 100)),
                        "fee_pct": self.fee_pct,
                        "slippage_pct": self.slippage_pct,
                        "accounting_version": "net_costs_v1",
                        "size_usd": alloc,
                        "signal": entry_signal,
                        "universe_version": getattr(self, "universe_version", "fixed"),
                        "universe_as_of": getattr(self, "universe_as_of", None),
                        "strategy": STRATEGY,
                        "regime": regime,
                        "signal_candle": candle_id,
                        "stop_price": curr_price * (1 + self.slippage_pct / 100) * (1 - self.sl_pct / 100.0),
                        "highest_price": curr_price * (1 + self.slippage_pct / 100)
                    }
                    notifications.append(f"🚀 OPEN {sym} @ {curr_price:.4f} | Signal: {entry_signal}")
            except Exception:
                if not self.persist:
                    raise
                continue

        # Revalue all positions after closes and new entries.
        total_open_value = 0.0
        for sym, pos in self.state["open_positions"].items():
            try:
                latest = self.client.get_klines(sym, interval=timeframe, limit=2)
                mark = float(latest.iloc[-1]["Close"]) if not latest.empty else float(pos["entry_price"])
                pnl_pct = (mark - float(pos["entry_price"])) / float(pos["entry_price"]) * 100.0
                total_open_value += self.liquidation_value(pos, mark)
            except Exception:
                total_open_value += float(pos.get("size_usd", 0))
        self.state["equity"] = round(self.state["cash_usdt"] + total_open_value, 2)
        self._save_state()

        return {
            "summary": self.get_summary(timeframe=timeframe),
            "notifications": notifications
        }

    def _daily_loss_limit_hit(self) -> bool:
        today = self.clock().date()
        realized_today = 0.0
        for trade in self.state.get("history", []):
            try:
                if datetime.fromisoformat(trade["exit_time"]).date() == today:
                    realized_today += float(trade.get("pnl_usd", 0))
            except (KeyError, TypeError, ValueError):
                continue
        limit = float(self.state.get("initial_balance", self.init_balance)) * self.daily_loss_limit_pct / 100.0
        return realized_today <= -limit

    def _entries_allowed(self) -> bool:
        if not self.new_entries_enabled:
            return False
        if not self.persist:
            return True
        try:
            with open(self.control_file, encoding="utf-8") as handle:
                control = json.load(handle)
            return bool(control.get("paper_new_entries_enabled", False))
        except FileNotFoundError:
            return True
        except (OSError, ValueError, TypeError):
            return False

    @staticmethod
    def liquidation_value(pos, mark):
        """Estimated proceeds after sell slippage and fee; preserve legacy books."""
        if "quantity" in pos:
            return pos["quantity"] * mark * (1 - pos["slippage_pct"] / 100) * (1 - pos["fee_pct"] / 100)
        return pos["size_usd"] * mark / pos["entry_price"]

    def get_summary(self, refresh: bool = True, timeframe: str = "15m") -> Dict[str, Any]:
        """Return mark-to-market portfolio summary with realized/unrealized PnL."""
        init = self.state.get("initial_balance", 1000.0)
        cash = self.state.get("cash_usdt", 1000.0)
        open_pos = self.state.get("open_positions", {})
        history = self.state.get("history", [])

        # Win rate
        closed_trades = len(history)
        wins = [t for t in history if t["pnl_usd"] > 0]
        losses = [t for t in history if t["pnl_usd"] <= 0]
        win_rate = round((len(wins) / closed_trades * 100), 1) if closed_trades > 0 else 0.0

        total_realized_pnl = sum(float(t.get("pnl_usd", 0)) for t in history)
        marked_positions = []
        total_open_value = 0.0
        total_unrealized_pnl = 0.0
        for symbol, pos in open_pos.items():
            entry = float(pos.get("entry_price", 0))
            size = float(pos.get("size_usd", 0))
            mark = entry
            try:
                if refresh:
                    latest = self.client.get_klines(symbol, interval=timeframe, limit=2)
                    if not latest.empty:
                        mark = float(latest.iloc[-1]["Close"])
            except Exception:
                pass
            market_value = self.liquidation_value(pos, mark) if entry else size
            pnl_usd = market_value - size
            pnl_pct = pnl_usd / size * 100 if size else 0
            total_open_value += market_value
            total_unrealized_pnl += pnl_usd
            marked_positions.append({**pos, "mark_price": round(mark, 8), "pnl_pct": round(pnl_pct, 2), "pnl_usd": round(pnl_usd, 2), "market_value_usd": round(market_value, 2)})
        equity = round(cash + total_open_value, 2)
        net_return_pct = round(((equity - init) / init) * 100, 2)

        return {
            "profile": self.profile,
            "initial_balance": init,
            "cash_usdt": round(cash, 2),
            "equity": equity,
            "net_pnl_usd": round(equity - init, 2),
            "realized_pnl_usd": round(total_realized_pnl, 2),
            "unrealized_pnl_usd": round(total_unrealized_pnl, 2),
            "net_return_pct": net_return_pct,
            "open_positions_count": len(open_pos),
            "open_positions": {symbol: pos for symbol, pos in zip(open_pos.keys(), marked_positions)},
            "closed_trades_count": closed_trades,
            "win_rate_pct": win_rate,
            "history": history[-20:],
            "last_scan_time": self.state.get("last_scan_time", "-")
        }
