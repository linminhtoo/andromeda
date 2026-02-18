# Methodology Critique (Devil's Advocate): Andromeda Financial RAG

This document is intentionally harsh. It is written for interview preparation: to anticipate what a skeptical forward-deployed engineer (FDE) hiring manager, a principal engineer, or a security reviewer might say after a fast read of this repo.

The critique is mostly about *methodology*: how you decide what to build, how you validate it, how you know it works, and what could go wrong in production. It references concrete design choices in this codebase (planner, tools-first orchestration, Postgres hybrid retrieval, eval harness) and supports several claims with external literature and standards.

## 0) Executive Summary (What A Skeptic Would Say)

- **The system is too prompt- and heuristic-driven for a “production-grade” claim.** Core routing and behavior hinges on brittle keyword detectors and a planner prompt. The methodology is “ship a clever prompt, then patch failures”, not “define measurable invariants, instrument, and iterate under controlled assumptions.”
- **Evaluation is impressive in structure but still dangerously judge-led.** The system relies heavily on LLM-as-a-judge, which is known to have systematic biases (position, verbosity, agreeableness, self-enhancement). Manual audits help, but the methodology can still select for “what the judge likes,” not “what users trust.” The reliability set is small and may not estimate real-world risk.
- **The system is not robust to adversarial or simply messy real inputs.** Prompt injection, policy/guardrails, and output sanitization are not treated as first-class engineering concerns, despite OWASP explicitly ranking these as top risks for LLM apps.
- **There’s an implicit mismatch between the product claim (“SEC-grounded investor QA”) and the tool stack.** You mix SEC filings with yfinance snapshots, yet don’t formalize a data provenance contract or resolve conflicts rigorously. In finance, “probably correct” is unacceptable.
- **The open-ended/no-ticker problem is not an edge case, it’s the core UX gap.** If the user can’t ask “find me a candidate” or “screen the universe,” the system is a demo that requires insider knowledge (tickers) rather than an analyst assistant.

If someone is really trying to tear it apart, they’ll argue: “This is a solid research prototype with good engineering instincts, but the methodology still has the classic RAG pitfalls: brittle routing, non-rigorous evaluation, missing threat model, and unclear production invariants.”

## 1) Methodology Critique: The Big Patterns

### 1.1 “Heuristic-First” As A Hidden Core Dependency

The repo’s behavior is governed by a large set of string/regex heuristics:
- narrative detection (`_question_mentions_filing_narrative`)
- numeric-intent detection (`_question_is_simple_numeric_metric`)
- comparison detection (`_question_mentions_comparison`)
- date window inference (`_infer_filing_date_window_from_question`)
- narrative query expansion (`narrative_retrieval_queries`)
- chunk-type inference for “risk vs growth” coverage enforcement

These heuristics:
- **Create brittle decision boundaries.** Users rephrase; your detectors silently flip execution plans.
- **Encourage whack-a-mole iteration.** You’ll patch new tokens as failures appear, increasing complexity and reducing explainability over time.
- **Will not transfer to new customers.** One customer’s internal jargon, one sector’s idioms, or one new query template breaks routing.

Devil’s advocate conclusion: *You built a set of ad hoc classifiers without training data, calibration, or drift monitoring.* That is not an acceptable methodology once you claim production intent.

Concrete example:
- A question like “Is NVDA undervalued?” triggers market/valuation tokens and routes to tools; a question like “What are the key risks that could derail NVDA’s long-term thesis?” forces RAG and disables tools. But many real questions are mixed: valuation *and* filing evidence, and your routing makes that a hard dichotomy rather than a controlled blend.

### 1.2 The System Is “Prompt-Programmed” More Than “Policy-Programmed”

The repo is disciplined about citations and evidence in prompts, but that is not the same as enforcing invariants.

