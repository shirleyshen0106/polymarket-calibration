# Are Polymarket prices calibrated probabilities?

A reliability study of resolved Polymarket markets. The headline sample is **one complete
week of resolutions, 6 to 13 September 2026: 8,547 markets and 18,638 quote–outcome
pairs**, at one hour, one day, seven days and thirty days before resolution.

![reliability diagram](reliability.png)

## The question

A prediction-market price is only a probability if it behaves like one: of everything
the market prices at 70 per cent, roughly 70 per cent should happen. That is a
*reliability* question, and it is the same question I ask of my own models' uncertainty
in my PhD, where a multi-seed ensemble claiming 90 per cent coverage was found to
deliver 58.9 per cent, and split conformal prediction repaired it to 94.6 per cent
without retraining. This repository points the same discipline at market prices.

## Headline result

**Away from even odds, Polymarket prices are too extreme.** Markets quoted at 5 to 35
per cent resolve Yes more often than quoted, and markets quoted at 65 to 95 per cent
less often, at both one day and one hour before resolution. The 35 to 65 per cent band,
which holds most of the book, is consistent with its quotes.

This replaces two earlier headlines, both withdrawn below. It rests on a complete sweep
for the first time, and it comes with a caution that may yet kill it too: noisy quotes
produce exactly this shape on their own (see *What could explain it*).

| Quote taken | n | Brier | reliability ↓ | resolution ↑ | uncertainty | beats base rate by |
|---|---:|---:|---:|---:|---:|---:|
| 30 days before | 167 | 0.1189 | 0.0068 | 0.0642 | 0.1758 | 0.0569 |
| 7 days before | 3,765 | 0.2071 | 0.0013 | 0.0366 | 0.2474 | 0.0403 |
| 1 day before | 7,357 | 0.2216 | 0.0016 | 0.0251 | 0.2470 | 0.0254 |
| 1 hour before | 7,349 | 0.1876 | 0.0013 | 0.0599 | 0.2468 | 0.0592 |

**Do not read the Brier column across rows.** Different markets survive at different
horizons (only 167 have a quote a full 30 days out, because the price-history window
itself is about 30 days), so the rows are different samples. Compare reliability within
a horizon, not Brier across horizons.

Resolution is much lower than in the earlier, truncated sample. That is composition,
not a worse market: the complete week is dominated by short-dated Bitcoin up/down,
football and esports markets quoted near 50 per cent, which carry little information a
day out by construction.

## Correction, 12 September 2026: the sample was not the venue

The 7 September version of this study fixed one truncation and missed a second, larger
one. Its headline, that the market is well calibrated at one day and overpriced at
65 to 95 per cent in the last hour, described a sample that does not represent
Polymarket. That headline is withdrawn.

**What was wrong.** Gamma refuses any `offset` of 2,100 or more with HTTP 422. A window
holding more than 2,100 matching markets therefore returns exactly the first 2,100 and
then errors, and the pagination guard added on 7 September read that hard refusal as the
end of the data. Every harvest reported exactly 2,100 eligible markets, which should
have been the giveaway.

**Why it was not harmless.** Gamma returns markets in ascending id order, so the 2,100
were not a random subsample. They were the lowest-id, earliest-created markets in the
window. Measured on 12 September:

* A single 24-hour slice holds about 1,100 eligible markets, and a complete 7-day harvest
  found 8,595, so a 30-day window holds more than 30,000. The harvest saw about 6 to 7
  per cent of it.
* For the day 9 to 10 September, the complete enumeration has 1,227 markets. The
  truncated harvest captured **6** of them.
* The populations differ in kind. The complete day is dominated by short-dated recurring
  markets (Bitcoin price, football, CS2, MLS, ATP tennis) with median volume $35,896.
  The six captured were long-lived "who will" and "will" questions with median volume
  $172,844.

So the 7 September result, and the cumulative series below it, is a statement about
long-lived, early-created, high-volume questions. It may be a true statement about
those, but it is not a statement about the venue.

**The fix.** `fetch_markets` now splits the window recursively until every slice
completes on its own terms rather than against the offset cap, and deduplicates on
market id across slice boundaries. A slice that still hits the cap at the 15-minute
floor is reported as truncated. The harvest now also survives a network drop instead of
losing the run; it did not, the first time the complete harvest was attempted.

This is the second time the same function has silently under-read the window, by a
different mechanism each time, and both times the short read looked complete. The
lesson I am taking is that a sweep has to be checked against an independent count, not
just against its own error handling.

## Correction, 7 September 2026: the first version of this study was wrong

The first version of this study, published 30 August 2026, concluded that **no
probability band is testable in a one-month window**. That conclusion was an artefact
of a bug in my own harvester, not a property of the venue, and it is now withdrawn.

