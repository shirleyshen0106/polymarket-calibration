#!/usr/bin/env python3
"""
Does the mispricing survive costs?

analyse.py establishes that Polymarket quotes are miscalibrated away from even odds:
low quotes resolve Yes more often than quoted, high quotes less often. That is a
statement about frequencies. It is not a statement about money, and analyse.py says so
in its own limitation 4 -- "Prices are mid-quotes, not executable. Spread and fees are
not modelled, so an apparent edge here is not a tradable edge."

This script answers the money question. It is written to be able to return "no".

METHOD, and why each choice was made
------------------------------------
* WALK-FORWARD, ordered by resolution date. The per-band bias is estimated on markets
  that had already resolved, and traded on markets that resolve later. Nothing is ever
  traded on the data that produced its own signal. This is the same discipline as the
  clustered holdout in the thesis work: the point of the split is to make the result
  able to fail.
* ONE HORIZON AT A TIME. observations_complete.csv holds one row per (market, horizon),
  so a single market appears up to four times. Pooling horizons would bet on the same
  resolution four times and inflate every statistic. --horizon picks one.
* ONE BET PER EVENT, optionally. Limitation 3 of analyse.py applies with more force to a
  backtest than to a reliability diagram: markets in one event ("who will win X") are
  mutually exclusive, so betting every leg is one position, not many. --one-per-event
  keeps the highest-volume leg per event and is the conservative reading.
* COSTS CHARGED ON ENTRY. The quote is a mid, so a buyer pays mid + half-spread.
  --half-spread is in probability units (0.01 = one cent on a 0-to-1 contract) and is
  the single most important parameter here. --fee-on-winnings charges a share of the
  profit on winning positions.
* BENCHMARKS, because a positive PnL means nothing on its own. Always-Yes and Always-No
  are reported on the same bets, and a no-edge control buys at the mid with no signal:
  its expected PnL is zero before costs and negative after, which is the number the
  strategy has to beat.
* CLUSTERED BOOTSTRAP for the interval. Resampling individual bets would pretend the
  legs of an event are independent. Events are resampled whole.

KNOWN LIMITATIONS, stated because they bound the conclusion
-----------------------------------------------------------
1. Inherited from the harvest: a rolling window of recently resolved markets, not a
   historical archive, so this is a month-scale sample and not a multi-year backtest.
2. Inherited survivorship: markets that served no price history are absent, and they are
   not missing at random.
3. Fills are assumed at mid plus half-spread for the full stake. Depth is not modelled.
   On a thin market the real fill is worse, so the costed result here is still optimistic.
4. No position sizing and no compounding. Every bet is one unit of stake, which makes
   per-bet statistics interpretable and deliberately says nothing about bankroll growth.
5. Sharpe here is a per-bet ratio over a sequence ordered by resolution date, not an
   annualised figure. Do not compare it to an annualised Sharpe.
"""
import argparse, csv, math, random, sys
from collections import defaultdict

BIN_EDGES = [0.0, 0.05, 0.15, 0.35, 0.65, 0.85, 0.95, 1.0]
MIN_TRAIN_N = 30        # no band trades until the training window has this many resolutions
MIN_EDGE = 0.02         # required |realised - quoted| in the training window to trade a band


def band_of(p):
    for i in range(len(BIN_EDGES) - 1):
        if BIN_EDGES[i] <= p < BIN_EDGES[i + 1]:
            return i
    return len(BIN_EDGES) - 2


