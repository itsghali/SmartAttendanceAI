# Research-Grade Forex Backtesting System

A fully automated, rule-based, deterministic backtesting system for a
**Supply & Demand + MA200** Forex strategy on M30 candles, covering
EUR/USD, GBP/USD, GBP/JPY, and AUD/USD.

The goal of this project is **not** to produce an impressive-looking
backtest. It is to build a reproducible, look-ahead-free system that lets
the historical data itself answer the question: does this specific,
mathematically-defined rule set show evidence of a historical edge?

> **No real market data is bundled.** This environment has no access to a
> real Forex data vendor. `main.py` will auto-generate a reproducible
> **synthetic** M30 dataset (`data/synthetic.py`) for any pair whose CSV is
> missing under `data/raw/`, purely so the full pipeline is runnable and
> testable end to end. Every number in `outputs/reports/research_report.md`
> produced from that synthetic data is a **pipeline demonstration only** —
> it has no evidentiary value about the real strategy's edge. To do actual
> research, drop real M30 OHLC CSVs into `data/raw/` (see "Data format"
> below) and re-run `main.py`.

---

## 1. Mathematical Specification of the Supply/Demand Algorithm

This is the core deliverable requested before any code: a precise,
deterministic definition with every ambiguity resolved explicitly.

### 1.1 Swing points (`zones/swings.py`)

With `SWING_LOOKBACK = k`:

```
candle i is a RAW swing high  iff  high[i] > high[j] for all j in [i-k, i-1]
                              and  high[i] > high[j] for all j in [i+1, i+k]
candle i is a RAW swing low   iff  low[i]  < low[j]  for all j in [i-k, i-1]
                              and  low[i]  < low[j]  for all j in [i+1, i+k]
```

Strict inequality on both sides — a tie does not qualify (deterministic,
avoids an arbitrary tie-break rule the spec never mentions).

**No-look-ahead rule:** a swing at index `i` cannot be *known* until candle
`i+k` has closed (we need the `k` right-hand candles to exist). Every raw
swing therefore carries `confirmed_at = i + k`, and the strategy is only
ever allowed to consult swings with `confirmed_at <= current_index`
(`zones/swings.py::SwingRegistry`).

### 1.2 Base candle

A candle `j` is a **base candle** iff its range is below the prevailing
volatility:

```
(high[j] - low[j]) < ATR[j]
```

*Resolved ambiguity:* the spec explicitly forbids subjective terms like
"tight" or "clean" consolidation. Anchoring "quiet" to the same ATR
yardstick used for displacement keeps the whole algorithm on one
consistent, configurable scale, with no separate unconfigured threshold.

### 1.3 Base

Immediately before a candidate displacement candle at index `i`, walk
backwards from `i-1` and collect the maximal contiguous run of base
candles. If `i-1` itself is not a base candle, there is **no base** and no
zone can be created from displacement at `i`. If the run is longer than
`BASE_MAX_CANDLES`, only the `BASE_MAX_CANDLES` candles closest to `i` are
kept (a base must stay "small", per spec).

### 1.4 Displacement

At candidate index `i`, for a **bullish** (Demand) displacement:

```
close[i] > open[i]
(high[i] - low[i]) >= ATR[i] * DISPLACEMENT_MIN_ATR_MULTIPLIER
```

Bearish (Supply) displacement is the exact mirror image:
`close[i] < open[i]` and the same range condition.

### 1.5 Structure break

The displacement candle's close must break a **previously confirmed**
swing point (see 1.1):

```
Demand: close[i] > price of the most recently confirmed swing HIGH as of i
Supply: close[i] < price of the most recently confirmed swing LOW  as of i
```

### 1.6 Zone boundaries

Derived **only** from the base candles (never the displacement candle),
identically for both zone types:

```
upper boundary = max(high) over the base candles
lower boundary = min(low)  over the base candles
```

A zone's boundaries are immutable once created — only its **lifecycle
state** changes afterward (`zones/lifecycle.py`).

### 1.7 Zone lifecycle

```
CREATED -> ACTIVE -> TESTED -> INVALIDATED
                  \-> EXPIRED        (only from ACTIVE, i.e. never tested)
```

- A zone becomes tradeable (`ACTIVE`) starting the candle **after** the
  displacement candle — the displacement candle's own close is what
  confirms the zone and cannot simultaneously retest it.
- **Interaction:** `candle.low <= zone.upper AND candle.high >= zone.lower`
  (identical test for Demand and Supply — see spec section 10).
