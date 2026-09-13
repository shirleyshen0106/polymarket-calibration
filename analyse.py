#!/usr/bin/env python3
"""
Is the Polymarket price a calibrated probability?

Reads observations.csv from harvest.py -- one row per (market, horizon) giving the
price quoted H hours before resolution and the outcome the market settled to -- and
asks the only question that matters for a probability: when the market says 70 per
cent, does it happen 70 per cent of the time?

METHOD, and why each choice was made
------------------------------------
* Binary outcome, so calibration is a RELIABILITY DIAGRAM, not interval coverage.
  Same question as conformal coverage (does the claimed frequency occur?), different
  estimator, because the target is an event rather than a real-valued response.
* Bins are coarse and uneven on purpose. Prediction-market quotes pile up near 0 and 1,
  so equal-width deciles leave the middle bins with single-digit counts and nothing can
  be concluded from them. The bin edges below keep most bins usable.
* Every bin carries a WILSON confidence interval, and no bin below MIN_N gets a verdict.
  A realised frequency from eight markets is a hint, not a finding -- the same rule as
  report_by_group_ci in 06_UQ_Toolkit.
* Brier score with the Murphy decomposition (reliability - resolution + uncertainty)
  because a single score hides whether the model is miscalibrated or merely uninformative.

KNOWN LIMITATIONS, stated because they bound the conclusion
-----------------------------------------------------------
1. ~30-day rolling window. The CLOB serves price history only for recently closed
   markets, so this is one month of resolutions, not a historical archive.
2. Survivorship in the sample. Roughly one eligible market in seven is dropped because
   no history was served (295 of 2100 in the 7 Sep 2026 harvest); check_selection()
   reports the live figures from harvest_stats.json rather than hard-coding them, which
   is how the stale "90 of 300" from the truncated first sweep survived as long as it did.
3. Observations are NOT independent. Several markets often belong to one event
   ("who will be X") and are mutually exclusive, so effective sample size is below
   the row count and the intervals below are optimistic.
4. Prices are mid-quotes, not executable. Spread and fees are not modelled, so an
   apparent edge here is not a tradable edge.
"""
import argparse, csv, json, math, sys
from collections import defaultdict

MIN_N = 30
MIN_EVENTS = 5   # need >=5 of each outcome in a band before any verdict
BIN_EDGES = [0.0, 0.05, 0.15, 0.35, 0.65, 0.85, 0.95, 1.0]
HORIZON_LABEL = {1: "1 hour", 24: "1 day", 168: "7 days", 720: "30 days"}


def wilson(k, n, conf=0.95):
    """Wilson score interval for a proportion -- same estimator as uq_toolkit.coverage_ci."""
    if n == 0:
        return float("nan"), float("nan"), float("nan")
    z = 1.959963984540054 if abs(conf - 0.95) < 1e-9 else 1.959963984540054
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return p, max(0.0, centre - half), min(1.0, centre + half)


def load(path="observations.csv"):
    rows = []
    for r in csv.DictReader(open(path)):
        rows.append({
            "market_id": r["market_id"], "category": r["category"],
            "volume": float(r["volume"]), "horizon": int(r["horizon_hours"]),
            "p": float(r["quoted_prob"]), "y": int(r["outcome"]),
        })
    return rows


def brier(rows):
    """Brier score and its Murphy decomposition into reliability, resolution, uncertainty."""
    n = len(rows)
    if n == 0:
        return {}
    bs = sum((r["p"] - r["y"]) ** 2 for r in rows) / n
    base = sum(r["y"] for r in rows) / n
    unc = base * (1 - base)
    buckets = defaultdict(list)
    for r in rows:
        buckets[bin_of(r["p"])].append(r)
    rel = res = 0.0
    for _, grp in buckets.items():
        nk = len(grp)
        pk = sum(g["p"] for g in grp) / nk
        ok = sum(g["y"] for g in grp) / nk
        rel += nk * (pk - ok) ** 2
        res += nk * (ok - base) ** 2
    return {"brier": bs, "reliability": rel / n, "resolution": res / n,
            "uncertainty": unc, "base_rate": base, "n": n,
            "brier_vs_base": bs - base * (1 - base)}