As a skeptic:
- Prompts are **soft constraints**. They will be violated under long contexts, confusing questions, or model changes.
- You lack a **hard correctness layer** for key claims (numbers, time period, entity, and causality).

The roadmap hints at claim-level checks, but the current methodology still trusts the generator to self-police.

Relevant literature: hallucination and grounding are persistent issues in LLMs and RAG systems; retrieval reduces risk but does not eliminate it, and verification layers are often needed for high-stakes settings. See RAG (Lewis et al., 2020) and surveys on hallucination. [1] [2]

### 1.3 “LLM-As-Judge” Drives Iteration, But Judges Are Biased

This repo’s eval framework is a strength, but a devil’s advocate will go straight for the weak point: **judge reliability**.

Known issues:
- LLM judges show **position and verbosity bias**, and other systematic effects. [3] [4] [5]
- Judge design choices materially change reliability. [6]
- Even “aligned” judge frameworks like G-Eval note bias toward LLM-generated text and only moderate correlation with humans in some settings. [7]

Methodology critique:
- If your primary optimization loop is “reduce judge fail-rate,” you risk building a system that is better at satisfying *that* judge prompt than satisfying customers.
- Manual audits help, but unless you measure false negatives (passes that should fail), you can still ship regressions that the judge misses.

More devilish critique: your judge policy can become a *shadow product spec*. Teams will optimize toward it because it is cheap and scalable, even when it is subtly misaligned with human trust (especially in finance where “confidently wrong” is worse than “uncertain but honest”).

Supporting evidence:
- LLM judge bias is empirically documented (MT-Bench; systematic position bias; broader bias catalogs). [3] [4] [5]
- Judge prompt and protocol design choices materially affect reliability. [6]

### 1.4 Long Context Is Treacherous, But Your Approach Leans On It

The system uses very large token budgets (draft_max_tokens/final_max_tokens) and builds long contexts. That’s tempting, but long context performance is not robust: models are empirically worse at using evidence in the middle of long contexts (“lost in the middle”). [8]

Methodology critique:
- You’ve chosen a “more context is better” default, but the literature suggests you should expect *position sensitivity*, *evidence dropout*, and *spurious synthesis*.
- You mitigate with reranking, MMR diversity, and narrative query expansion, which is good, but you don’t have a formal evidence prioritization scheme (e.g., claim-level evidence selection, explicit quote extraction, or NLI-based verification).

Devil’s advocate add-on: long context also makes failures harder to diagnose. When an answer is wrong, you don’t know whether it’s:
- retrieval failure (missing evidence),
- context packaging failure (evidence present but buried),
- synthesis failure (evidence present and salient, but model still hallucinates),
- or evaluation failure (judge fooled).

Without a decomposed methodology (retrieval metrics + evidence utilization + claim verification), long-context systems tend to produce “mysterious” failures that waste engineering cycles.

### 1.5 The Core Risk: Overreliance In A High-Stakes Domain

In finance, the dangerous failure isn’t “the model is sometimes wrong.” It is:
- the model is *plausible*, *confident*, and *actionable* while being wrong,
- users stop checking sources after initial trust is established,
- a rare but catastrophic error dominates real-world harm.

Overreliance is explicitly called out in LLM application risk guidance (OWASP). [16]

Separately, work like TruthfulQA demonstrates a general phenomenon: larger/more fluent models can still be less truthful and can mimic common misconceptions in persuasive ways. [20]

## 2) Architecture Critique (What’s Methodologically Risky)

### 2.1 The Planner Is A “Thin Waist” That Can Break Everything

The planner outputs JSON and selects:
- action (answer/clarify/refuse)
- tickers
- tool mix (rag/yfinance/edgar)
- multi-ticker flags

This is an elegant interface, but methodologically:
- The planner is a **single point of failure**. A minor model update or a slightly different prompt changes the entire execution plan.
- There is no independent, measurable accuracy target for the planner. You don’t treat planning quality as a metric with a labeled dataset and regression tests.
- The fallback inference is simplistic (regex + company name matching). This will fail on ambiguous names, synonyms, ADRs, dual listings, or common English tokens that look like tickers.

