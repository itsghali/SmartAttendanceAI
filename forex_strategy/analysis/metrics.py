"""Performance metrics (section 26).

Sharpe/Sortino/Calmar/CAGR/max-drawdown are computed from a daily-resampled,
forward-filled equity curve (the trade-event equity curve is irregular in
time, so a calendar-day resample is the standard, defensible way to
annualize). Everything else is computed directly from the trade list.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict

import numpy as np
import pandas as pd

from backtest.trade import Trade

TRADING_DAYS_PER_YEAR = 252


@dataclass
class PerformanceMetrics:
    initial_capital: float
    final_capital: float
    net_profit: float
    net_return_pct: float
    cagr_pct: float

    max_drawdown: float
    max_drawdown_pct: float
    sharpe_ratio: float
    sortino_ratio: float
    calmar_ratio: float

    n_trades: int
    n_winners: int
    n_losers: int
    win_rate_pct: float
    avg_winner: float
    avg_loser: float
    profit_factor: float
    expectancy: float
    avg_r_multiple: float
    best_trade: float
    worst_trade: float

    max_winning_streak: int
    max_losing_streak: int

    avg_holding_bars: float
    median_holding_bars: float

    def to_dict(self) -> dict:
        return asdict(self)


def _daily_equity(equity_curve: pd.Series) -> pd.Series:
    if len(equity_curve) < 2:
        return equity_curve
    daily = equity_curve.resample("1D").last().ffill()
    return daily


def _max_drawdown(equity: pd.Series) -> tuple[float, float]:
    running_max = equity.cummax()
    dd = equity - running_max
    dd_pct = dd / running_max.replace(0, np.nan)
    return float(dd.min()) if len(dd) else 0.0, float(dd_pct.min() * 100) if len(dd_pct) else 0.0


def _streaks(trades: list[Trade]) -> tuple[int, int]:
    max_win, max_loss, cur_win, cur_loss = 0, 0, 0, 0
    for t in trades:
        if t.pnl is None:
            continue
        if t.pnl > 0:
            cur_win += 1
            cur_loss = 0
        elif t.pnl < 0:
            cur_loss += 1
            cur_win = 0
        else:
            cur_win = cur_loss = 0
        max_win = max(max_win, cur_win)
        max_loss = max(max_loss, cur_loss)
    return max_win, max_loss


def compute_metrics(trades: list[Trade], equity_curve: pd.Series, initial_capital: float) -> PerformanceMetrics:
    trades_sorted = sorted(trades, key=lambda t: t.timestamp)
    final_capital = float(equity_curve.iloc[-1]) if len(equity_curve) else initial_capital
    net_profit = final_capital - initial_capital
    net_return_pct = (net_profit / initial_capital) * 100 if initial_capital else 0.0

    daily = _daily_equity(equity_curve)
    if len(daily) >= 2:
        days = (daily.index[-1] - daily.index[0]).days
        years = max(days / 365.25, 1 / 365.25)
        if initial_capital > 0 and final_capital > 0:
            cagr = ((final_capital / initial_capital) ** (1 / years) - 1) * 100
        else:
            cagr = -100.0  # equity wiped out or worse
        daily_returns = daily.pct_change().dropna()
    else:
        cagr = 0.0
        daily_returns = pd.Series(dtype=float)

    max_dd, max_dd_pct = _max_drawdown(daily if len(daily) else equity_curve)

    if len(daily_returns) > 1 and daily_returns.std() > 0:
        sharpe = float(daily_returns.mean() / daily_returns.std() * np.sqrt(TRADING_DAYS_PER_YEAR))
    else:
        sharpe = 0.0

    downside = daily_returns[daily_returns < 0]
    if len(downside) > 1 and downside.std() > 0:
        sortino = float(daily_returns.mean() / downside.std() * np.sqrt(TRADING_DAYS_PER_YEAR))
    else:
        sortino = 0.0

    calmar = float(cagr / abs(max_dd_pct)) if max_dd_pct != 0 else 0.0

    pnls = [t.pnl for t in trades_sorted if t.pnl is not None]
    r_multiples = [t.r_multiple for t in trades_sorted if t.r_multiple is not None and t.r_multiple == t.r_multiple]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]

    n_trades = len(pnls)
    win_rate = (len(wins) / n_trades * 100) if n_trades else 0.0
    avg_winner = float(np.mean(wins)) if wins else 0.0
    avg_loser = float(np.mean(losses)) if losses else 0.0
    gross_win = sum(wins)
    gross_loss = abs(sum(losses))
    profit_factor = (gross_win / gross_loss) if gross_loss > 0 else (float("inf") if gross_win > 0 else 0.0)
    expectancy = float(np.mean(pnls)) if pnls else 0.0
    avg_r = float(np.mean(r_multiples)) if r_multiples else 0.0
    best_trade = max(pnls) if pnls else 0.0
    worst_trade = min(pnls) if pnls else 0.0

    max_win_streak, max_loss_streak = _streaks(trades_sorted)

    holding = [t.holding_bars for t in trades_sorted if t.holding_bars is not None]
    avg_holding = float(np.mean(holding)) if holding else 0.0
    median_holding = float(np.median(holding)) if holding else 0.0

    return PerformanceMetrics(
        initial_capital=initial_capital,
        final_capital=final_capital,
        net_profit=net_profit,
        net_return_pct=net_return_pct,
        cagr_pct=cagr,
        max_drawdown=max_dd,
        max_drawdown_pct=max_dd_pct,
        sharpe_ratio=sharpe,
        sortino_ratio=sortino,
        calmar_ratio=calmar,
        n_trades=n_trades,
        n_winners=len(wins),
        n_losers=len(losses),
        win_rate_pct=win_rate,
        avg_winner=avg_winner,
        avg_loser=avg_loser,
        profit_factor=profit_factor,
        expectancy=expectancy,
        avg_r_multiple=avg_r,
        best_trade=best_trade,
        worst_trade=worst_trade,
        max_winning_streak=max_win_streak,
        max_losing_streak=max_loss_streak,
        avg_holding_bars=avg_holding,
        median_holding_bars=median_holding,
    )