`fetch_markets` paginates Gamma and caught any exception from a page request as a
signal to stop, on the reasoning that Gamma 500s on deep offsets rather than returning
an empty page. It does, but it also 500s *intermittently* at shallow offsets. A
transient failure at offset 300 therefore ended the sweep silently and looked exactly
like a completed one. The harvest reported 300 eligible markets for a window that
actually held 2,100, and every downstream conclusion inherited that 7x undercount.

Two headline claims died with it:

* **"No band is testable in one month" is false.** A single complete 30-day window,
  analysed on its own, already gives a verdict in six of seven bands at the one-day
  horizon, and finds the 65–85 per cent band overpriced there. It was never necessary to accumulate forward to make the middle of the range
  testable; it was necessary to read the whole window.
* **"Half of all quotes sit below five per cent" is false.** That was 53 per cent of
  the truncated sample. In the complete sweep it is 27 per cent at the one-day horizon.
  The longshot skew is real but roughly half the size the first version reported.

The pagination bug is fixed: a failed page is now probed at further offsets before the
sweep is allowed to conclude, unrecovered gaps are recorded, and an incomplete sweep
says so loudly instead of returning a short read that looks complete. The survivorship
figures the analysis prints are now read from `harvest_stats.json` rather than
hard-coded, which is how the stale numbers survived as long as they did.

I have left this section in rather than quietly restating the result, because the
kill was the point of the exercise.

## Where the market is miscalibrated

```
RELIABILITY -- quote taken 1 day before resolution   (n = 7357)
     quoted band     n  mean quote  realised           95% CI   verdict
           0%-5%   398       1.6%      3.0% [ 1.7%,  5.2%]   market UNDERPRICED this band
          5%-15%   422       9.5%     17.8% [14.4%, 21.7%]   market UNDERPRICED this band
         15%-35%  1030      25.7%     32.9% [30.1%, 35.8%]   market UNDERPRICED this band
         35%-65%  4873      49.9%     48.8% [47.4%, 50.2%]   consistent with the quote
         65%-85%   417      73.3%     68.3% [63.7%, 72.6%]   market OVERPRICED this band
         85%-95%   113      90.3%     79.6% [71.3%, 86.0%]   market OVERPRICED this band
        95%-100%   104      98.2%     94.2% [88.0%, 97.3%]   market OVERPRICED this band
```

```
RELIABILITY -- quote taken 1 hour before resolution   (n = 7349)
     quoted band     n  mean quote  realised           95% CI   verdict
           0%-5%   980       0.6%      0.9% [ 0.5%,  1.7%]   consistent with the quote
          5%-15%   364       9.6%     14.8% [11.6%, 18.9%]   market UNDERPRICED this band
         15%-35%   818      25.5%     32.9% [29.8%, 36.2%]   market UNDERPRICED this band
         35%-65%  4137      49.9%     49.0% [47.5%, 50.5%]   consistent with the quote
         65%-85%   341      73.5%     65.7% [60.5%, 70.5%]   market OVERPRICED this band
         85%-95%   130      90.1%     77.7% [69.8%, 84.0%]   market OVERPRICED this band
        95%-100%   579      99.5%     99.1% [98.0%, 99.6%]   consistent with the quote
```

**By market family.** About 3,100 of the 7,400 observations at each short horizon are
crypto price markets, nearly all quoted between 35 and 65 per cent. Excluding them
leaves the shape intact, so it is not a Bitcoin artefact:

| 1 day before, crypto excluded | n | mean quote | realised | 95% CI | verdict |
|---|---:|---:|---:|---|---|
| 0–5% | 276 | 1.8% | 4.0% | [2.2%, 7.0%] | underpriced |
| 5–15% | 400 | 9.6% | 18.8% | [15.2%, 22.9%] | underpriced |
| 15–35% | 1,001 | 25.7% | 33.5% | [30.6%, 36.4%] | underpriced |
| 35–65% | 2,035 | 49.1% | 50.3% | [48.1%, 52.5%] | consistent |
| 65–85% | 407 | 73.2% | 68.6% | [63.9%, 72.9%] | overpriced |
| 85–95% | 105 | 90.1% | 78.1% | [69.3%, 84.9%] | overpriced |
| 95–100% | 54 | 97.3% | 88.9% | [77.8%, 94.8%] | overpriced |

Within that, sports and esports markets show it most strongly: at one day every band
from 5 to 100 per cent is miscalibrated in this direction except 35 to 65. The crypto markets on their own look slightly overpriced in the
35 to 65 band (50.4 per cent quoted, 47.6 per cent realised), but that is "Up" resolving
less often than priced during one week of Bitcoin, which is a single correlated draw, not
a calibration finding.

The 7 September version called its (smaller, truncated) version of this pattern "the
classic favourite–longshot bias". That label was backwards. The classic bias in betting
markets is longshots *overpriced*; here longshots are *underpriced* and favourites
overpriced, which is prices overshooting toward the extremes.

