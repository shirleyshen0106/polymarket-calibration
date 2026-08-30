#!/usr/bin/env python3
"""
Harvest resolved Polymarket markets and the price path that preceded them.

WHAT THIS PRODUCES
------------------
One row per (market, horizon): the price the market was quoting H hours before it
resolved, and the outcome it actually settled to. That pairing -- quoted probability
versus realised frequency -- is the whole input to a calibration study.

THE ONE CONSTRAINT THAT SHAPES THE DESIGN (verified 30 Aug 2026)
---------------------------------------------------------------
The CLOB price-history endpoint only serves markets that closed in roughly the last
30 days. Tested on samples of eight markets per month:
    closed in Aug 2026 -> history served for 8/8
    closed in Jul 2026 -> 0/8
    closed in Jun 2026 -> 0/8
So this is a ROLLING ~30-DAY WINDOW, not an archive. Two consequences:
  1. Run it now and keep the output. The window moves; today's data is gone next month.
  2. Re-run weekly to accumulate. The dataset grows forward, not backward.

Also verified: `interval=max&fidelity=<minutes>` works; `startTs`/`endTs` returns an
empty history even on live markets. Use interval, not timestamps.

Kalshi was tried first and is not reachable from this machine (TLS handshake failure
from a UK connection), so this study is Polymarket-only. Say so in the write-up
rather than implying wider coverage than the data supports.

USAGE
-----
    python3 harvest.py                 # last 30 days, volume >= 10k
    python3 harvest.py --days 30 --min-volume 10000 --out observations.csv
"""
import argparse, csv, datetime as dt, json, sys, time, urllib.error, urllib.request

GAMMA = "https://gamma-api.polymarket.com/markets"
CLOB = "https://clob.polymarket.com/prices-history"
UA = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}

# Hours before resolution at which to read the quoted probability.
HORIZONS_H = [720, 168, 24, 1]   # 30 days, 7 days, 1 day, 1 hour


def get(url, retries=6, pause=0.35):
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=45) as r:
                return json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503) and attempt < retries - 1:
                time.sleep(min(30, 1.5 * 2 ** attempt))
                continue
            raise
        except Exception:
            if attempt < retries - 1:
                time.sleep(min(30, 1.5 * 2 ** attempt))
                continue
            raise


def iso(d):
    return d.strftime("%Y-%m-%dT%H:%M:%SZ")


def fetch_markets(days, min_volume):
    """Every closed market ending in the window, paginated. Gamma caps limit at 100."""
    now = dt.datetime.now(dt.timezone.utc)
    lo, hi = now - dt.timedelta(days=days), now
    out, offset = [], 0
    while True:
        url = (f"{GAMMA}?limit=100&offset={offset}&closed=true"
               f"&volume_num_min={int(min_volume)}"
               f"&end_date_min={iso(lo)}&end_date_max={iso(hi)}")
        try:
            page = get(url)
        except Exception as e:
            # Gamma 500s on deep offsets rather than returning an empty page, so a
            # failure here means "no more pages", not "the harvest is broken".
            print(f"  pagination stopped at offset {offset}: {type(e).__name__}", file=sys.stderr)
            break
        if not page:
            break
        out.extend(page)
        offset += 100
        if len(page) < 100 or offset > 5000:
            break
    return out


def settled_outcome(market):
    """Return 1 if the FIRST listed outcome won, 0 if it lost, None if unresolved.

    outcomePrices is the settlement vector, e.g. ["0","1"] means outcome[1] won.
    Anything that is not a clean 0/1 pair (voided, 50/50 split, multi-outcome) is
    dropped rather than guessed at -- a mis-scored resolution is worse than a
    smaller sample.
    """
    try:
        prices = [float(p) for p in json.loads(market["outcomePrices"])]
    except Exception:
        return None
    if len(prices) != 2:
        return None
    if abs(prices[0] - 1) < 1e-9 and abs(prices[1]) < 1e-9:
        return 1
    if abs(prices[0]) < 1e-9 and abs(prices[1] - 1) < 1e-9:
        return 0
    return None