Devil’s advocate: you replaced deterministic business logic with an LLM gatekeeper, but you didn’t add the engineering scaffolding (monitoring, calibration set, drift alarms) that makes this safe.

### 2.2 Tools-First Is A Great Idea With A Missing Contract

Tools-first is a valid pattern (similar spirit to ReAct-style “act then reason”). [9]

But a skeptic will note:
- Tool outputs (yfinance and EDGAR financials) are not treated as first-class “facts with provenance.” They’re just concatenated into “Tool Context,” which the model can misuse.
- You don’t resolve contradictions. If EDGAR-derived values disagree with yfinance or with filing narrative, the model is left to “reason it out” with no deterministic policy.
- In finance, “the model blended two numbers” is a catastrophic failure mode.

### 2.3 Configuration Sprawl Creates “Non-Reproducible Reproducibility”

The repo tries to be reproducible via profiles and run artifacts, but actual behavior is mediated by a large surface of env vars:
- model endpoints, model names, provider type
- Postgres schema, sparse method, ANN knobs
- context strategy knobs
- tool enable/disable gates
- eval runner concurrency/timeouts

Devil’s advocate: you can run the “same” experiment twice and silently differ in:
- model version behind `*-latest`,
- tokenizer behavior,
- database state (indexes, vacuum, dead tuples),
- external tool behavior (SEC/yfinance availability),
- concurrency scheduling (thread/process differences).

Methodology fix is not “more logs.” It’s a minimal experiment manifest that pins:
- model IDs + versions,
- git commit,
- Postgres version + extensions,
- corpus snapshot hash,
- and stable seeds where applicable.

### 2.4 “Narrative Mode Disables Tools” Is Too Blunt

In `resolve_tool_usage_from_decision`, narrative queries disable finance tools to avoid mixing external facts. That’s philosophically clean, but practically:
- Users routinely want *both*: what filings say *and* what markets priced in.
- A production assistant should include an explicit “external data” section, not pretend market data doesn’t exist.

Methodology critique: this hard split forces an unnatural UX and pushes the model to improvise narrative explanations without the balancing context that a real analyst would consult.

## 3) Retrieval Methodology Critique

### 3.1 Hybrid Retrieval Is Sound, But The Implementation Has Sharp Edges

You implement dense + sparse hybrid retrieval with weighted RRF fusion. That’s a reasonable approach and well supported by IR literature:
- BM25 and probabilistic relevance have deep foundations. [10]
- RRF has evidence as a robust fusion method. [11]
- HNSW is a standard ANN index with known trade-offs. [12]

Devil’s advocate concerns:
- **Fixed top-k budgets** are a hidden assumption. Retrieval should be adaptive to query ambiguity and time budgets, otherwise you either waste latency or miss evidence.
- **Sparse query formulation is naive** (`plainto_tsquery` for FTS, and `to_bm25query` for BM25) and may underperform on financial jargon, abbreviations, and numeric-heavy queries (tables, line items).
- **Filter surface is narrow** (ticker/date). Real filing analysis needs filtering by form (10-K vs 10-Q), section, and possibly XBRL concept.

### 3.2 Finance-Specific Retrieval Pitfalls (Numbers, Tables, Units)

Devil’s advocate perspective: “Your retrieval stack looks like a generic text QA system, but finance QA is weird.”

Typical failure modes:
- Numeric questions are answered from tables where units are implicit (thousands/millions) and time basis is ambiguous (QTD/YTD/FY).
- Sparse retrieval often degrades on alphanumeric line items and accounting labels.
- A system can retrieve the right table but still answer with the wrong scale or period. Your prompts warn about this, but the methodology is still “warn and hope” rather than “verify and enforce.”

