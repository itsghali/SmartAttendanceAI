"""Simple Moving Average used as the strategy's static take-profit target.

sma200[i] = mean(close[i-199 .. i])   (the 200 most recent CLOSED candles as
of the close of candle i). It is NaN until 200 candles exist (i >= 199),
enforcing that no trade can reference an MA200 value computed from an
incomplete window.
"""
from __future__ import annotations

import pandas as pd


def sma(df: pd.DataFrame, period: int = 200, column: str = "close") -> pd.Series:
    return df[column].rolling(window=period, min_periods=period).mean()
