"""GTA VI trophy rarity forecast: a refresh / dilution model.

Exophase does not update a game's trophy counts continuously: it refreshes
them on its own schedule, hours apart, and a read shows the rates as of the
last refresh before it.  Between refreshes the page is frozen; at a refresh
the tracked-player count jumps and every rate drops, because the newly
tracked players have earned far fewer trophies than the early adopters who
were tracked first.  A forecast that just extends the last read is therefore
wrong in exactly the way the practice cases punish: it is scored on a page
that has refreshed since the checkpoint.

The model below works in earners, not rates.  For every read it recovers the
integer number of earners behind each printed rate (rate * players / 100),
finds the refreshes in the history (jumps in players tracked), and measures
on them how much the tracked base grows per refresh, how fast earners grow,
and how little the newly tracked players have earned (their earn odds are a
small fraction of the old cohort's odds).  It then projects the players and
the earners to the target: the number of refreshes still to come is a
mixture (a lognormal gap, conditioned on how long the page has already been
flat, so a long-flat page is overdue for a refresh), each refresh dilutes
the rates by the measured factor, and earners keep growing in between.
The forecast for a trophy is that mixture, inverted at the five scored
levels, so the upper quantiles honestly carry the chance that no refresh
comes before the target while the median sits on the refreshed value.

When the history holds no refresh at all (the practice shape: one flat page
from launch night) the refresh behaviour falls back to priors: a median gap
of about three and a half hours, a first refresh that multiplies the tracked
base about sixfold, and newly tracked players earning at about 5% of the old
cohort's odds.  Those priors are the documented behaviour of this game's
launch-night page, and they are the only place the program leans on anything
beyond the case file; everything else is estimated from the history in hand.

Standard library only, no network, no randomness: the same input always
writes the same bytes.
"""

import json
import math
import os
from datetime import datetime, timezone
from pathlib import Path

INPUT_DIR = Path(os.environ.get("MAKEFUN_INPUT_DIR", "/input"))
OUTPUT_DIR = Path(os.environ.get("MAKEFUN_OUTPUT_DIR", "/output"))

LEVELS = [0.05, 0.25, 0.5, 0.75, 0.95]

# Priors for a history with no refresh in it yet.  A page that has been flat
# for hours on launch night is stale, not stable: Exophase refreshes every
# few hours, so a refresh before the target is the modal outcome.
PRIOR_GAP_MIN = 210.0       # median minutes between refreshes
PRIOR_GAP_LOG_SD = 0.20     # dispersion of the gap, log scale
PRIOR_GROWTH = 6.0          # tracked players multiply by ~6 at a refresh
PRIOR_KAPPA_ODDS = 0.05     # new cohort earns at ~5% of the old odds
PRIOR_TREND_PER_HOUR = 0.0  # earners stand still while the page is frozen

# Spread of one mixture component, in logit units: a fixed term for how
# well the refresh size is known, plus a term that shrinks as the trophy's
# earner count grows (a trophy with few earners is known less precisely).
SPREAD_FIXED = 0.08
SPREAD_EARNERS = 0.25


def clamp_rate(x):
    return min(99.99, max(0.01, x))


def logit_pct(x):
    p = clamp_rate(x)
    return math.log(p / (100.0 - p))


def inv_logit_pct(lo):
    if lo >= 0:
        return 100.0 / (1.0 + math.exp(-lo))
    e = math.exp(lo)
    return 100.0 * e / (1.0 + e)


def round4(x):
    """Round to 4 decimals, half up; whole numbers come back as ints."""
    scaled = x * 10000.0
    whole = math.floor(scaled + 0.5)
    value = whole / 10000.0
    return int(value) if value.is_integer() else value


def norm_cdf(x):
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def parse_minutes(text):
    """An ISO timestamp to minutes since the epoch (UTC)."""
    dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp() / 60.0