def price_path(token_id, fidelity=60):
    h = get(f"{CLOB}?market={token_id}&interval=max&fidelity={fidelity}")
    return h.get("history") or []


def quote_at(path, target_ts, tolerance_s):
    """Nearest quote to target_ts, or None if the gap exceeds tolerance.

    Returning the nearest point unconditionally would silently substitute a quote
    from a different week when the path is sparse, so the tolerance is enforced.
    """
    best, best_gap = None, None
    for p in path:
        gap = abs(p["t"] - target_ts)
        if best_gap is None or gap < best_gap:
            best, best_gap = p, gap
    if best is None or best_gap > tolerance_s:
        return None, None
    return float(best["p"]), best_gap


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--min-volume", type=int, default=10000)
    ap.add_argument("--fidelity", type=int, default=60, help="minutes per history point")
    ap.add_argument("--max-markets", type=int, default=0, help="0 = no cap")
    ap.add_argument("--out", default="observations.csv")
    ap.add_argument("--markets-out", default="markets.csv")
    a = ap.parse_args()

    markets = fetch_markets(a.days, a.min_volume)
    if a.max_markets:
        markets = markets[:a.max_markets]
    print(f"{len(markets)} closed markets in the last {a.days} days with volume >= {a.min_volume:,}")

    rows, mrows = [], []
    kept = dropped_unresolved = dropped_nohistory = 0

    for i, m in enumerate(markets, 1):
        y = settled_outcome(m)
        if y is None:
            dropped_unresolved += 1
            continue
        try:
            token = json.loads(m["clobTokenIds"])[0]      # the "Yes"/first-outcome token
            end = dt.datetime.fromisoformat(m["endDate"].replace("Z", "+00:00"))
        except Exception:
            dropped_unresolved += 1
            continue

        time.sleep(0.25)   # be polite; the public API 500s under rapid fire
        path = price_path(token, a.fidelity)
        if not path:
            dropped_nohistory += 1
            continue
        kept += 1
        end_ts = int(end.timestamp())
        cat = (m.get("events") or [{}])[0].get("ticker", "") or m.get("category", "") or "uncategorised"

        mrows.append({
            "market_id": m.get("id"), "question": m.get("question"),
            "slug": m.get("slug"), "category": cat,
            "end_date": m.get("endDate"), "closed_time": m.get("closedTime"),
            "volume": round(float(m.get("volumeNum") or 0), 2),
            "outcome_first_won": y, "n_history_points": len(path),
        })

        for H in HORIZONS_H:
            p, gap = quote_at(path, end_ts - H * 3600, tolerance_s=max(3 * 3600, H * 3600 * 0.25))
            if p is None:
                continue
            rows.append({
                "market_id": m.get("id"), "question": m.get("question"),
                "category": cat, "volume": round(float(m.get("volumeNum") or 0), 2),
                "horizon_hours": H, "quoted_prob": round(p, 6),
                "outcome": y, "quote_gap_hours": round(gap / 3600, 2),
                "end_date": m.get("endDate"),
            })
        if i % 25 == 0:
            print(f"  {i}/{len(markets)} markets, {len(rows)} observations", file=sys.stderr)

    with open(a.out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()) if rows else
                           ["market_id", "question", "category", "volume", "horizon_hours",
                            "quoted_prob", "outcome", "quote_gap_hours", "end_date"])
        w.writeheader(); w.writerows(rows)
    with open(a.markets_out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(mrows[0].keys()) if mrows else ["market_id"])
        w.writeheader(); w.writerows(mrows)

    print(f"\nkept {kept} markets | dropped {dropped_unresolved} (not a clean binary settlement) "
          f"| dropped {dropped_nohistory} (no history served -- outside the ~30-day window)")
    print(f"wrote {len(rows)} observations -> {a.out}")
    print(f"wrote {len(mrows)} markets      -> {a.markets_out}")


if __name__ == "__main__":
    main()
