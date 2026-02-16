# query
please have a look at _enforce_ticker_coverage() Basically, i have a RAG pipeline over SEC financial documents. i wanted to handle multi-ticker queries better. retrieval is done independently per ticker, then there is some merging and reranking. i find the current reranking + ticker coverage enforcement is still too naive. it results in imbalanced reranked chunks (eg for query "Compare NVDA to GOOGL as long term investments", i had 10 NVDA chunks and 2 GOOGL chunks). of course, increasing the number of top-K to select after reranking helps, but it fundamentally does not address the root problem. can u pls propose some better alternatives?

# expert answer
I looked at _enforce_ticker_coverage() in `query_runtime.py` — it’s doing the bare minimum:

pick at most 1 chunk per ticker (first from primary, else fallback)

then fill the rest with the globally best-scoring chunks (which will naturally get dominated by the “stronger” ticker)

then sort again by score (fine when len(tickers) <= limit, but if you ever have len(tickers) > limit, the final selected[:limit] can silently drop some tickers you just “ensured”)

So the imbalance you’re seeing (10 NVDA / 2 GOOGL) is expected: after the first “coverage” pass, you’re basically back to pure global top-K.

Below are better alternatives, from “drop-in improvement” → “fix the root cause”.

1) Hard quotas (min + optional max per ticker) — simplest, effective

Instead of “1 per ticker”, reserve a budget per ticker.

Typical choices:

compare / vs intent: min_per_ticker = floor(K / N) (or ceil)

non-compare multi-ticker: min_per_ticker = 1

optional cap: max_per_ticker = ceil(K * max_share) (e.g. 0.6) to prevent domination

Drop-in shape:

def enforce_ticker_quotas(primary, fallback, tickers, limit, *, min_per_ticker, max_per_ticker=None):
    combined = dedupe(primary + fallback)  # already sorted desc by score
    pools = {t: [sc for sc in combined if chunk_ticker(sc) == t] for t in tickers}

    selected = []
    counts = {t: 0 for t in tickers}
    used = set()

    # 1) reserve minimum quota
    for t in tickers:
        for sc in pools[t]:
            if counts[t] >= min_per_ticker or len(selected) >= limit:
                break
            if sc.chunk.id in used:
                continue
            selected.append(sc); used.add(sc.chunk.id); counts[t] += 1

    # 2) fill remaining with best available, respecting optional cap
    for sc in combined:
        if len(selected) >= limit:
            break
        t = chunk_ticker(sc)
        if sc.chunk.id in used:
            continue
        if t in counts and max_per_ticker is not None and counts[t] >= max_per_ticker:
            continue
        selected.append(sc); used.add(sc.chunk.id)
        if t in counts:
            counts[t] += 1

    return selected


Why this works: if K=12, N=2, a compare query can force min_per_ticker=5 or 6, and NVDA simply can’t take 10 slots.

2) Soft “fairness penalty” selection (greedy) — better than hard quotas

Hard quotas can occasionally force in junky chunks for a weak ticker. A nicer compromise is: keep global scoring, but penalize over-represented tickers while selecting.

Greedy rule:

At each step, pick chunk maximizing adjusted = score - λ * count[ticker]

or score / (1 + λ*count) if you want a multiplicative penalty

This behaves like “balanced top-K” without rigid quotas. It also naturally handles 3+ tickers.

Sketch:

while len(selected) < limit:
    best = None; best_val = -1e9
    for sc in candidates_not_used:
        t = chunk_ticker(sc)
        val = sc.score - lam * counts.get(t, 0)
        if val > best_val:
            best, best_val = sc, val
    select(best)


Practical tip: you can set λ so that being “+1 chunk ahead” costs about the typical score gap between ranks ~3–10.

3) Score normalization per ticker before merging — fixes “cross-ticker comparability”

Even with a cross-encoder reranker, scores can be systematically higher for one ticker because of:

chunk length/style differences

repetitive boilerplate that matches “investment” language well

more filings / more similar passages

Normalize within each ticker then merge:

convert score → percentile_rank inside that ticker pool

or z-score (mean/std) per ticker

Then run either:

plain top-K, or

soft-penalty selection (Option 2)

This often reduces domination without any quotas.

4) Two-stage rerank: rerank per ticker first, then rerank the union — improves balance and relevance

Right now you retrieve per ticker, but rerank once globally on the merged pile. A better structure:

For each ticker:

rerank within ticker

keep top M (e.g. M = 2 * target_per_ticker)

Union all tickers’ top-M

Run a final rerank on that union

Apply a mild balancing rule (Option 2 or small quotas)

This ensures each ticker even gets a chance in the final rerank.

5) If the user asked to “compare”: select pairs (or “matched sets”), not individual chunks

For comparison questions, the best unit often isn’t a chunk — it’s a pair of evidence items addressing the same facet.

Example facets:

revenue growth

margins

valuation

risks (regulatory, competition)

capex / R&D

guidance / outlook

Approach:

cluster / tag chunks by facet (cheap embedding + kmeans, or keyword rules)

for each facet, pick the best NVDA chunk and best GOOGL chunk

then rank facets by usefulness and take top facets

This guarantees balance and makes generation easier (“facet-by-facet compare”).

6) “Fix the root problem”: generate per-ticker briefs, then do a compare reduce step

If your actual goal is answer quality (not “a single blended top-K list”), the cleanest solution is:

Retrieve + rerank separately per ticker

Allocate context budget per ticker (tokens or chunk count)

Produce an “investment brief” per ticker (map step)

Then do the final compare answer (reduce step)

This makes the system robust even when one ticker has weak filings coverage or lower retrieval quality. It also largely eliminates the need for delicate fairness in a single list.
