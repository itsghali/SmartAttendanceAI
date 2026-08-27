# Research-Grade Forex Backtesting — Results Report

Generated for pairs: EURUSD, GBPUSD, GBPJPY, AUDUSD  |  Timeframe: M30

**This run used SYNTHETIC data unless real CSVs were supplied — see data/synthetic.py and README. Treat all numbers below as a pipeline demonstration unless real market data was used.**


## 1. Strategy Performance (baseline config)

### Combined portfolio

- Net return: -95.10%  |  CAGR: -90.64%
- Max drawdown: -95.10%  |  Sharpe: -4.85  |  Sortino: -6.19  |  Calmar: -0.95
- Trades: 446  |  Win rate: 21.30%  |  Profit factor: 0.39  |  Expectancy: -213.23  |  Avg R: -0.658
- Best / worst trade: 5,115.52 / -1,979.09
- Max winning streak: 4  |  Max losing streak: 18
- Avg holding: 13.7 bars (6.8h)  |  Median holding: 7.0 bars


**Is historical expectancy positive?** NO (expectancy = -213.23 USD/trade).


## 2. Pair Comparison

| Pair   |   Trades |   Win Rate % |   Profit Factor |   Expectancy |   Net Return % |   Max DD % |   Sharpe |   Avg R |
|:-------|---------:|-------------:|----------------:|-------------:|---------------:|-----------:|---------:|--------:|
| EURUSD |       91 |        17.58 |            0.38 |      -519.8  |         -47.3  |     -47.7  |    -2.64 |  -0.689 |
| GBPUSD |      109 |        25.69 |            0.54 |      -362.86 |         -39.55 |     -39.97 |    -1.69 |  -0.442 |
| GBPJPY |      117 |        21.37 |            0.34 |      -543.17 |         -63.55 |     -64.69 |    -3.14 |  -0.842 |
| AUDUSD |      129 |        20.16 |            0.44 |      -449.76 |         -58.02 |     -58.02 |    -2.73 |  -0.656 |



**Best pair (by expectancy):** GBPUSD. **Worst pair:** GBPJPY.

**Trade concentration:** the busiest pair accounts for 28.92% of all trades across the four pairs — trade count is reasonably spread across pairs.


## 3. SL Analysis: 15 pips vs 20 pips

|   max_sl_pips |   n_trades |   win_rate_pct |   profit_factor |   expectancy |   net_return_pct |   max_drawdown_pct |   sharpe_ratio |   avg_r_multiple |   max_losing_streak |
|--------------:|-----------:|---------------:|----------------:|-------------:|-----------------:|-------------------:|---------------:|-----------------:|--------------------:|
|            15 |        436 |          20.64 |            0.39 |      -218.42 |           -95.23 |             -95.23 |          -4.94 |           -0.68  |                  18 |
|            20 |        446 |          21.3  |            0.39 |      -213.23 |           -95.1  |             -95.1  |          -4.85 |           -0.658 |                  18 |



- Trades available at 15 pips: 436; at 20 pips: 446 (10 additional trades become available).

- By expectancy, the **20-pip** limit performs better in this run (-218.42 vs -213.23 USD/trade). This is a single historical sample — do not treat this as proof either limit dominates.


## 4. Robustness


### 4a. Transaction cost sensitivity

|   cost_multiplier |   n_trades |   net_return_pct |   expectancy |   profit_factor |   max_drawdown_pct |
|------------------:|-----------:|-----------------:|-------------:|----------------:|-------------------:|
|               0   |        446 |           -75.95 |      -170.3  |            0.62 |             -75.95 |
|               1   |        446 |           -95.1  |      -213.23 |            0.39 |             -95.1  |
|               1.5 |        446 |           -97.78 |      -219.24 |            0.32 |             -97.78 |
|               2   |        446 |           -98.99 |      -221.95 |            0.26 |             -98.99 |



### 4b. Parameter sensitivity


**max_sl_pips x min_rr**