## What could explain it

1. **Quote noise, which would make it an artefact.** If a quote is the true probability
   plus noise, bucketing by the noisy quote sends markets with positive noise into the
   high bands and negative noise into the low bands, and outcomes then regress toward the
   middle. That is exactly this shape, with no mispricing at all. Hourly mid-quotes on
   thin books, and sports markets quoted mid-game, are noisy. This explanation has not
   been ruled out and is the first thing to test.
2. **Genuine overreaction** in fast-moving, retail-heavy markets, which would be a real
   and possibly persistent effect.

Separating them needs quotes that are less noisy for the same markets: finer history
fidelity, time-averaged quotes around each horizon, or executed trade prices. If the
shape shrinks as the quote gets cleaner, it was noise.

## Two sample-size rules, and why both are needed

1. **n ≥ 30 per band.** Coverage is a proportion estimated from n points and carries
   its own uncertainty; below about thirty, the Wilson interval is wider than any
   effect worth detecting.
2. **≥ 5 of each outcome per band.** This one still does most of the work at the tails.
   It caught a false positive in an earlier version of this analysis: the 0–5 per cent
   band at the one-hour horizon had n = 107 and *looked* significantly underpriced,
   0.49 per cent quoted against 1.87 per cent realised, with a Wilson lower bound
   clearing the mean quote by 0.02 percentage points. But k = 2. The entire result
   rested on two markets resolving Yes. The rule refuses a verdict on any band with
   fewer than five of the rarer outcome, and on the current sample it still withholds a
   verdict on both extreme bands at three of four horizons.

## The earlier, truncated series

`observations.csv` and `markets.csv` hold the merged harvests of 30 August, 7 September
and 12 September: **2,990 markets, 7,121 quote–outcome pairs**. Every one of those
harvests was truncated, so the series describes long-lived, early-created, high-volume
questions rather than the venue. It is kept, frozen, because it is the sample the
withdrawn results were computed on, and because as a description of that subpopulation
it may still be useful. It cannot be extended: the fixed harvester no longer reproduces
the truncation. Its output is in `results_truncated_series.txt` and
`reliability_truncated.png`.

## Limitations, stated because they bound the conclusion

1. **One week.** The headline rests on a single complete week of resolutions. A second,
   disjoint week is the minimum before calling the shape persistent.
2. **Rolling ~30-day window.** The CLOB price-history endpoint serves history only for
   recently closed markets (measured 30 August 2026 on samples of eight: August 8/8,
   July 0/8, June 0/8). Data cannot be back-filled; a week not harvested is lost.
3. **Survivorship is now small.** Of 8,595 eligible markets, 39 were dropped for not
   settling to a clean binary, 8 for lack of served history, and 1 to a network failure.
4. **Observations are not independent.** Crypto up/down markets on the same underlying
   and hour move together, and sports markets on one fixture are mutually exclusive, so
   the effective sample is far smaller than the row count and every interval here is
   optimistic.
5. **Mid-quotes, not executable prices.** Spread and fees are not modelled; nothing here
   is a tradable edge.
6. **Resolution time is `endDate`.** Horizons are measured back from the listed end date,
   which for some sports markets is not the moment the outcome became known.
7. **Polymarket only.** Kalshi's API is not reachable from a UK connection (TLS handshake
   failure), so no cross-venue comparison is claimed.

## Running it

```bash
python3 harvest.py --days 7 --min-volume 10000 --out observations_complete_$(date +%Y%m%d).csv --markets-out markets_complete_$(date +%Y%m%d).csv
# merge into observations_complete.csv / markets_complete.csv, deduplicating on (market_id, horizon_hours)
python3 analyse.py --obs observations_complete.csv --markets markets_complete.csv > results.txt
```

Run weekly with `--days 7` so consecutive harvests tile the timeline. With the offset cap
handled, a 30-day window is more than 30,000 markets and several hours of history requests;
a 7-day window is about 8,600 markets and a little over an hour.

No dependencies beyond the standard library, except matplotlib for the figure.

## Files

| File | What it is |
|---|---|
| `harvest.py` | Pulls resolved markets and their price paths; splits the window to get under Gamma's offset cap, and documents both truncation failures |
| `analyse.py` | Reliability bands with Wilson intervals, Brier score with Murphy decomposition, both sample-size rules |
| `observations_complete.csv`, `markets_complete.csv` | The complete sample (headline) |
| `observations.csv`, `markets.csv` | The earlier truncated series, frozen |
| `*_YYYYMMDD.csv` | Raw output of each individual harvest |
| `harvest_stats.json` | Eligible/kept/dropped counts from the most recent harvest |
| `results.txt`, `reliability.png` | Analysis of the complete sample |
| `results_truncated_series.txt`, `reliability_truncated.png` | Analysis of the truncated series |
