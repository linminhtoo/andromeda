#!/usr/bin/env python3
"""Apply manual faithfulness labels for open200 fail calls."""

from __future__ import annotations

import csv
from pathlib import Path

AUDIT_CSV = Path("agent_logs/judge_audit_faithfulness_open71_single100_open200_20260218.csv")
RUN_TOKEN = "open_diverse200_iter0_baseline"
JUDGE_ID = "faithfulness_v1"

# Manual labels: human_label 0=pass/judge error, 1=genuine fail.
MANUAL_LABELS: dict[str, tuple[str, str]] = {
    "08e9cf9f-a9cf-47a2-b729-e29d2e57c09f": (
        "0",
        "Judge over-penalized; core dependency claims are supported by cited chunks.",
    ),
    "0d540a31-7857-4101-bdf3-92808e72e393": (
        "0",
        "Mostly grounded; margin-resilience interpretation is acceptable inference from cited cost benefits.",
    ),
    "1c28a07b-52d4-405d-b235-4b2b32d5ac19": (
        "0",
        "Temporal caveat is explicit; strategy summary is grounded in cited filing text.",
    ),
    "26ec7ff1-f41a-4bbc-960b-d22698fee075": (
        "0",
        "Answer explicitly scopes limits and uses cited evidence; judge was too strict on 2026 framing.",
    ),
    "26f80524-bfe4-4acf-9e83-72a2f897803c": (
        "0",
        "Core bottlenecks are supported; no clear material hallucination.",
    ),
    "2ee9cb47-b4d1-413d-b40c-911c80a03066": (
        "0",
        "Growth-driver synthesis from historical + forward-looking filings is acceptable and cited.",
    ),
    "347f619c-0ffc-4b97-8ff0-d7d0e1233ee2": (
        "0",
        "Single phrase-level overreach is peripheral; main demand framing is grounded.",
    ),
    "36a523a4-9c28-447c-a31c-f84d24e8c82d": (
        "0",
        "Answer clearly states risk factors are carried forward; judge over-penalized period framing.",
    ),
    "3b0e3563-d990-49e2-b752-5d4669919918": (
        "0",
        "Evidence and numerics align; no material unsupported claim identified.",
    ),
    "3f21a340-59f4-4098-a0b8-c9b96c084390": (
        "1",
        "Material numeric error: dividend total in 2025 is miscomputed (1.325B vs ~3.43B), affecting core claim.",
    ),
    "44e1358d-9beb-4a42-947c-6c185aff9bcd": (
        "0",
        "Mostly grounded with explicit period context; judge over-penalized temporal wording.",
    ),
    "47f47fa1-45a2-4eb3-b84f-c1a90823441b": (
        "0",
        "23.7B is presented as approximate implication and paired with explicit uncertainty caveat.",
    ),
    "4b4be128-5d31-4eb0-be25-d8212e9d1a53": (
        "0",
        "Citation-granularity criticism is not a material faithfulness breach; core risks are supported.",
    ),
    "54216e03-19a3-4564-ae97-8222b0de8d8d": (
        "0",
        "Huawei-specific omission is minor/peripheral; core bottleneck analysis is grounded.",
    ),
    "59c71bf5-5dc6-47f2-bcc1-2f175f888729": (
        "0",
        "Q3/Q4 wording issue is minor; overall demand-trend signals are supported by citations.",
    ),
    "62886489-6c37-4029-bdf9-403714c0438d": (
        "0",
        "Question asks for dependencies; inferred dependencies with evidence are acceptable.",
    ),
    "662cc929-178c-42b7-aea8-66713c0b78ff": (
        "0",
        "Grounded evaluation with explicit scope caveat; judge explanation itself confirms support.",
    ),
    "6bf20116-3058-4606-bcff-2026fba643b4": (
        "0",
        "Narrative from tabular evidence is reasonable synthesis, not material hallucination.",
    ),
    "780fe54e-fa1e-4b18-a4e0-69bb6809e148": (
        "0",
        "Cited strategy and long-term commitment evidence is present in retrieved context.",
    ),
    "79d76244-61a9-48a1-83a9-b1f7b8fd6fec": (
        "0",
        "Mixed period framing and one citation-format issue are minor relative to supported core claims.",
    ),
    "7ef5a9a5-4fd4-4908-80c0-2ac9936f5307": (
        "0",
        "Debt/14A/government-incentive evidence exists in context; judge missed available support.",
    ),
    "8aab67b2-f74d-4c2e-b200-472de1839827": (
        "0",
        "Segment and end-market drivers are directly supported by cited filing excerpts.",
    ),
    "9b002d32-3b2e-4c0f-a984-568b694f0f81": (
        "0",
        "Answer explicitly constrains to 2025 due context limits; no material unsupported fact.",
    ),
    "9b31da67-cb96-49e6-8036-8f3c903083b5": (
        "0",
        "Supported-vs-uncertain structure is grounded and appropriately caveated.",
    ),
    "a94a6f5c-a23e-4f9a-b3eb-5dd9b9dd9697": (
        "0",
        "Evaluative conclusion is supported synthesis for this open-ended question type.",
    ),
    "b2a9a8c5-c747-4241-90d2-9d057a130e4f": (
        "1",
        "Material logic/numeric error: claims operating margin 'improved/expanded' while cited values show decline (~42% to ~41%).",
    ),
    "b6968dd9-e144-4ae4-a670-918768cd2c14": (
        "0",
        "Risk list is grounded in cited filings; no material unsupported claim identified.",
    ),
    "b8e5d8b3-1109-421b-9f10-065f6ed4f885": (
        "0",
        "Context is empty and answer appropriately refuses; no fabricated company facts.",
    ),
    "b9318abf-9659-418a-948c-ede8b1f9c91f": (
        "0",
        "Plan-vs-outcome caveat is explicit; capital-allocation discussion remains grounded.",
    ),
    "c6d58af2-5b51-4bec-9daa-05df68734f58": (
        "0",
        "Competitive-positioning thesis is evidence-backed; no material hallucination found.",
    ),
    "cd87db11-396f-433a-a829-38ad0b2a0249": (
        "1",
        "Material contradictions and unsupported ranges (e.g., 20% attribution and 96-101/75-78 claims) vs cited filings.",
    ),
    "cff5865d-1ba5-4b84-a2ba-70e575a4f6bc": (
        "0",
        "Bull-vs-bear synthesis is largely evidence-aligned; no material unsupported core claim.",
    ),
    "d0246b83-d914-4f24-9711-e1c3106e20a3": (
        "0",
        "Key numerics (revenue/op income table values) are present in retrieved context.",
    ),
    "d6125077-0b78-4959-be5f-0064349b7e34": (
        "1",
        "Material numeric mismatch: cites 46.6M capex where cited context reports 13.2M.",
    ),
    "db13815c-6313-497c-9509-3446ca42f734": (
        "0",
        "Answer clearly scopes to available half-year data; judge over-penalized timeframe phrasing.",
    ),
    "de72e5a3-c80c-4fb5-9a53-9df84fd595ff": (
        "0",
        "Filing-date vs period semantics are handled; demand framing remains grounded.",
    ),
    "e4b72bd2-3f80-4550-972e-18aa4ea2d369": (
        "0",
        "Execution-dependency framing is valid synthesis from cited operational risks.",
    ),
    "e6ac85a6-3b08-4dd2-95d4-59f108d75585": (
        "0",
        "Answer explicitly states 2026 specifics are unavailable and uses cited 2025 evidence.",
    ),
    "e7885c55-88ef-46e0-9b60-7117553f3d6d": (
        "0",
        "Quoted reorganization statement is present; ambiguity around future effective date is not material.",
    ),
    "ebeefaf7-efda-49d9-af68-d7abcbf145f6": (
        "0",
        "Explicitly states full-year 2025 data limits; analysis remains grounded in cited results.",
    ),
    "f1a40168-e278-4d98-9aab-fa184f3c31af": (
        "0",
        "Answer includes explicit 2026-limit caveat; strategy summary is grounded in filing evidence.",
    ),
    "f1efb2be-f9d9-4c0c-b63e-1e83a04996ee": (
        "0",
        "Partial-year segment synthesis is supported by cited disclosures; no clear fabrication.",
    ),
    "f9126ba0-b564-4d45-87dd-484099d3af12": (
        "0",
        "Speculative R&D absence comment is peripheral; core capital-allocation evidence is grounded.",
    ),
}


