"""CSV persistence for trades and rejected setups (section 37)."""
from __future__ import annotations

import pandas as pd

from backtest.trade import Trade
from strategy.signals import SetupOutcome


def trades_to_dataframe(trades: list[Trade]) -> pd.DataFrame:
    rows = [t.to_dict() for t in trades]
    return pd.DataFrame(rows)


def save_trades_csv(trades: list[Trade], path: str) -> None:
    df = trades_to_dataframe(trades)
    df.to_csv(path, index=False)


def rejected_setups_to_dataframe(setups: list[SetupOutcome]) -> pd.DataFrame:
    rows = []
    for s in setups:
        rows.append(
            {
                "pair": s.pair,
                "direction": s.direction,
                "zone_type": s.zone.zone_type.value,
                "zone_high": s.zone.upper,
                "zone_low": s.zone.lower,
                "confirmation_timestamp": s.confirmation_timestamp,
                "entry_timestamp": s.entry_timestamp,
                "raw_entry": s.raw_entry,
                "sl": s.sl,
                "tp": s.tp,
                "sl_pips": s.sl_pips,
                "tp_pips": s.tp_pips,
                "rr": s.rr,
                "atr_at_confirmation": s.atr_at_confirmation,
                "ma200_at_confirmation": s.ma200_at_confirmation,
                "rejection_reasons": ";".join(r.value for r in s.rejection_reasons),
            }
        )
    return pd.DataFrame(rows)


def save_rejected_setups_csv(setups: list[SetupOutcome], path: str) -> None:
    df = rejected_setups_to_dataframe(setups)
    df.to_csv(path, index=False)