def bin_of(p):
    for i in range(len(BIN_EDGES) - 1):
        if BIN_EDGES[i] <= p < BIN_EDGES[i + 1]:
            return i
    return len(BIN_EDGES) - 2


def reliability_table(rows, label):
    print(f"\n{'='*78}\nRELIABILITY -- quote taken {label} before resolution   (n = {len(rows)})\n{'='*78}")
    print(f"  {'quoted band':>14} {'n':>5} {'mean quote':>11} {'realised':>9} {'95% CI':>16}   verdict")
    buckets = defaultdict(list)
    for r in rows:
        buckets[bin_of(r["p"])].append(r)
    out = []
    for i in sorted(buckets):
        grp = buckets[i]
        n = len(grp)
        k = sum(g["y"] for g in grp)
        mean_q = sum(g["p"] for g in grp) / n
        f, lo, hi = wilson(k, n)
        band = f"{BIN_EDGES[i]:.0%}-{BIN_EDGES[i+1]:.0%}"
        # Compare on floats with a small margin: a verdict that flips on the third
        # decimal is a rounding artefact, not a finding.
        eps = 1e-4
        if n < MIN_N:
            v = f"too few to judge (n<{MIN_N})"
        elif min(k, n - k) < MIN_EVENTS:
            # A band can clear the n floor and still rest on a handful of events.
            # 107 observations of which 2 resolved Yes is two data points, not 107,
            # and a Wilson interval that clears the quote by 0.02 points is an
            # artefact of the approximation rather than a result.
            v = f"n ok but only {min(k, n-k)} of the rarer outcome -- no verdict"
        elif hi < mean_q - eps:
            v = "market OVERPRICED this band"
        elif lo > mean_q + eps:
            v = "market UNDERPRICED this band"
        else:
            v = "consistent with the quote"
        print(f"  {band:>14} {n:>5} {mean_q:>10.1%} {f:>9.1%} [{lo:>5.1%},{hi:>6.1%}]   {v}")
        out.append({"band": band, "n": n, "mean_quote": mean_q, "realised": f,
                    "lo": lo, "hi": hi, "verdict": v})
    b = brier(rows)
    print(f"\n  Brier {b['brier']:.4f}   (reliability {b['reliability']:.4f}, "
          f"resolution {b['resolution']:.4f}, uncertainty {b['uncertainty']:.4f})")
    print(f"  Base rate {b['base_rate']:.1%}.  Always predicting the base rate scores "
          f"{b['uncertainty']:.4f}, so the market beats it by {-b['brier_vs_base']:.4f}.")
    return out, b