Related work on generation faithfulness shows that unfaithful outputs occur even when source evidence is available, motivating explicit verification rather than prompt-only discipline. [21]

### 3.3 Index/Runtime Compatibility Is Good, But Portability Is Fragile

Methodologically, the runtime compatibility checks around sparse method (bm25 vs fts) are good safety engineering.

But:
- BM25 depends on Postgres extensions and version-specific behavior. The `.env.example` warns about pg_textsearch “on PG17/18,” which is already a portability risk.
- HNSW in pgvector has operational issues around dead tuples and recall loss unless vacuum/maintenance is handled. [13]

Devil’s advocate: you’re claiming production constraints, but the retrieval stack still requires careful DBA hygiene and version constraints you don’t enforce as SLOs.

### 3.4 “More Chunks + Rerank” Is Not A Full Evidence Strategy

Reranking is a good step, but evidence selection for long-form answers is not solved by reranking alone:
- You can retrieve relevant chunks but still synthesize unsupported claims.
- You can retrieve contradictory chunks and the model may resolve them incorrectly.

Methodology critique: you need an explicit “evidence-to-claim” mapping or verification loop, not just a bigger retrieval budget.

Related research directions:
- Self-RAG argues for adaptive retrieval and self-reflection rather than fixed retrieval. [14]
- “Lost in the Middle” suggests strong pressure to prioritize evidence positions and reduce long-context dependence. [8]
- RAG evaluation work (RAGAS) explicitly decomposes retrieval quality and answer faithfulness as separate axes, rather than treating the final answer as the only outcome. [22]

### 3.5 Hybrid Fusion Is Defensible, But Not Calibrated

Weighted RRF fusion is robust and widely used in IR. [11]

Devil’s advocate question: why these weights, these k’s, and these candidate budgets for this domain?
- You have some chunk-size experiments, but not a systematic “retrieval frontier” methodology across alpha, rrf_k, sparse method, and top-k settings.
- You do not report confidence intervals for these deltas. Small changes can be noise under LLM stochasticity.

A skeptic will say: you have knobs and some experiments, but you don’t have a principled hyperparameter selection method or statistical treatment of variance.

## 4) Prompting And Citation Methodology Critique

### 4.1 Citation Format Is Developer-Friendly, Not Analyst-Friendly

Citations like `[doc=... chunk=...]` are great for debugging, but:
- Real analysts want citations they can click and read in a “source viewer” with clear section headers and line ranges.
- Chunk IDs are not stable from a user standpoint if chunking changes.

Methodology critique: you optimized for internal auditability, not end-user trust ergonomics.

### 4.2 The “Hedge Fund / Investment Banking Analyst” Persona Is A Risk

Your system prompt frames the assistant as a “principal investment banking analyst leading a top-tier hedge fund.” This:
- biases the model toward confident, narrative-heavy outputs
- may increase verbosity and rhetorical flourish
- can create the *appearance* of expertise without adding factual reliability

Devil’s advocate: the persona increases reputational and compliance risk because it pushes toward authoritative tone in a domain where overconfidence is costly.

### 4.3 Token Budgeting Uses Crude Approximations

Some context building uses a char-based heuristic (tokens ~= chars/4). That’s common in prototypes, but methodologically weak:
- Tokenization varies by model and language; table-heavy content breaks the approximation.
- You risk truncating key evidence or including too much irrelevant context.

### 4.4 “Explain Your Work” Is Requested, But Not Mechanized

Your prompts request careful citations and even quotes in narrative mode, but the system does not:
- extract material claims,
- bind each claim to one or more evidence spans,
- and validate that those spans actually entail the claim.

Devil’s advocate: the current approach can degrade into “generate a persuasive report and sprinkle citations,” which is precisely what skeptical users fear from LLM systems.

## 5) Evaluation Methodology Critique (The Big One)

### 5.1 You Have Evals, But Are They The Right Evals?

