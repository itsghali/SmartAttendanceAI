"""Trade record (section 37 of the spec)."""
from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd


@dataclass
class Trade:
    pair: str
    timestamp: pd.Timestamp          # entry timestamp
    direction: str                    # BUY | SELL
    zone_type: str                     # DEMAND | SUPPLY
    zone_high: float
    zone_low: float
    entry: float                       # cost-adjusted fill price
    stop_loss: float
    take_profit: float
    sl_pips: float
    tp_pips: float
    initial_rr: float
    ma200_at_entry: float
    atr_at_entry: float
    position_size_lots: float
    risk_amount: float
    spread_pips: float
    slippage_pips: float
    exit_timestamp: pd.Timestamp | None = None
    exit_price: float | None = None
    exit_reason: str | None = None
    pnl: float | None = None
    r_multiple: float | None = None
    equity_after: float | None = None
    holding_bars: int | None = None

    def to_dict(self) -> dict:
        d = dict(self.__dict__)
        return d