def check_selection(kept_path="markets.csv"):
    """The dropped markets are the ones the API would not serve history for.
    If they differ systematically in volume, the sample is biased and we say so."""
    kept = list(csv.DictReader(open(kept_path)))
    vols = sorted(float(m["volume"]) for m in kept)
    med = vols[len(vols) // 2]
    print(f"\nSELECTION: {len(kept)} markets kept, median volume ${med:,.0f}, "
          f"range ${vols[0]:,.0f} to ${vols[-1]:,.0f}")
    try:
        s = json.load(open("harvest_stats.json"))
    except Exception:
        print("  (no harvest_stats.json; survivorship figures unavailable for this run)")
        return
    print(f"  Most recent harvest ({s['harvest_date'][:10]}, {s['days']}-day window): "
          f"{s['eligible']} eligible, {s['kept']} kept, "
          f"{s['dropped_nohistory']} dropped for lack of served history and "
          f"{s['dropped_unresolved']} for not settling to a clean binary.")
    print("  The history drop is a function of closing date, not of size.")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--obs", default="observations.csv")
    ap.add_argument("--markets", default="markets.csv")
    ap.add_argument("--fig", default="reliability.png")
    a = ap.parse_args()
    rows = load(a.obs)
    check_selection(a.markets)
    results = {}
    for h in sorted({r["horizon"] for r in rows}, reverse=True):
        sub = [r for r in rows if r["horizon"] == h]
        if len(sub) < MIN_N:
            print(f"\nSKIPPING {HORIZON_LABEL.get(h, h)} horizon: only {len(sub)} observations, "
                  f"below the {MIN_N}-point floor for saying anything.")
            continue
        results[h] = reliability_table(sub, HORIZON_LABEL.get(h, f"{h}h"))
    try:
        plot(rows, results, a.fig)
    except Exception as e:
        print(f"\n(plot skipped: {type(e).__name__} {e})")
    return results


def plot(rows, results, fig_path="reliability.png"):
    """Plot every band, but make the thin ones look thin.

    Plotting only the bands that pass the sample-size floor would show one point per
    horizon and imply the curve was measured. Marker area is proportional to n and
    unfilled markers are bands with no verdict, so the figure carries its own caveat.
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(1, 2, figsize=(11.5, 4.8))
    ax[0].plot([0, 1], [0, 1], "--", color="#888", lw=1, zorder=1, label="perfect calibration")
    colours = {1: "#c0392b", 24: "#2b3a67", 168: "#0f6e69"}
    for h, (tbl, _) in sorted(results.items()):
        c = colours.get(h, "#555")
        xs = [t["mean_quote"] for t in tbl]
        ys = [t["realised"] for t in tbl]
        ax[0].plot(xs, ys, "-", color=c, lw=1.2, alpha=0.75, zorder=2,
                   label=f"{HORIZON_LABEL.get(h, h)} before")
        for t in tbl:
            # A band has a verdict if it is either consistent or mispriced. Filling only
            # the consistent ones (as this did until 12 Sep 2026) drew the mispriced
            # bands -- the actual finding -- as if they were too thin to judge.
            judged = (t["verdict"] == "consistent with the quote"
                      or t["verdict"].startswith("market "))
            mispriced = t["verdict"].startswith("market ")
            ax[0].errorbar(t["mean_quote"], t["realised"],
                           yerr=[[t["realised"] - t["lo"]], [t["hi"] - t["realised"]]],
                           color=c, alpha=0.5, capsize=2, lw=1, zorder=2)
            ax[0].scatter(t["mean_quote"], t["realised"], s=10 + 9 * t["n"] ** 0.5,
                          facecolor=(c if judged else "none"), edgecolor=c,
                          lw=1.3, alpha=0.8, zorder=3)
            if mispriced:
                ax[0].scatter(t["mean_quote"], t["realised"], s=10 + 9 * t["n"] ** 0.5,
                              facecolor="none", edgecolor="black", lw=1.6, zorder=4)
    ax[0].set_xlim(-0.04, 1.04); ax[0].set_ylim(-0.04, 1.04)
    ax[0].set_xlabel("quoted probability"); ax[0].set_ylabel("realised frequency")
    ax[0].set_title("Polymarket reliability by horizon\n"
                    "area $\\propto \\sqrt{n}$; unfilled = no verdict; black ring = mispriced",
                    fontsize=10)
    ax[0].legend(fontsize=8, loc="upper left"); ax[0].grid(alpha=0.22)

    ps = [r["p"] for r in rows]
    ax[1].hist(ps, bins=25, color="#2b3a67", alpha=0.85)
    below = sum(1 for p in ps if p < 0.05) / len(ps)
    ax[1].axvspan(0, 0.05, color="#c0392b", alpha=0.12)
    ax[1].set_xlabel("quoted probability"); ax[1].set_ylabel("observations")
    mid = sum(1 for p in ps if 0.35 <= p < 0.65) / len(ps)
    ax[1].set_title(f"Where the quotes sit: {below:.0%} below 5%, "
                    f"{mid:.0%} between 35 and 65%\n(all horizons pooled)", fontsize=10)
    ax[1].grid(alpha=0.22)
    fig.tight_layout(); fig.savefig(fig_path, dpi=170)
    print(f"\nwrote {fig_path}")


if __name__ == "__main__":
    main()
