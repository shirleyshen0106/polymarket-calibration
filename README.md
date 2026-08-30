# Are Polymarket prices calibrated probabilities?

A one-month reliability study of resolved Polymarket markets. **202 markets, 529
quote–outcome pairs**, at one hour, one day and seven days before resolution.

![reliability diagram](reliability.png)

## The question

A prediction-market price is only a probability if it behaves like one: of everything
the market prices at 70 per cent, roughly 70 per cent should happen. That is a
*reliability* question, and it is the same question I ask of my own models' uncertainty
in my PhD — where a multi-seed ensemble claiming 90 per cent coverage was found to
deliver 58.9 per cent, and split conformal prediction repaired it to 94.6 per cent
without retraining. This repository points the same discipline at market prices.

## Headline result

**In aggregate, the market looks well calibrated and is genuinely informative — and
that aggregate cannot be trusted, because no individual probability band has enough
resolutions in one month to test it.**

| Quote taken | n | Brier | reliability ↓ | resolution ↑ | uncertainty | beats base rate by |
|---|---:|---:|---:|---:|---:|---:|
| 7 days before | 128 | 0.0828 | 0.0031 | 0.1509 | 0.2256 | 0.1428 |
| 1 day before | 198 | 0.0592 | 0.0056 | 0.1524 | 0.2071 | 0.1479 |
| 1 hour before | 198 | 0.0560 | 0.0078 | 0.1550 | 0.2071 | 0.1511 |

Read positively: the reliability component of the Brier score is tiny next to the
uncertainty term, so there is little systematic miscalibration; resolution is large,
so the prices carry real information; and the score sharpens monotonically as
resolution approaches, which is what an efficient market should do.

**Read honestly, that table is weaker than it looks.** Every probability band fails one
of two sample-size tests, so not one of them supports a verdict:

```
RELIABILITY -- quote taken 1 day before resolution   (n = 198)
   quoted band     n  mean quote  realised           95% CI   verdict
         0%-5%   104       0.5%      1.0% [ 0.2%,  5.2%]   n ok but only 1 of the rarer outcome -- no verdict
        5%-15%    14       9.7%     14.3% [ 4.0%, 39.9%]   too few to judge (n<30)
       15%-35%    16      25.6%     25.0% [10.2%, 49.5%]   too few to judge (n<30)
       35%-65%    11      48.3%     18.2% [ 5.1%, 47.7%]   too few to judge (n<30)
       65%-85%    10      73.6%     80.0% [49.0%, 94.3%]   too few to judge (n<30)
       85%-95%    17      90.7%     94.1% [73.0%, 99.0%]   too few to judge (n<30)
      95%-100%    26      98.5%     96.2% [81.1%, 99.3%]   too few to judge (n<30)
```

## Why, and it is structural rather than a sampling accident

**Half of all quotes sit below five per cent** (right-hand panel above). Prediction-market
questions are overwhelmingly "will this unusual thing happen", and they overwhelmingly
resolve No. So the aggregate calibration is carried almost entirely by longshots
correctly resolving No — the easy part — while the middle of the range, where a
mispricing would actually be worth trading, is never populated enough to test.

This is why the study reports a negative result rather than the encouraging Brier
score. Widening the volume filter does not fix it: the shape of the quote distribution
is a property of the venue, not of the sample.

## Two sample-size rules, and why both are needed

1. **n ≥ 30 per band.** Coverage is a proportion estimated from n points and carries
   its own uncertainty; below about thirty, the Wilson interval is wider than any
   effect worth detecting.
2. **≥ 5 of each outcome per band.** This one matters more here, and it caught a false
   positive in an earlier version of this analysis. The 0–5 per cent band at the
   one-hour horizon has n = 107 and *looks* significantly underpriced — 0.49 per cent
   quoted against 1.87 per cent realised, with a Wilson lower bound of 0.514 per cent
   that clears the mean quote. But **k = 2**: the entire result rests on two markets
   resolving Yes, and it clears the threshold by 0.02 percentage points. That is an
   artefact of a normal approximation in the extreme tail, not a finding. The rule now
   refuses a verdict on any band with fewer than five of the rarer outcome.

## Limitations, stated because they bound the conclusion

1. **Rolling ~30-day window.** The CLOB price-history endpoint serves history only for
   recently closed markets. Measured on samples of eight markets per month: closed in
   Aug 2026 → history for 8/8; Jul 2026 → 0/8; Jun 2026 → 0/8. This is a moving window,
   not an archive, so the dataset grows *forward* by re-running, never backward.
2. **Survivorship.** 90 of 300 eligible markets were dropped for lack of served history.
   That depends on closing date rather than on size, but it has not been proven harmless.
3. **Observations are not independent.** Several markets typically belong to one event
   ("who will be X") and are mutually exclusive, so the effective sample is smaller than
   the row count and every interval here is optimistic.
4. **Mid-quotes, not executable prices.** Spread and fees are not modelled; nothing here
   is a tradable edge.
5. **Polymarket only.** Kalshi was tried first and its API is not reachable from a UK
   connection (TLS handshake failure), so no cross-venue comparison is claimed.

## What would actually answer the question

Keep harvesting forward. One month gives 529 observations of which roughly half are
longshots; six months of accumulation would put the 15–85 per cent bands past both
sample-size floors, at which point the reliability curve becomes testable where it
matters. `harvest.py` is written to be re-run weekly and appended.

## Running it

```bash
python3 harvest.py --days 30 --min-volume 10000   # -> observations.csv, markets.csv
python3 analyse.py                                # -> results.txt, reliability.png
```

No dependencies beyond the standard library, except matplotlib for the figure.

## Files

| File | What it is |
|---|---|
| `harvest.py` | Pulls resolved markets and the price path preceding them; documents the API constraints it works around |
| `analyse.py` | Reliability bands with Wilson intervals, Brier score with Murphy decomposition, both sample-size rules |
| `observations.csv` | One row per (market, horizon): quoted probability, realised outcome |
| `markets.csv` | One row per market: question, category, volume, settlement |
| `results.txt` | Full output of the analysis |
| `reliability.png` | The figure above |