|   max_sl_pips |   min_rr |   n_trades |   win_rate_pct |   profit_factor |   expectancy |   net_return_pct |   max_drawdown_pct |   sharpe_ratio |   avg_r_multiple |
|--------------:|---------:|-----------:|---------------:|----------------:|-------------:|-----------------:|-------------------:|---------------:|-----------------:|
|            15 |      1   |        436 |          20.64 |            0.39 |      -218.42 |           -95.23 |             -95.23 |          -4.94 |           -0.68  |
|            15 |      1.5 |        384 |          18.23 |            0.39 |      -243.7  |           -93.58 |             -93.58 |          -4.44 |           -0.696 |
|            15 |      2   |        347 |          16.43 |            0.39 |      -265.55 |           -92.15 |             -92.15 |          -4.26 |           -0.713 |
|            20 |      1   |        446 |          21.3  |            0.39 |      -213.23 |           -95.1  |             -95.1  |          -4.85 |           -0.658 |
|            20 |      1.5 |        390 |          18.46 |            0.39 |      -239.78 |           -93.51 |             -93.51 |          -4.41 |           -0.682 |
|            20 |      2   |        352 |          16.48 |            0.39 |      -261.69 |           -92.11 |             -92.11 |          -4.22 |           -0.701 |



**displacement_min_atr_multiplier**


|   displacement_min_atr_multiplier |   n_trades |   win_rate_pct |   profit_factor |   expectancy |   net_return_pct |   max_drawdown_pct |   sharpe_ratio |   avg_r_multiple |
|----------------------------------:|-----------:|---------------:|----------------:|-------------:|-----------------:|-------------------:|---------------:|-----------------:|
|                               1   |        833 |          21.13 |            0.38 |      -119.58 |           -99.59 |             -99.61 |          -5.55 |           -0.647 |
|                               1.5 |        446 |          21.3  |            0.39 |      -213.23 |           -95.1  |             -95.1  |          -4.85 |           -0.658 |
|                               2   |        253 |          22.53 |            0.42 |      -317.4  |           -80.3  |             -80.3  |          -3.66 |           -0.624 |



**swing_lookback**


|   swing_lookback |   n_trades |   win_rate_pct |   profit_factor |   expectancy |   net_return_pct |   max_drawdown_pct |   sharpe_ratio |   avg_r_multiple |
|-----------------:|-----------:|---------------:|----------------:|-------------:|-----------------:|-------------------:|---------------:|-----------------:|
|                3 |        558 |          20.79 |            0.38 |      -175.07 |           -97.66 |             -97.66 |          -5.62 |           -0.657 |
|                5 |        446 |          21.3  |            0.39 |      -213.23 |           -95.1  |             -95.1  |          -4.85 |           -0.658 |
|                8 |        343 |          22.16 |            0.47 |      -257.78 |           -88.42 |             -88.42 |          -3.9  |           -0.61  |



**sl_buffer_atr_multiplier**


|   sl_buffer_atr_multiplier |   n_trades |   win_rate_pct |   profit_factor |   expectancy |   net_return_pct |   max_drawdown_pct |   sharpe_ratio |   avg_r_multiple |
|---------------------------:|-----------:|---------------:|----------------:|-------------:|-----------------:|-------------------:|---------------:|-----------------:|
|                       0.05 |        467 |          20.99 |            0.38 |      -205.97 |           -96.19 |             -96.19 |          -4.88 |           -0.681 |
|                       0.1  |        446 |          21.3  |            0.39 |      -213.23 |           -95.1  |             -95.1  |          -4.85 |           -0.658 |
|                       0.2  |        420 |          21.67 |            0.4  |      -221.15 |           -92.88 |             -92.88 |          -4.61 |           -0.612 |



Flag for overfitting per section 34: look for isolated spikes in the tables above — a single narrow combination performing far better than every neighboring combination is a red flag, not a discovery.


### 4c. Out-of-sample


**EURUSD** (in-sample / out-of-sample split at 2021-10-11 00:00:00)


In-sample:


- Net return: -28.31%  |  CAGR: -35.62%
- Max drawdown: -28.85%  |  Sharpe: -2.28  |  Sortino: -3.01  |  Calmar: -1.23
- Trades: 53  |  Win rate: 16.98%  |  Profit factor: 0.44  |  Expectancy: -534.08  |  Avg R: -0.612
- Best / worst trade: 4,665.70 / -1,483.90
- Max winning streak: 2  |  Max losing streak: 19
- Avg holding: 19.3 bars (9.6h)  |  Median holding: 9.0 bars


Out-of-sample:


- Net return: -26.49%  |  CAGR: -21.56%
- Max drawdown: -26.49%  |  Sharpe: -1.99  |  Sortino: -1.07  |  Calmar: -0.81
- Trades: 38  |  Win rate: 18.42%  |  Profit factor: 0.28  |  Expectancy: -697.18  |  Avg R: -0.798
- Best / worst trade: 3,294.33 / -1,496.53
- Max winning streak: 2  |  Max losing streak: 18
- Avg holding: 11.8 bars (5.9h)  |  Median holding: 5.5 bars


Out-of-sample expectancy is LOWER than in-sample (-697.18 vs -534.08).


**GBPUSD** (in-sample / out-of-sample split at 2021-10-11 00:00:00)


In-sample:


- Net return: -35.03%  |  CAGR: -43.37%
- Max drawdown: -35.34%  |  Sharpe: -2.68  |  Sortino: -2.71  |  Calmar: -1.23
- Trades: 60  |  Win rate: 20.00%  |  Profit factor: 0.38  |  Expectancy: -583.81  |  Avg R: -0.703
- Best / worst trade: 3,278.02 / -2,049.56
- Max winning streak: 2  |  Max losing streak: 12
- Avg holding: 8.3 bars (4.2h)  |  Median holding: 5.0 bars


Out-of-sample:


- Net return: -6.96%  |  CAGR: -5.52%
- Max drawdown: -11.35%  |  Sharpe: -0.31  |  Sortino: -0.38  |  Calmar: -0.49
- Trades: 49  |  Win rate: 32.65%  |  Profit factor: 0.85  |  Expectancy: -142.13  |  Avg R: -0.123
- Best / worst trade: 9,523.65 / -1,796.95
- Max winning streak: 2  |  Max losing streak: 8
- Avg holding: 13.1 bars (6.6h)  |  Median holding: 6.0 bars


Out-of-sample expectancy is similar or higher than in-sample (-142.13 vs -583.81).


**GBPJPY** (in-sample / out-of-sample split at 2021-10-11 00:00:00)


In-sample:


- Net return: -48.79%  |  CAGR: -58.88%
- Max drawdown: -49.73%  |  Sharpe: -3.37  |  Sortino: -4.02  |  Calmar: -1.18
- Trades: 75  |  Win rate: 22.67%  |  Profit factor: 0.32  |  Expectancy: -650.50  |  Avg R: -0.872
- Best / worst trade: 6,335.38 / -2,188.18
- Max winning streak: 4  |  Max losing streak: 15
- Avg holding: 12.1 bars (6.0h)  |  Median holding: 7.0 bars


Out-of-sample:


- Net return: -28.84%  |  CAGR: -23.85%
- Max drawdown: -31.06%  |  Sharpe: -1.73  |  Sortino: -1.06  |  Calmar: -0.77
- Trades: 42  |  Win rate: 19.05%  |  Profit factor: 0.39  |  Expectancy: -686.65  |  Avg R: -0.789
- Best / worst trade: 4,101.21 / -1,976.90
- Max winning streak: 2  |  Max losing streak: 10
- Avg holding: 16.1 bars (8.0h)  |  Median holding: 8.0 bars


Out-of-sample expectancy is LOWER than in-sample (-686.65 vs -650.50).


**AUDUSD** (in-sample / out-of-sample split at 2021-10-11 00:00:00)


In-sample:


- Net return: -30.09%  |  CAGR: -37.63%
- Max drawdown: -31.68%  |  Sharpe: -2.06  |  Sortino: -2.52  |  Calmar: -1.19
- Trades: 67  |  Win rate: 23.88%  |  Profit factor: 0.48  |  Expectancy: -449.12  |  Avg R: -0.518
- Best / worst trade: 4,378.46 / -1,579.00
- Max winning streak: 3  |  Max losing streak: 9
- Avg holding: 11.9 bars (5.9h)  |  Median holding: 5.0 bars


Out-of-sample:


- Net return: -39.95%  |  CAGR: -33.01%
- Max drawdown: -43.86%  |  Sharpe: -2.24  |  Sortino: -1.73  |  Calmar: -0.75
- Trades: 62  |  Win rate: 16.13%  |  Profit factor: 0.37  |  Expectancy: -644.41  |  Avg R: -0.804
- Best / worst trade: 6,106.63 / -2,442.13
- Max winning streak: 3  |  Max losing streak: 12
- Avg holding: 17.8 bars (8.9h)  |  Median holding: 8.0 bars