- **Invalidation:** Demand invalid when a candle **closes** below
  `lower - ATR_now * ZONE_INVALIDATION_BUFFER_ATR`; Supply invalid when a
  candle **closes** above `upper + ATR_now * ZONE_INVALIDATION_BUFFER_ATR`.
  `ATR_now` is the ATR of the candle being evaluated, i.e. information
  available at that candle's own close — never a future or past-frozen ATR.
  Once `INVALIDATED`, a zone can never again produce a signal.
- **Expiry:** *(resolved ambiguity — the spec names the `EXPIRED` state but
  never gives a threshold)* a zone that is never tested within
  `ZONE_MAX_AGE_BARS` (config, default 500) candles of its creation expires
  and can no longer trade. A zone that has been tested at least once does
  not expire by age — it is only removed from play by invalidation.

### 1.8 Confirmation candle

*Resolved ambiguity:* the spec does not say how many bars after the first
interaction confirmation may occur on. We define the confirmation candle to
be the **same candle** that interacts with the zone — the simplest
deterministic reading, and it avoids inventing an unconfigured
"confirmation window" parameter the spec never mentions.

```
Demand (-> BUY):  interacts AND close > open   AND close > zone.upper
Supply (-> SELL): interacts AND close < open   AND close < zone.lower
```

If a candle interacts but does not confirm, the zone stays alive
(ACTIVE/TESTED) for a future candle to attempt confirmation.

### 1.9 Structural stop loss

```
BUY  (Demand): SL = zone.lower - ATR_at_confirmation * SL_BUFFER_ATR_MULTIPLIER
SELL (Supply): SL = zone.upper + ATR_at_confirmation * SL_BUFFER_ATR_MULTIPLIER
```

Never moved closer to price to satisfy the max-pip filter — if it is too
wide, the trade is rejected outright (never resized, never placed inside
the zone).

### 1.10 Entry, filters, and the "entry price" ambiguity