Your eval runbook is strong operationally, but a skeptic will ask:
- Do the eval queries represent *customer distribution* or *developer imagination*?
- Are you measuring what matters (decision usefulness, correctness under constraints, failure severity), or just judge-aligned metrics?

Holistic evaluation frameworks (e.g., HELM) emphasize broad scenario coverage, multi-metric measurement, and explicitly naming what you are *not* measuring. [15]

Devil’s advocate: you have a narrow but well-instrumented set; you may still be blind to the failure modes that get you fired in production (misleading but fluent answers, silent ticker mismatch, subtle period errors).

### 5.2 Dataset Generation Risks Leakage And Overfitting

Eval query generation is derived from your corpus exports and templates. That is pragmatic, but it risks:
- **benchmark leakage**: prompts may resemble training-like patterns for your own system and your own prompt templates
- **overfitting to retrieval artifacts**: you might tune chunking/retrieval to “match the eval generator”

Methodology critique: you need an external validation set (human-written queries, real analyst questions, “red team” prompts) that is not produced by your own generation templates.

### 5.3 LLM-Judge Is Useful, But You Need A Statistical Story

You do some reliability auditing, which is excellent. But a skeptic will push harder:
- Reliability sets are small; confidence intervals might be wide.
- Labeling only fails inflates your ability to detect false positives but tells you little about false negatives.
- The same family of models as generator/judge can create correlated biases (self-enhancement). [3]

Supporting literature:
- MT-Bench (Zheng et al.) discusses judge biases (position, verbosity, self-enhancement). [3]
- Position bias in LLM judges has been studied systematically. [4] [5]
- More recent work suggests “design choices” matter and nondeterministic sampling may align better in some contexts. [6]

### 5.4 “Pass/Fail” Rubrics Hide Severity

Binary fail rates collapse a spectrum:
- a minor citation mismatch vs a wrong numeric claim vs a wrong ticker are not the same
- finance customers care about *severity-weighted* errors

Methodology critique: you should track severity classes and “catastrophic failure rate,” not only average fail-rate.

### 5.5 Missing “Negative Controls” For Judge Gaming

A devil’s advocate will ask:
- Do you have tests where the answer is rhetorically persuasive but wrong, to see if the judge is fooled?
- Do you test prompt injection or “excessive agency” scenarios?

OWASP explicitly calls out prompt injection, insecure output handling, model DoS, and overreliance. [16]

### 5.6 You Don’t Measure The RAG Pipeline, You Measure The Final Story

From a methodology standpoint, “answer quality” is an end result of multiple subsystems:
- planning
- retrieval
- reranking
- context packing
- synthesis
- postprocessing

This repo logs a lot, but the evaluation still mainly reduces to “final answer judged pass/fail.”

A skeptic will push for decomposed metrics:
- retrieval coverage (did we retrieve the right doc/section/table?),
- evidence utilization (did the answer actually use the retrieved evidence?),
- contradiction handling (did the answer reconcile conflicting chunks correctly?),
- and claim-level consistency (numbers/period/ticker).

Frameworks like RAGAS exist precisely to break RAG evaluation into retrieval vs generation components, because optimizing the final answer alone tends to hide root causes. [22]

### 5.7 No Significance Testing, Multiple-Comparisons Controls, Or Variance Reporting

Your logbook culture is good, but a skeptic will still ask for rigor:
- When you try many prompt tweaks and keep the best, you are implicitly doing multiple hypothesis tests.
- With small eval sets, you can “discover” improvements that are pure noise.

Minimum methodology:
- run repeats and report variance (or bootstrap confidence intervals),
- freeze a true holdout set,
- treat small deltas as non-actionable unless they replicate.

## 6) Data Source And Ingestion Methodology Critique

### 6.1 EDGAR Ingestion Is Operationally Sensitive

SEC rate limits and user-agent requirements are explicit. [17] [18]

