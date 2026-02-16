#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
from pathlib import Path


def to_float(v: str) -> float | None:
    t = (v or "").strip()
    if not t:
        return None
    try:
        return float(t)
    except ValueError:
        return None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('--csv-path', required=True)
    ap.add_argument('--run-name-prefix', action='append', default=[])
    args = ap.parse_args()

    rows = []
    with Path(args.csv_path).open('r', encoding='utf-8', newline='') as f:
        reader = csv.DictReader(f)
        for row in reader:
            if args.run_name_prefix and not any(row['run_name'].startswith(prefix) for prefix in args.run_name_prefix):
                continue
            rows.append(row)

    rows.sort(key=lambda r: r.get('timestamp', ''))

    keys = [
        'run_name', 'timestamp', 'status', 'n_ok', 'n_err', 'wall_total_ms', 'throughput_qps',
        'factual_numeric_accuracy', 'factual_correctness_fail_rate', 'factual_helpfulness_fail_rate',
        'open_ended_faithfulness_fail_rate', 'open_ended_helpfulness_fail_rate',
        'comparison_fail_rate', 'comparison_helpfulness_fail_rate',
    ]
    print(','.join(keys))
    for r in rows:
        out = []
        for k in keys:
            out.append(str(r.get(k, '')))
        print(','.join(out))


if __name__ == '__main__':
    main()
