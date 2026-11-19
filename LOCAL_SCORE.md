# LOCAL_SCORE — gta6-trophy-rarity-forecast-01

## Method (a few lines)

Earners, not rates. Each read's printed rates are two decimals of
`100 * earners / players`, so the integer earners behind every rate are
recovered exactly (their sum is 943, matching the `trophies_earned` field).
Refreshes in the history (jumps in players tracked) are measured for how
much the tracked base grows, how fast earners grow, and how little the
newly tracked players have earned (their earn odds are a small fraction of
the old cohort's). The forecast projects players and earners to the target:
the number of refreshes still to come is a mixture over a lognormal gap
conditioned on how long the page has already been flat (a page flat for
hours on launch night is overdue, so a refresh before the target is the
modal outcome), each refresh dilutes the rates, and earners keep growing
between refreshes. Quantiles come from inverting that mixture, so the
upper tail honestly carries the chance of no refresh while the median sits
on the refreshed value. With no refresh in the history (the practice
shape) the refresh behaviour falls back to priors (median gap ~3.5 h,
first refresh ~6x tracked, new cohort at ~5% of the old odds). When many
refreshes are expected (the final's 6,510-minute horizon) the players and
earners are extrapolated from their own history trends instead of
compounding one refresh factor.

## Practice scores (local, pinball loss on the logit scale)

The kit holds no answer file, so the practice answers are reconstructed:
the refreshed page documented in `competition.yaml` (638 -> 3,868 players
tracked, every rate but the 100% one lower), earners recovered exactly from
the last read, grown by a factor `g` across the refresh window, divided by
3,868, rounded to Exophase's 2 decimals. The reconstruction is calibrated
on the two practice statistics the rules publish for the house persistence
baseline (loss about 1.51, typical miss about 0.68, coverage about 0):
at `g = 0.21` the baseline reproduces loss 1.49 / miss 0.69 / coverage 0.
The scorer itself was validated exactly against the worked example in
RULES.txt (mean 0.403404, every item value, and the 0.46023 invalid case).

| answers growth `g` | p00 loss | p01 loss | mean loss | typical miss | coverage |
|---|---|---|---|---|---|
| 0.21 (central) | 0.081556 | 0.072311 | **0.076934** | 0.0108 / 0.0082 | 1.000 |
| 0.10 (pessimistic) | 0.118931 | 0.106291 | 0.112611 | 0.0310 / 0.0284 | 1.000 |
| 0.32 (optimistic) | 0.073124 | 0.068951 | 0.071037 | 0.0026 / 0.0046 | 1.000 |

House persistence baseline on the same reconstructed answers: loss ~1.49
(about 1.51 published). The median of this entry is nearly exact
(typical miss ~0.01 points); the remaining loss is the honest spread.

## Runtime and determinism

- Both practice cases in 0.08 s total (limit 8 s per case).
- Two runs byte-identical (`cmp` clean on both `.out` files).
- Output format verified: 55 rows, ids 1..55 once each, 5 non-decreasing
  quantiles in [0, 100], ~2.7 KB per file (limit 65,536).

## Two passes

- v1: mean loss 0.130052 — FAIL. The median was already right, but the
  tails were wrong: a Poisson count for later refreshes put 14% weight on
  a second refresh inside 90 minutes (impossible on a ~3.5 h regular
  schedule), dragging the 5% quantile far too low, and the spread was
  wider than the data supports.
- v2 (this file): every refresh probability now comes from the same
  lognormal gap law (a second refresh needs another whole gap inside the
  remaining horizon), the gap dispersion prior tightened (0.25 -> 0.20),
  the component spread tightened, and the many-refresh path now
  extrapolates players/earners from their history trends instead of
  compounding one refresh factor (which would dilute the final's rates
  to nothing). A gap-definition bug found by the synthetic final-regime
  test was also fixed (gaps are between refreshes, not between the reads
  around one). Mean loss 0.130 -> 0.077. The multi-refresh path was
  smoke-tested only on synthetic cases (valid output, sane rates,
  deterministic); it cannot be validated against real f00 data locally.

## Verdict: SUBMIT

Mean practice loss **0.076934 < 0.117** (the gate), and it passes across
the whole reconstruction sensitivity range (0.071–0.113). Two honest
notes: (1) the loss is measured against reconstructed answers, not the
server's — the server's grade is the one that counts; (2) the live
rank-10 bar has tightened since the gate was set (about 0.106 at the
19:50 WIB sweep, rank 1 about 0.059) — the central estimate 0.077 is
still below it, but the pessimistic end of the sensitivity range (0.113)
is not, so the margin is real but not large.
