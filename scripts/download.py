"""
Download SEC filings from EDGAR.

TODO's
------
- more ergonomic batch downloading mechanism
    * read from a file
    * use yfinance to get tickers based on industries, market cap ranges, YTD/1Y performances, etc.
- add proper docstrings
- define proper return dataclass
"""

import argparse
import json
import time
from pathlib import Path
from urllib.parse import urljoin

from dotenv import load_dotenv
import requests
from loguru import logger
from tqdm import tqdm

from andromeda.ingest_profile import ingest_profile_layout, resolve_ingest_profile_name, update_ingest_profile_step

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

# required by SEC policies
UA = "MinHtoo linmin.htoo@gmail.com"
session = requests.Session()
session.headers.update({"User-Agent": UA, "Accept-Encoding": "gzip, deflate"})


CIK_TO_TICKER = {}


def ticker_map(timeout: int = 30):
    # Official SEC static mapping of tickers <-> CIKs
    j = session.get("https://www.sec.gov/files/company_tickers.json", timeout=timeout).json()
    # normalize -> { "AAPL": "0000320193", ... }
    m = {}
    for _, row in j.items():
        cik = f"{int(row['cik_str']):010d}"
        m[row["ticker"].upper()] = cik
        CIK_TO_TICKER[cik] = row["ticker"].upper()
    return m


def list_10k_submissions(cik, max_docs: int = 5, timeout: int = 30, year_cutoff: int | None = None):
    url = f"https://data.sec.gov/submissions/CIK{cik}.json"
    s = session.get(url, timeout=timeout).json()
    filings = s.get("filings", {}).get("recent", {})

    forms, acc, prim, dates = [filings.get(k, []) for k in ("form", "accessionNumber", "primaryDocument", "filingDate")]
    out_10k = []
    out_10q = []
    for f, a, p, d in zip(forms, acc, prim, dates):
        filing_year = int(d.split("-", maxsplit=1)[0])
        if year_cutoff is not None and filing_year < year_cutoff:
            continue
        if f == "10-K":
            out_10k.append(("10-K", a.replace("-", ""), p, d))
        if f == "10-Q":
            out_10q.append(("10-Q", a.replace("-", ""), p, d))

    ticker = CIK_TO_TICKER.get(cik, "UNKNOWN")
    logger.info(
        f"Found {len(out_10k)} 10-K filings for CIK {cik} ({ticker}), returning top {min(len(out_10k), max_docs)}"
    )
    logger.info(
        f"Found {len(out_10q)} 10-Q filings for CIK {cik} ({ticker}), returning top {min(len(out_10q), max_docs)}"
    )
    # [(accession_no_nohyphens, primary_doc, filing_date), ...]
    return out_10k[:max_docs] + out_10q[:max_docs]


def download_primary(cik, acc_no, primary_doc, timeout: int = 60):
    base = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{acc_no}/"
    url = urljoin(base, primary_doc)
    html = session.get(url, timeout=timeout).text
    return html, url


def fetch_10ks_for_tickers(
    tickers: list[str],
    output_dir: Path,
    per_company: int = 5,
    delay: float = 0.2,
    skip_existing: bool = False,
    year_cutoff: int | None = None,
):
    out_raw_folder = output_dir / "raw_htmls"
    out_meta_folder = output_dir / "meta"
    out_raw_folder.mkdir(parents=True, exist_ok=True)
    out_meta_folder.mkdir(parents=True, exist_ok=True)

    t2c = ticker_map()
    for t in tqdm(tickers, desc="fetching tickers"):
        cik = t2c[t.upper()]
        for form_type, acc_no, primary, fdate in tqdm(
            list_10k_submissions(cik, per_company, year_cutoff=year_cutoff), desc=f"processing ticker {t}"
        ):
            base = f"{t.upper()}_{acc_no}_{form_type}_{fdate}"

            raw_path = out_raw_folder / f"{base}.html"
            meta_path = out_meta_folder / f"{base}.json"
            if skip_existing and raw_path.exists() and meta_path.exists():
                logger.info(f"Skipping existing files for {base}")
                continue

            html, src_url = download_primary(cik, acc_no, primary)

            raw_path.write_text(html, encoding="utf-8")

            meta = {
                "ticker": t.upper(),
                "cik": cik,
                "filing_date": fdate,
                "accession": acc_no,
                "primary": primary,
                "source_url": src_url,
                "form": form_type,
            }
            meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2))

            time.sleep(delay)  # be polite

    logger.success("Done.")


if __name__ == "__main__":
    # NOTE: run this script from project root
    parser = argparse.ArgumentParser(description="Download SEC 10-K filings for given tickers")
    parser.add_argument("--tickers", nargs="+", help="List of ticker symbols to download")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Directory to save downloaded files (default: profile-scoped `data/ingest_profiles/<profile>/sec_filings`).",
    )
    parser.add_argument("--per-company", type=int, default=8, help="Number of filings to download per company")
    parser.add_argument(
        "--year-cutoff", type=int, default=None, help="Minimum filing year to include (e.g., 2025 means 2025 and later)"
    )
    parser.add_argument("--delay", type=float, default=0.2, help="Delay between requests to SEC")
    parser.add_argument("--skip-existing", action="store_true", help="Skip downloads when output files already exist")
    parser.add_argument(
        "--ingest-profile",
        default=None,
        help=(
            "Profile name for persisting download settings to disk "
            "(default resolution: FINRAG_INGEST_PROFILE, then POSTGRES_SCHEMA, then `default`)."
        ),
    )
    args = parser.parse_args()

    project_root = Path(__file__).resolve().parents[1]
    profile_name = resolve_ingest_profile_name(args.ingest_profile)
    profile_layout = ingest_profile_layout(project_root=project_root, profile_name=profile_name)
    output_dir = (
        Path(args.output_dir).expanduser().resolve() if args.output_dir is not None else profile_layout.sec_filings_root
    )
    tickers = [str(t or "").strip().upper() for t in (args.tickers or []) if str(t or "").strip()]

    fetch_10ks_for_tickers(
        tickers,
        output_dir=output_dir,
        per_company=args.per_company,
        delay=args.delay,
        skip_existing=args.skip_existing,
        year_cutoff=args.year_cutoff,
    )

    update_ingest_profile_step(
        project_root=project_root,
        profile_name=profile_name,
        step_name="download",
        settings={
            "tickers": tickers,
            "output_dir": str(output_dir),
            "per_company": int(args.per_company),
            "year_cutoff": int(args.year_cutoff) if args.year_cutoff is not None else None,
            "delay": float(args.delay),
            "skip_existing": bool(args.skip_existing),
        },
        metadata={"raw_html_dir": str(output_dir / "raw_htmls"), "meta_dir": str(output_dir / "meta")},
    )