def load(path, horizon):
    rows = []
    with open(path, newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            try:
                h = float(r["horizon_hours"])
                if abs(h - horizon) > 1e-6:
                    continue
                rows.append({
                    "market_id": r["market_id"],
                    "event": r.get("category") or r["market_id"],
                    "volume": float(r.get("volume") or 0.0),
                    "p": float(r["quoted_prob"]),
                    "y": int(float(r["outcome"])),
                    "end": r["end_date"],
                })
            except (ValueError, KeyError):
                continue
    rows.sort(key=lambda d: (d["end"], d["market_id"]))
    return rows


def one_per_event(rows):
    best = {}
    for r in rows:
        k = r["event"]
        if k not in best or r["volume"] > best[k]["volume"]:
            best[k] = r
    out = list(best.values())
    out.sort(key=lambda d: (d["end"], d["market_id"]))
    return out


def pnl(side, p_exec, y, fee):
    """One unit of stake. Buy Yes at p_exec pays 1 on y==1. Buy No at 1-p_exec pays 1 on y==0."""
    if side == "YES":
        gross = (1.0 - p_exec) if y == 1 else -p_exec
    else:
        q = 1.0 - p_exec
        gross = q if y == 0 else -(1.0 - q)
    if gross > 0 and fee > 0:
        gross *= (1.0 - fee)
    return gross


def fit_bands(train):
    """Per-band direction and edge, estimated on resolved markets only."""
    agg = defaultdict(lambda: [0, 0.0, 0])   # n, sum_p, sum_y
    for r in train:
        b = band_of(r["p"])
        agg[b][0] += 1
        agg[b][1] += r["p"]
        agg[b][2] += r["y"]
    sig = {}
    for b, (n, sp, sy) in agg.items():
        if n < MIN_TRAIN_N:
            continue
        quoted, realised = sp / n, sy / n
        edge = realised - quoted
        if abs(edge) < MIN_EDGE:
            continue
        sig[b] = ("YES" if edge > 0 else "NO", edge, n)
    return sig


def max_drawdown(curve):
    peak, mdd = 0.0, 0.0
    for v in curve:
        peak = max(peak, v)
        mdd = min(mdd, v - peak)
    return mdd


def sharpe(xs):
    if len(xs) < 2:
        return float("nan")
    m = sum(xs) / len(xs)
    var = sum((x - m) ** 2 for x in xs) / (len(xs) - 1)
    return m / math.sqrt(var) if var > 0 else float("nan")


def run(rows, train_frac, half_spread, fee, step):
    """Expanding-window walk-forward. Returns per-bet records in resolution order."""
    n = len(rows)
    start = max(int(n * train_frac), MIN_TRAIN_N)
    bets = []
    i = start
    while i < n:
        j = min(i + step, n)
        sig = fit_bands(rows[:i])          # fit on everything resolved before i
        for r in rows[i:j]:                # trade the next block
            b = band_of(r["p"])
            if b not in sig:
                continue
            side, edge, tn = sig[b]
            p_exec = min(1.0, r["p"] + half_spread) if side == "YES" \
                     else max(0.0, r["p"] - half_spread)
            bets.append({
                "event": r["event"], "band": b, "side": side, "p": r["p"],
                "p_exec": p_exec, "y": r["y"], "end": r["end"],
                "pnl": pnl(side, p_exec, r["y"], fee),
                "train_edge": edge, "train_n": tn,
            })
        i = j
    return bets, start


def benchmarks(bets, half_spread, fee):
    out = {}
    for name, side in (("always-YES", "YES"), ("always-NO", "NO")):
        tot = 0.0
        for b in bets:
            pe = min(1.0, b["p"] + half_spread) if side == "YES" else max(0.0, b["p"] - half_spread)
            tot += pnl(side, pe, b["y"], fee)
        out[name] = tot
    # no-edge control: take the strategy's own side but pay the mid, no signal value
    out["no-edge (mid, no signal)"] = sum(pnl(b["side"], b["p"], b["y"], fee) for b in bets)
    return out


def event_bootstrap(bets, reps, seed=0):
    by_event = defaultdict(list)
    for b in bets:
        by_event[b["event"]].append(b["pnl"])
    events = list(by_event.values())
    if not events:
        return float("nan"), float("nan")
    rng = random.Random(seed)
    totals = []
    for _ in range(reps):
        s, k = 0.0, 0
        for _ in range(len(events)):
            e = events[rng.randrange(len(events))]
            s += sum(e); k += len(e)
        totals.append(s / k if k else 0.0)
    totals.sort()
    lo = totals[int(0.025 * len(totals))]
    hi = totals[min(len(totals) - 1, int(0.975 * len(totals)))]
    return lo, hi


def main():
    ap = argparse.ArgumentParser(description="Cost-aware walk-forward test of the Polymarket mispricing.")
    ap.add_argument("--obs", default="observations_complete.csv")
    ap.add_argument("--horizon", type=float, default=720, help="hours before resolution: 1, 24, 168 or 720")
    ap.add_argument("--train-frac", type=float, default=0.4, help="initial training share, by resolution order")
    ap.add_argument("--step", type=int, default=250, help="markets traded per refit block")
    ap.add_argument("--half-spread", type=float, default=0.01, help="probability units paid over the mid on entry")
    ap.add_argument("--fee-on-winnings", type=float, default=0.0, help="share of profit taken on winning bets")
    ap.add_argument("--one-per-event", action="store_true", help="keep only the highest-volume leg per event")
    ap.add_argument("--bootstrap", type=int, default=2000)
    a = ap.parse_args()

    rows = load(a.obs, a.horizon)
    if not rows:
        sys.exit(f"no rows at horizon {a.horizon} in {a.obs}")
    label = "all legs"
    if a.one_per_event:
        rows = one_per_event(rows); label = "one leg per event"

    print(f"DATA        {a.obs}")
    print(f"            horizon {a.horizon:g}h, {len(rows)} resolutions, {label}")
    print(f"            resolution dates {rows[0]['end'][:10]} to {rows[-1]['end'][:10]}")
    print(f"COSTS       half-spread {a.half_spread:.4f} on entry, fee on winnings {a.fee_on_winnings:.2%}")

    bets, start = run(rows, a.train_frac, a.half_spread, a.fee_on_winnings, a.step)
    print(f"WALK-FWD    fit on first {start} resolutions, refit every {a.step}; "
          f"{len(bets)} bets placed out of {len(rows) - start} testable")
    if not bets:
        print("\nNO BETS. No band cleared the training thresholds "
              f"(n >= {MIN_TRAIN_N}, |edge| >= {MIN_EDGE}). That is a result, not a failure.")
        return

    pnls = [b["pnl"] for b in bets]
    total = sum(pnls)
    curve, run_tot = [], 0.0
    for v in pnls:
        run_tot += v; curve.append(run_tot)
    wins = sum(1 for b in bets if b["pnl"] > 0)
    lo, hi = event_bootstrap(bets, a.bootstrap)

    print(f"\nSTRATEGY    total PnL {total:+.2f} units over {len(bets)} bets")
    print(f"            PnL per bet {total/len(bets):+.4f}  "
          f"[95% event-clustered bootstrap {lo:+.4f}, {hi:+.4f}]")
    print(f"            hit rate {wins/len(bets):.1%}   per-bet Sharpe {sharpe(pnls):.3f}")
    print(f"            max drawdown {max_drawdown(curve):+.2f} units   turnover {len(bets)} bets")
    print(f"            distinct events {len({b['event'] for b in bets})}")

    print("\nBENCHMARKS  on the same bets, same costs")
    for k, v in benchmarks(bets, a.half_spread, a.fee_on_winnings).items():
        print(f"            {k:28} {v:+.2f} units  ({v/len(bets):+.4f} per bet)")

    print("\nBY BAND")
    agg = defaultdict(lambda: [0, 0.0])
    for b in bets:
        agg[b["band"]][0] += 1; agg[b["band"]][1] += b["pnl"]
    for b in sorted(agg):
        n, s = agg[b]
        side = next(x["side"] for x in bets if x["band"] == b)
        print(f"            [{BIN_EDGES[b]:.2f},{BIN_EDGES[b+1]:.2f}) {side:3}  "
              f"n={n:5}  PnL {s:+8.2f}  per bet {s/n:+.4f}")

    verdict = "SURVIVES" if lo > 0 else ("DOES NOT SURVIVE" if hi < 0 else "INCONCLUSIVE")
    print(f"\nVERDICT     {verdict} at these costs. "
          f"The bootstrap interval {'excludes' if verdict != 'INCONCLUSIVE' else 'includes'} zero.")
    print("            Re-run with a larger --half-spread before believing anything positive.")


if __name__ == "__main__":
    main()