def main() -> None:
    rows = list(csv.DictReader(AUDIT_CSV.open("r", encoding="utf-8", newline="")))
    if not rows:
        raise SystemExit(f"No rows found in {AUDIT_CSV}")

    fieldnames = list(rows[0].keys())
    if "human_label" not in fieldnames:
        fieldnames.append("human_label")
    if "human_notes" not in fieldnames:
        fieldnames.append("human_notes")

    found: set[str] = set()
    updates = 0
    for row in rows:
        run_name = row.get("run_name") or ""
        judge_id = (row.get("judge_id") or "").strip()
        qid = (row.get("query_id") or "").strip()
        pred = (row.get("judge_prediction") or "").strip()
        if RUN_TOKEN not in run_name or judge_id != JUDGE_ID or pred != "1":
            continue
        if qid not in MANUAL_LABELS:
            raise SystemExit(f"Missing manual label mapping for {qid}")
        label, note = MANUAL_LABELS[qid]
        row["human_label"] = label
        row["human_notes"] = note
        found.add(qid)
        updates += 1

    missing = sorted(set(MANUAL_LABELS) - found)
    if missing:
        raise SystemExit(f"Manual label IDs not found in audit CSV: {missing}")

    with AUDIT_CSV.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)

    fail_count = sum(1 for qid in found if MANUAL_LABELS[qid][0] == "1")
    print(f"Updated rows: {updates}")
    print(f"Manual labels applied: {len(found)}")
    print(f"Genuine fails labeled: {fail_count}")


if __name__ == "__main__":
    main()