Your downloader script has:
- a hard-coded user agent string (including a personal email)
- simple delays and minimal error/backoff shaping

Devil’s advocate: as soon as you run this at any scale (multiple users, multiple tickers, retries), you risk violating SEC policies or getting throttled, and you don’t have an operational plan for that.

### 6.2 yfinance Is Not A Production Data Source

yfinance explicitly states it is not affiliated with Yahoo, is intended for research/educational use, and Yahoo’s APIs are for personal use. [19]

Methodology critique:
- Using yfinance in a product story for enterprise finance customers invites legal/compliance pushback.
- Even for demos, you should present it as a placeholder with an abstraction that supports a licensed market data provider.

### 6.3 No Freshness / Staleness Semantics

The system doesn’t formalize:
- when filings were last ingested
- what coverage window exists per ticker
- whether “latest” means latest filing date or latest period end date

Methodology critique: this is a major trust defect for analysts. The assistant must surface staleness, coverage, and missingness explicitly.

### 6.4 Filings Are Not “Just Text”

SEC filings contain structured financial statements (XBRL concepts), defined accounting policies, reconciliation tables, and repeated boilerplate.

Devil’s advocate: the pipeline is largely “HTML -> markdown -> chunks -> embeddings,” which throws away:
- concept-level structure,
- unit normalization,
- statement rollups,
- and cross-form comparability.

That forces the LLM to recover structure from flattened text, which is precisely where hallucinations and period/scale errors creep in.

## 7) Security, Privacy, And “FDE Reality” Critique

### 7.1 Threat Model Is Missing

Even if this is a side project, an FDE role will expect you to reason about deployment and adversarial inputs.

OWASP Top 10 for LLM Apps is a reasonable baseline. [16]

Immediate gaps:
- Prompt injection: no explicit hardening for “ignore previous instructions / reveal system prompt / exfiltrate” beyond generic prompt wording.
- Insecure output handling: tool outputs are blindly passed into the model context. If tool output contains adversarial text, the model can be steered.
- Model DoS: very large token budgets and high concurrency settings create easy latency/cost blowups.

### 7.2 No Authentication / Authorization / Data Governance

From a production lens:
- API endpoints are open, CORS allows all origins.
- History endpoints imply persistent storage but no auth boundary.

Devil’s advocate: this is a non-starter for enterprise deployments and should be clearly labeled as “demo-only.”

### 7.3 Supply Chain And Remote Code Risks (Often Overlooked)

Devil’s advocate security reviewer will look for:
- model loading paths that allow remote code execution (for example, `trust_remote_code=True` patterns),
- dependencies with large transitive trees,
- and runtime downloads without pinning/hashes.

Even if you don’t treat this as production, FDEs are expected to anticipate “customer security review” objections early.

## 8) “Production-Grade” Claims That A Skeptic Will Challenge

If you say “production-grade constraints,” a skeptic will ask:
- Where are the SLOs and error budgets? (Roadmap mentions them; runtime doesn’t enforce them.)
- Where is the on-call story, triage playbook, incident taxonomy?
- Where is the model/version rollout and rollback strategy tied to eval gates?
- Where is the cost model and caching strategy (prompt caching, retrieval caching), beyond mention in FUTURE_WORKS?

Methodology critique: the repo has the right direction, but the “production-grade” claim is aspirational unless you add operational contracts and guardrails.

## 9) What To Fix First (If You Want The Critique To Be Actionable)

Devil’s advocate doesn’t just complain; they demand priorities.

### 9.1 Replace Heuristics With Measured Classifiers (Or At Least Calibrate Them)

- Create a labeled dataset of routing decisions (numeric vs narrative vs mixed vs comparison vs screening).
- Measure planner accuracy separately from answering quality.
- Keep heuristics as fallbacks, not primary policy.

### 9.2 Add A Claim-Level Verification Layer For “Material Claims”