Out-of-sample expectancy is LOWER than in-sample (-644.41 vs -449.12).


### 4d. Walk-forward


**EURUSD** — 12 walk-forward window(s)


- Net return: -43.68%  |  CAGR: -36.42%
- Max drawdown: -43.68%  |  Sharpe: -2.89  |  Sortino: -2.26  |  Calmar: -0.83
- Trades: 67  |  Win rate: 14.93%  |  Profit factor: 0.25  |  Expectancy: -651.95  |  Avg R: -0.845
- Best / worst trade: 3,333.38 / -1,529.95
- Max winning streak: 2  |  Max losing streak: 19
- Avg holding: 15.8 bars (7.9h)  |  Median holding: 7.0 bars


2/12 windows were net profitable.


**GBPUSD** — 12 walk-forward window(s)


- Net return: -22.51%  |  CAGR: -18.19%
- Max drawdown: -22.67%  |  Sharpe: -0.92  |  Sortino: -1.04  |  Calmar: -0.80
- Trades: 81  |  Win rate: 28.40%  |  Profit factor: 0.69  |  Expectancy: -277.96  |  Avg R: -0.293
- Best / worst trade: 7,934.02 / -2,188.26
- Max winning streak: 2  |  Max losing streak: 11
- Avg holding: 10.5 bars (5.3h)  |  Median holding: 6.0 bars


4/12 windows were net profitable.


**GBPJPY** — 12 walk-forward window(s)


- Net return: -51.79%  |  CAGR: -44.26%
- Max drawdown: -53.29%  |  Sharpe: -2.72  |  Sortino: -2.72  |  Calmar: -0.83
- Trades: 92  |  Win rate: 22.83%  |  Profit factor: 0.37  |  Expectancy: -562.96  |  Avg R: -0.775
- Best / worst trade: 3,955.60 / -2,388.49
- Max winning streak: 4  |  Max losing streak: 15
- Avg holding: 13.7 bars (6.8h)  |  Median holding: 7.0 bars


1/12 windows were net profitable.


**AUDUSD** — 12 walk-forward window(s)


- Net return: -47.73%  |  CAGR: -39.93%
- Max drawdown: -47.73%  |  Sharpe: -2.21  |  Sortino: -2.25  |  Calmar: -0.84
- Trades: 102  |  Win rate: 21.57%  |  Profit factor: 0.48  |  Expectancy: -467.96  |  Avg R: -0.619
- Best / worst trade: 5,314.72 / -2,125.72
- Max winning streak: 3  |  Max losing streak: 12
- Avg holding: 15.1 bars (7.6h)  |  Median holding: 6.5 bars


3/12 windows were net profitable.


## 5. Strategy-Specific Statistics


**EURUSD**: 200 demand zones, 196 supply zones, 2785 retests detected.


**GBPUSD**: 208 demand zones, 188 supply zones, 2623 retests detected.


**GBPJPY**: 213 demand zones, 193 supply zones, 2579 retests detected.


**AUDUSD**: 215 demand zones, 212 supply zones, 3059 retests detected.


**EURUSD** setups: 211 valid, 589 rejected (SL too large: 59, MA200 wrong side: 530, RR insufficient: 162). BUY trades: 40, SELL trades: 51.


**GBPUSD** setups: 202 valid, 536 rejected (SL too large: 66, MA200 wrong side: 460, RR insufficient: 189). BUY trades: 46, SELL trades: 63.


**GBPJPY** setups: 228 valid, 496 rejected (SL too large: 59, MA200 wrong side: 435, RR insufficient: 128). BUY trades: 47, SELL trades: 70.


**AUDUSD** setups: 281 valid, 575 rejected (SL too large: 88, MA200 wrong side: 475, RR insufficient: 206). BUY trades: 63, SELL trades: 66.


## 6. Critical Research Principle

This report intentionally evaluates the FULL risk/return profile (drawdown, Sharpe, Sortino, Calmar, streaks) alongside raw return, and separately reports in-sample vs out-of-sample and walk-forward performance, because net profit alone is not evidence of edge. A historical backtest — on synthetic OR real data — never proves future profitability; it only provides evidence for or against a historical edge under the stated, fixed, non-optimized rules.