def median(values):
    vals = sorted(values)
    n = len(vals)
    if n == 0:
        return None
    if n % 2:
        return vals[n // 2]
    return 0.5 * (vals[n // 2 - 1] + vals[n // 2])


def weighted_median(pairs):
    """Median of values with weights: pairs are (value, weight)."""
    ordered = sorted(pairs)
    total = sum(w for _, w in ordered)
    if total <= 0:
        return None
    acc = 0.0
    for value, weight in ordered:
        acc += weight
        if acc >= 0.5 * total:
            return value
    return ordered[-1][0]


def read_case(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def recover_reads(case):
    """History reads as (slot minutes, players, earners per trophy).

    Earners are integers: the printed rates are two decimals of
    100 * earners / players, so rounding rate * players / 100 recovers them.
    A null rate falls back to the trophy's last seen rate.
    """
    trophies = case["trophies"]
    n = len(trophies)
    last_rates = [0.0] * n
    reads = []
    for read in case["history"]:
        players = read["players_tracked"]
        earners = []
        for i, rate in enumerate(read["rates"]):
            if rate is None:
                rate = last_rates[i]
            else:
                last_rates[i] = rate
            earners.append(int(round(rate * players / 100.0)))
        slot = read.get("slot") or read["at"]
        reads.append((parse_minutes(slot), players, earners))
    return reads


def find_refreshes(reads):
    """Reads where the tracked base jumps: (index, players before/after)."""
    out = []
    for j in range(1, len(reads)):
        before = reads[j - 1][1]
        after = reads[j][1]
        if after > before * 1.02:
            out.append((j, before, after))
    return out


def estimate_trend(reads, n):
    """Earners' fractional growth per hour between refreshes.

    Measured on consecutive reads with an unchanged tracked base, as an
    earners-weighted median across trophies and read pairs, so a trophy
    nobody has earned cannot drag the estimate.
    """
    samples = []
    for j in range(1, len(reads)):
        t0, p0, e0 = reads[j - 1]
        t1, p1, e1 = reads[j]
        if p0 != p1 or t1 <= t0:
            continue
        hours = (t1 - t0) / 60.0
        if hours <= 0:
            continue
        for i in range(n):
            if e0[i] >= 2:
                samples.append(((e1[i] - e0[i]) / (e0[i] * hours), float(e0[i])))
    value = weighted_median(samples)
    if value is None:
        return PRIOR_TREND_PER_HOUR
    return min(0.30, max(0.0, value))


def estimate_params(case, reads, refreshes):
    """Refresh behaviour: gap, growth, new-cohort odds, earners trend."""
    n = len(case["trophies"])
    trend = estimate_trend(reads, n)

    gaps = []
    growths = []
    kappas = []
    refresh_times = [reads[j][0] for j, _, _ in refreshes]
    if len(refresh_times) >= 2:
        # Gaps are the times between one refresh and the next, not the
        # spacing of the reads around a refresh.
        gaps = [b - a for a, b in zip(refresh_times, refresh_times[1:]) if b > a]
    for j, p_before, p_after in refreshes:
        t_before = reads[j - 1][0]
        t_after = reads[j][0]
        growths.append(p_after / p_before)
        _, _, e_before = reads[j - 1]
        _, _, e_after = reads[j]
        dt_hours = max(0.0, (t_after - t_before) / 60.0)
        newcomers = p_after - p_before
        for i in range(n):
            old = e_before[i]
            if old < 3 or old >= p_before - 3 or newcomers <= 0:
                continue
            grown = old * (1.0 + trend * dt_hours)
            rho = (e_after[i] - grown) / newcomers
            if rho <= 0.0 or rho >= 1.0:
                continue
            p_old = old / p_before
            if p_old <= 0.0 or p_old >= 1.0:
                continue
            kappa = (rho / (1.0 - rho)) / (p_old / (1.0 - p_old))
            if 0.0 < kappa < 2.0:
                kappas.append(kappa)

    if len(gaps) >= 2:
        gap_med = median(gaps)
        logs = [math.log(g) for g in gaps if g > 0]
        mean_log = sum(logs) / len(logs)
        var_log = sum((x - mean_log) ** 2 for x in logs) / len(logs)
        gap_sd = min(0.60, max(0.15, math.sqrt(var_log)))
    elif len(gaps) == 1:
        gap_med = gaps[0]
        gap_sd = PRIOR_GAP_LOG_SD
    else:
        gap_med = PRIOR_GAP_MIN
        gap_sd = PRIOR_GAP_LOG_SD
    if not gap_med or gap_med <= 0:
        gap_med = PRIOR_GAP_MIN

    growth = median(growths) if growths else PRIOR_GROWTH
    growth = min(50.0, max(1.05, growth))
    kappa = median(kappas) if kappas else PRIOR_KAPPA_ODDS
    kappa = min(0.50, max(0.005, kappa))
    return {
        "gap_med": gap_med,
        "gap_sd": gap_sd,
        "growth": growth,
        "kappa": kappa,
        "trend": trend,
    }


def refresh_probability(flat_minutes, horizon_minutes, gap_med, gap_sd):
    """P(at least one refresh in the next horizon | flat for this long).

    Gaps are lognormal: a page flat for most of a gap is overdue, so the
    conditional chance of a refresh before the target is high.
    """
    s = max(1.0, flat_minutes)
    mu = math.log(gap_med)
    cdf_s = norm_cdf((math.log(s) - mu) / gap_sd)
    cdf_t = norm_cdf((math.log(s + horizon_minutes) - mu) / gap_sd)
    if cdf_s >= 1.0:
        return 1.0
    return min(1.0, max(0.0, (cdf_t - cdf_s) / (1.0 - cdf_s)))


def project_one(players, earners, refreshes, params, horizon_hours, gap_hours):
    """One refresh path: apply `refreshes` refreshes, earners growing between.

    Each refresh grows the tracked base by the measured factor and adds the
    newly tracked players' earnings at their (much lower) odds; between
    refreshes earners grow at the measured trend.  A trophy everybody has
    stays at 100%: its newcomers have it too.
    """
    p = players
    e = list(earners)
    remaining = horizon_hours
    for _ in range(refreshes):
        step = min(gap_hours, remaining)
        if step > 0:
            for i in range(len(e)):
                e[i] = e[i] * (1.0 + params["trend"] * step)
            remaining -= step
        p_new = p * params["growth"]
        newcomers = p_new - p
        for i in range(len(e)):
            if p <= 0:
                continue
            p_old = e[i] / p
            if p_old >= 0.999:
                rho = 1.0
            elif p_old <= 0.0:
                rho = 0.0
            else:
                odds = params["kappa"] * p_old / (1.0 - p_old)
                rho = odds / (1.0 + odds)
            e[i] = e[i] + rho * newcomers
        p = p_new
    if remaining > 0:
        for i in range(len(e)):
            e[i] = e[i] * (1.0 + params["trend"] * remaining)
    return p, e


def fit_log_curve(times, values):
    """Least-squares quadratic of log(values) against time (hours).

    Returns a function of time.  With too few points it falls back to a
    lower degree; with a flat series it returns the constant.  Times are
    centred and scaled before fitting so the normal equations stay sane.
    """
    pts = [(t, math.log(max(v, 0.5))) for t, v in zip(times, values)]
    n = len(pts)
    if n == 0:
        return lambda t: 1.0
    if n < 3:
        last = values[-1] if values else 1.0
        return lambda t: float(last)
    degree = 2 if n >= 4 else 1
    x0 = pts[0][0]
    scale = max(1.0, pts[-1][0] - pts[0][0])
    us = [(t - x0) / scale for t, _ in pts]
    ys = [y for _, y in pts]
    m = degree + 1
    mat = [[sum(u ** (i + j) for u in us) for j in range(m)] for i in range(m)]
    vec = [sum(y * (u ** i) for u, y in zip(us, ys)) for i in range(m)]
    # Gaussian elimination with partial pivoting.
    for col in range(m):
        piv = max(range(col, m), key=lambda r: abs(mat[r][col]))
        mat[col], mat[piv] = mat[piv], mat[col]
        vec[col], vec[piv] = vec[piv], vec[col]
        if abs(mat[col][col]) < 1e-12:
            break
        for row in range(col + 1, m):
            factor = mat[row][col] / mat[col][col]
            for j in range(col, m):
                mat[row][j] -= factor * mat[col][j]
            vec[row] -= factor * vec[col]
    coef = [0.0] * m
    for row in range(m - 1, -1, -1):
        if abs(mat[row][row]) < 1e-12:
            coef[row] = 0.0
            continue
        coef[row] = (vec[row] - sum(mat[row][j] * coef[j] for j in range(row + 1, m))) / mat[row][row]

    def fitted(t):
        u = (t - x0) / scale
        return math.exp(sum(coef[i] * (u ** i) for i in range(m)))

    return fitted


def extrapolate_counts(case, reads):
    """Players and earners at the target, from their history trends.

    Only used when many refreshes are expected: the history is then long
    enough to show how the tracked base and the earners actually grow, so
    the forecast follows those curves instead of compounding one refresh
    factor, which would dilute the rates to nothing.
    """
    t0 = reads[0][0]
    times = [(r[0] - t0) / 60.0 for r in reads]
    horizon_hours = float(case["horizon_minutes"]) / 60.0
    checkpoint = parse_minutes(case["at"])
    t_target = (checkpoint - t0) / 60.0 + horizon_hours
    n = len(case["trophies"])
    p_last = float(reads[-1][1])
    p_fit = fit_log_curve(times, [float(r[1]) for r in reads])
    p_tgt = min(max(p_fit(t_target), p_last), p_last * 100.0)
    e_tgt = []
    for i in range(n):
        vals = [float(r[2][i]) for r in reads]
        fitted = fit_log_curve(times, vals)
        e = min(max(fitted(t_target), vals[-1]), p_tgt)
        e_tgt.append(e)
    return p_tgt, e_tgt


def mixture_components(case, reads, params):
    """(weight, median rate, sigma) components for the refresh count.

    Every refresh probability comes from the same gap law: a lognormal gap,
    conditioned on how long the page has already been flat.  A fairly
    regular schedule means two refreshes inside one short horizon are
    nearly impossible, so the weights never leak into extra dilutions the
    schedule cannot produce.  When many refreshes are expected, the count
    is summarised by its mean and the players and earners are extrapolated
    from their history trends instead of compounding one refresh factor.
    """
    horizon = float(case["horizon_minutes"])
    horizon_hours = horizon / 60.0
    gap_hours = params["gap_med"] / 60.0
    _, p_last, e_last = reads[-1]
    refreshes = find_refreshes(reads)
    if refreshes:
        last_refresh_slot = reads[refreshes[-1][0]][0]
    else:
        last_refresh_slot = reads[0][0]
    checkpoint = parse_minutes(case["at"])
    flat_minutes = max(0.0, checkpoint - last_refresh_slot)
    p_one = refresh_probability(flat_minutes, horizon, params["gap_med"], params["gap_sd"])

    def gap_cdf(minutes):
        if minutes <= 0:
            return 0.0
        return norm_cdf((math.log(minutes) - math.log(params["gap_med"])) / params["gap_sd"])

    # Weights over the refresh count, from the gap law alone: after the
    # first refresh the next one needs another whole gap inside what is
    # left of the horizon, which is short.
    weights = [(0, 1.0 - p_one)]
    remaining_h = horizon / 2.0
    mass = p_one
    for k in range(1, 6):
        p_next = gap_cdf(max(1.0, remaining_h))
        w = mass * (1.0 - p_next)
        weights.append((k, w))
        mass = mass * p_next
        remaining_h = max(0.0, remaining_h - params["gap_med"])
        if mass < 0.001:
            break
    if mass > 0:
        k_last, w_last = weights[-1]
        weights[-1] = (k_last, w_last + mass)
    total_w = sum(w for _, w in weights)
    mean_count = sum(k * w for k, w in weights) / total_w

    def component(k, weight):
        p_k, e_k = project_one(p_last, e_last, k, params, horizon_hours, gap_hours)
        medians = []
        sigmas = []
        for i in range(len(e_k)):
            rate = 100.0 * e_k[i] / p_k if p_k > 0 else 0.0
            medians.append(rate)
            sigma = math.sqrt(SPREAD_FIXED ** 2 + SPREAD_EARNERS / max(e_k[i], 1.0))
            sigmas.append(min(0.45, sigma))
        return weight, medians, sigmas

    if mean_count < 4.0:
        return [component(k, w / total_w) for k, w in weights if w > 0]

    # Many refreshes coming: extrapolate the counts from their trends.
    # The count variance is the renewal variance, not Poisson's: a regular
    # schedule counts far more precisely than a memoryless one.
    p_tgt, e_tgt = extrapolate_counts(case, reads)
    shift = math.log(max(1e-6, (1.0 + params["kappa"] * (params["growth"] - 1.0)) / params["growth"]))
    count_var = mean_count * (math.exp(params["gap_sd"] ** 2) - 1.0)
    medians = []
    sigmas = []
    for i in range(len(e_tgt)):
        rate = 100.0 * e_tgt[i] / p_tgt if p_tgt > 0 else 0.0
        medians.append(rate)
        sigma = math.sqrt(SPREAD_FIXED ** 2 + SPREAD_EARNERS / max(e_tgt[i], 1.0) + count_var * shift * shift + 0.05)
        sigmas.append(min(1.20, sigma))
    return [(1.0, medians, sigmas)]


def forecast_trophy(components, index):
    """Five quantiles for one trophy from the mixture components."""
    parts = []
    for weight, medians, sigmas in components:
        rate = medians[index]
        if rate >= 99.99:
            parts.append((weight, None, None))
        else:
            parts.append((weight, logit_pct(rate), sigmas[index]))
    if all(m is None for _, m, _ in parts):
        return [100, 100, 100, 100, 100]
    # Bracket the logit range the mixture can reach.
    mus = [m for _, m, _ in parts if m is not None]
    sgs = [s for _, _, s in parts if s is not None]
    lo = min(mus) - 6.0 * max(sgs) - 1.0
    hi = max(mus) + 6.0 * max(sgs) + 1.0

    def cdf(x):
        total = 0.0
        for weight, mu, sigma in parts:
            if mu is None:
                total += weight if x >= logit_pct(99.99) else 0.0
            else:
                total += weight * norm_cdf((x - mu) / sigma)
        return total

    out = []
    for level in LEVELS:
        a, b = lo, hi
        for _ in range(80):
            mid = 0.5 * (a + b)
            if cdf(mid) < level:
                a = mid
            else:
                b = mid
        out.append(round4(inv_logit_pct(0.5 * (a + b))))
    fixed = []
    prev = 0.0
    for q in out:
        q = min(100.0, max(0.0, q))
        if q < prev:
            q = prev
        fixed.append(q)
        prev = q
    return fixed


def forecast_case(case, name):
    if case["levels"] != LEVELS:
        raise ValueError(f"{name} asks for levels {case['levels']}, not {LEVELS}")
    if not case["history"]:
        raise ValueError(f"{name} has no history")
    reads = recover_reads(case)
    refreshes = find_refreshes(reads)
    params = estimate_params(case, reads, refreshes)
    components = mixture_components(case, reads, params)
    rows = []
    for i, trophy in enumerate(case["trophies"]):
        rows.append({"id": trophy["id"], "q": forecast_trophy(components, i)})
    return {"trophies": rows}


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for path in sorted(INPUT_DIR.glob("*.in")):
        case = read_case(path)
        forecast = forecast_case(case, path.name)
        out_path = OUTPUT_DIR / f"{path.stem}.out"
        out_path.write_text(json.dumps(forecast, separators=(",", ":")) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