Start small:
- extract numeric claims + time periods + tickers from the draft
- verify against tool outputs and/or retrieved snippets
- fail closed on key mismatches

This aligns with the roadmap, and it addresses hallucination risk more directly than prompt tightening. (Self-RAG style reflection loops point in this direction.) [14]

### 9.3 Judge Reliability: Expand Human Labels And Add Adversarial Controls

- Label a random sample of “passes” to estimate false negatives.
- Add judge bias checks (verbosity, position) inspired by MT-Bench and judge-bias studies. [3] [4] [5]
- Track confidence intervals and do not overinterpret small deltas.

### 9.4 Make “No-Ticker / Screening” A First-Class Product Feature

If you can’t answer “find me candidates,” this is not an analyst assistant.

Pragmatic MVP:
- Use ingested ticker catalog as the universe
- use sector classification + simple valuation heuristics + filing-backed justification
- output top 3 with transparent scoring and missing-data flags

Also: stop relying on yfinance for this in any enterprise story; abstract it behind a provider interface. [19]

### 9.5 Security Baseline

At minimum:
- explicit prompt injection tests
- sanitize tool output channels
- add rate limiting and request caps
- document OWASP LLM Top 10 mapping and mitigations. [16]

### 9.6 Add A “Human Trust” Methodology Layer

A devil’s advocate hiring manager will care whether you can do the FDE loop:
- sit with a customer,
- watch them use it,
- log what broke their trust,
- translate that into measurable engineering work.

Pragmatic moves:
- build a “trust friction” rubric (when did the user stop believing? why?),
- track “citation clickthrough” and “user correction rate,”
- add structured “coverage/missingness” statements in every answer.

## Appendix A: Failure Mode Inventory (What Breaks In The Wild)

This is the “tear it apart” list: a high-volume inventory of failure modes a skeptical reviewer will assume exist unless you can demonstrate otherwise.

### A.1 Planning And Routing

- Mixed-intent questions get hard-switched into the wrong route (tools-only vs RAG-only).
- Ambiguous company names or synonyms fail ticker inference.
- Multi-entity questions collapse into single-entity answers.
- Clarification is overused (bad UX) or underused (silently wrong target).
- “Latest” is interpreted inconsistently (filing date vs covered period).

### A.2 Retrieval

- Boilerplate dominates (risk factors, legal disclaimers), drowning signal.
- The wrong section is retrieved (MD&A vs Risk Factors vs footnotes).
- Entity bleed: irrelevant ticker chunks slip in; “ignore irrelevant chunks” is not enforceable.
- Numeric tables are under-retrieved or mis-ranked by both sparse and dense methods.
- Contradictory evidence is not surfaced; the model overcommits to one side.

### A.3 Period, Scope, And Accounting Semantics

- Filing date vs period end date confusion persists for year-scoped questions.
- Quarterly and annual numbers are mixed without explicit basis statements.
- Units are wrong (thousands/millions/billions) or per-share vs total is mixed.
- GAAP vs non-GAAP is blended or treated as interchangeable.
- Directionality errors (“up” vs “down”) and small arithmetic mistakes become material.

### A.4 Tools And External Data

- yfinance fields are missing/stale/definition-dependent; upstream changes break behavior. [19]
- Tool outputs contradict filing context; no deterministic tie-break policy exists.
- Tool output text can contain adversarial or misleading content; it is fed into the model verbatim.

### A.5 Generation And Citations

- Citation laundering: a chunk is cited that is topically related but does not support the claim.
- Quotes are not verbatim even when requested; the system doesn’t verify.
- Persona prompts push authoritative tone, increasing “confidently wrong” risk.
- Long answers become unreadable; concision is not enforced by budgets.

### A.6 Evaluation

- Goodharting: improvements are “judge wins,” not user wins (judge bias risk). [3] [4] [5]
- Variance is misread as progress; best-of-many prompt tweaks overfit the eval set.
- Template-derived evals miss real analyst phrasing and messy mixed-intent queries.
- No-ticker “screening” prompts are not covered, yet are high value in real workflows.