Entry is mechanically the **next candle's open** after confirmation
(never the confirmation candle's close). The max-SL-pips filter, the
MA200-direction filter, and the RR filter all reference "the entry price" —
but the entry price is only known once the next candle actually opens.

*Resolved ambiguity:* these filters are evaluated on the **realized**
next-open (the theoretical, cost-free fill), not on some estimate made at
confirmation time. This is not look-ahead: no additional trading decision
is made using information beyond what a live market order at the next open
would realize — the entry rule already unconditionally commits to that
price; the filters simply decide, after the fact, whether the resulting
setup was valid, exactly as a disciplined live trader would.

Filters (evaluated independently, **not** short-circuited, so a rejected
setup can carry more than one simultaneous reason — this keeps the
research statistics in section 27 undistorted by an arbitrary priority
order):

```
SL_distance_pips = |entry - SL| / pip_size   <= MAX_SL_PIPS   ?
TP (== MA200 at confirmation, frozen)  on the correct side of entry ?
RR = |TP - entry| / |entry - SL|             >= MIN_RR        ?
```

### 1.11 Take profit

TP is the MA200 value **frozen at the confirmation candle's close** — it is
never recalculated as MA200 subsequently moves (spec section 4's worked
example is a unit test: `tests/test_take_profit.py`).

### 1.12 Transaction costs

*Resolved ambiguity:* the full configured spread is charged once, on entry
(cross the spread to open); slippage is applied on both entry and exit
(execution uncertainty on any market order); commission is a flat
USD-per-standard-lot round-turn charge. All three are deliberately kept
**out** of the signal-validity filters above, so "is there a structural
edge" and "does it survive realistic costs" are reported separately
(exactly what spec section 20's cost-sensitivity requirement is asking
for).

### 1.13 Position sizing / pip value

Standard-lot pip value is `pip_size * lot_size` in the pair's quote
currency. For the three USD-quoted pairs (EUR/USD, GBP/USD, AUD/USD) that
is already USD. For GBP/JPY, the JPY pip value is converted to USD via a
configurable `usdjpy_conversion_rate` (default 150.0).

*Resolved ambiguity / known limitation:* this system does not ingest a
USD/JPY price series (it is not one of the four traded pairs), so the
conversion rate is a fixed, configurable approximation rather than a
live cross rate. **This same conversion factor must be, and is, applied
identically to realized trade P&L** — a real bug caught during development
(see `tests/test_jpy_pnl_conversion.py`) was GBP/JPY P&L being computed in
JPY and credited straight to USD equity unconverted, inflating results by
~100x. If a live USD/JPY feed becomes available, replace
`risk.position_sizing.quote_to_usd_factor` with a live lookup.

### 1.14 Same-candle SL/TP ambiguity

OHLC alone cannot tell you which of SL/TP was touched first if both fall
inside one candle's range. `SAME_CANDLE_POLICY` (config) resolves this:
`SL_FIRST` (conservative baseline) or `TP_FIRST` (optimistic upper bound).
Both are run and compared for robustness.

---

## 2. Project layout

```
forex_strategy/
├── config.yaml              # every numeric assumption, in one place
├── main.py                  # orchestrates the full pipeline, end to end
├── data/                    # CSV loader, validator, synthetic generator
├── indicators/               # ATR (Wilder), SMA200 — both causal
├── zones/                    # swings, lifecycle, supply/demand detector
├── strategy/                 # confirmation predicates, signal generation
├── risk/                     # SL, TP, RR, pip math, position sizing
├── execution/                 # transaction costs, bar-by-bar exit simulator
├── backtest/                  # engine, portfolio, sensitivity, IS/OOS, WF
├── analysis/                  # metrics, trade log CSVs, report generator
├── visualization/              # equity/drawdown curves, annotated trade charts
├── tests/                     # unit tests (see section 4 below)
└── outputs/                   # everything main.py produces (see section 5)
```

## 3. Running it

```bash
cd forex_strategy
pip install -r requirements.txt
python main.py            # full pipeline: baseline + SL 15/20 + cost
                           # sensitivity + parameter sensitivity + IS/OOS +
                           # walk-forward + charts + final report
pytest tests/ -q           # 40+ unit tests
```

### Data format

Drop CSVs at the paths configured in `config.yaml` (`pairs.<PAIR>.file`),
with columns `timestamp, open, high, low, close[, volume]`. They are
validated on load (`data/validator.py`) for missing/duplicate timestamps,
non-monotonic ordering, invalid OHLC relationships, missing values, and
timezone consistency; large gaps (e.g. weekends) are reported as warnings,
not treated as errors.

## 4. Unit tests

Each item required by the spec has a dedicated test:

| Requirement | File |
|---|---|
| MA200 uses only historical data | `test_ma.py` |
| Swings confirmed only once enough candles exist | `test_swings.py` |
| Valid/invalid Demand zones | `test_demand.py` |
| Valid/invalid Supply zones | `test_supply.py` |
| Entry: Demand+confirm+MA200 above -> BUY, Supply+confirm+MA200 below -> SELL | `test_entry.py` |
| SL: BUY SL < Demand zone, SELL SL > Supply zone | `test_stop_loss.py` |
| Max SL: SL > 15/20 pips -> rejected (spec's own worked example) | `test_max_sl.py` |
| TP: frozen MA200 at entry | `test_take_profit.py` |
| RR: below minimum -> rejected | `test_risk_reward.py` |
| Position sizing: risk correctly calculated per pair | `test_position_sizing.py` |
| Same-candle SL/TP policy | `test_simulator.py` |
| Data validation | `test_validator.py` |
| GBP/JPY currency conversion regression | `test_jpy_pnl_conversion.py` |

## 5. Outputs (`outputs/`)

- `trade_logs/<PAIR>_trades.csv`, `<PAIR>_rejected.csv`, `PORTFOLIO_trades.csv`
  — every field in spec section 37, plus rejected setups with their reasons.
- `equity_curves/<PAIR>_equity.png`, `PORTFOLIO_equity.png`, `ALL_equity.png`
  — equity + drawdown curves per pair, portfolio, and combined.
- `charts/*.png` — annotated trade charts (zone, MA200, entry, SL, TP,
  exit) for winners, losers, AND setups rejected for exceeding the max-SL
  filter — auditability, not a highlight reel.
- `reports/research_report.md` — the automated report answering every
  question in spec section 39: strategy performance, pair analysis, SL
  15-vs-20 analysis, transaction-cost / parameter-sensitivity /
  out-of-sample / walk-forward robustness checks, and the strategy-specific
  rejection statistics from section 27.

## 6. Reading the results responsibly

Per spec sections 34/40, this system deliberately does **not** optimize for
maximum net profit. `config.yaml`'s values are fixed a priori and are never
tuned against the full-period result. The report evaluates the whole
risk/return profile (drawdown, Sharpe, Sortino, Calmar, streaks), reports
in-sample vs out-of-sample and walk-forward performance separately, and
flags when a result looks concentrated in one pair or one narrow parameter
combination. **A historical backtest — on synthetic or real data — never
proves future profitability.** It only provides evidence for or against a
historical edge under a fixed, non-optimized rule set.