### A.7 Operations

- Latency cliffs from long decode and reranking; no graceful degradation policy.
- Concurrency blowups saturate local endpoints; timeouts become common.
- DB/index drift changes retrieval quality (dead tuples, vacuum, index params). [13]

## 10) References (External)

1. Lewis et al. (2020). “Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks.” https://arxiv.org/abs/2005.11401
2. Huang et al. (2023). “A Survey on Hallucination in Large Language Models: Principles, Taxonomy, Challenges, and Open Questions.” https://arxiv.org/abs/2311.05232
3. Zheng et al. (2023). “Judging LLM-as-a-Judge with MT-Bench and Chatbot Arena.” https://arxiv.org/abs/2306.05685
4. Shi et al. (2024). “Judging the Judges: A Systematic Study of Position Bias in LLM-as-a-Judge.” https://arxiv.org/abs/2406.07791
5. Ye et al. (2024). “Justice or Prejudice? Quantifying Biases in LLM-as-a-Judge.” https://arxiv.org/abs/2410.02736
6. Yamauchi et al. (2025). “An Empirical Study of LLM-as-a-Judge: How Design Choices Impact Evaluation Reliability.” https://arxiv.org/abs/2506.13639
7. Liu et al. (2023). “G-Eval: NLG Evaluation using GPT-4 with Better Human Alignment.” https://arxiv.org/abs/2303.16634
8. Liu et al. (2023/2024). “Lost in the Middle: How Language Models Use Long Contexts.” https://arxiv.org/abs/2307.03172
9. Yao et al. (2022). “ReAct: Synergizing Reasoning and Acting in Language Models.” https://arxiv.org/abs/2210.03629
10. Robertson, Zaragoza (2009). “The Probabilistic Relevance Framework: BM25 and Beyond.” https://doi.org/10.1561/1500000019
11. Cormack, Clarke, Buttcher (2009). “Reciprocal Rank Fusion outperforms condorcet and individual rank learning methods.” DOI: 10.1145/1571941.1572114 (SIGIR).
12. Malkov, Yashunin (2016). “Efficient and robust approximate nearest neighbor search using Hierarchical Navigable Small World graphs.” https://arxiv.org/abs/1603.09320
13. pgvector issue: “HNSW + dead tuples: recall loss/usability issues.” https://github.com/pgvector/pgvector/issues/244
14. Asai et al. (2023). “Self-RAG: Learning to Retrieve, Generate, and Critique through Self-Reflection.” https://arxiv.org/abs/2310.11511
15. Stanford CRFM (2022). HELM overview: “Language Models are Changing AI: The Need for Holistic Evaluation.” https://crfm.stanford.edu/2022/11/17/helm.html
16. OWASP (v1.1). “Top 10 for Large Language Model Applications.” https://owasp.org/www-project-top-10-for-large-language-model-applications/
17. SEC (2021; updated 2024). “SEC to apply new rate control limits to EDGAR websites.” https://www.sec.gov/filergroup/announcements-old/new-rate-control-limits
18. SEC. “Webmaster Frequently Asked Questions” (programmatic EDGAR access). https://www.sec.gov/about/webmaster-frequently-asked-questions
19. yfinance GitHub README (legal/personal-use disclaimers). https://github.com/ranaroussi/yfinance
20. Lin, Hilton, Evans (2021). “TruthfulQA: Measuring How Models Mimic Human Falsehoods.” https://arxiv.org/abs/2109.07958
21. Maynez et al. (2020). “On Faithfulness and Factuality in Abstractive Summarization.” https://aclanthology.org/2020.acl-main.173/
22. Es et al. (2023). “RAGAS: Automated Evaluation of Retrieval Augmented Generation.” https://arxiv.org/abs/2309.15217
