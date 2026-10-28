"""Download, normalize, and index the company dataset for the chatbot.

The raw Kaggle export is kept at ``data/raw/tracxn.csv``. This script creates
two generated artifacts for the application:

- ``data/processed/tracxn.csv``: normalized UTF-8 CSV
- ``data/processed/companies.db``: SQLite database with an FTS5 search index

Run from the project root:

    python data/create_dataset.py
"""

from __future__ import annotations

import os
import shutil
import sqlite3
import subprocess
import sys
from numbers import Integral
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DOTENV_PATH = PROJECT_ROOT / ".env"
DATASET_HANDLE = "srisankargiri/list-of-118-unicorn-startups-in-indiamay-2025"
RAW_PATH = PROJECT_ROOT / "data" / "raw" / "tracxn.csv"
PROCESSED_CSV_PATH = PROJECT_ROOT / "data" / "processed" / "tracxn.csv"
SQLITE_PATH = PROJECT_ROOT / "data" / "processed" / "companies.db"

load_dotenv(DOTENV_PATH, override=True)

MISSING_MARKERS = {"", "?", "n/a", "na", "none", "null", "unknown"}
LOCATION_ALIASES = {"bangalore": "Bengaluru", "bengaluru": "Bengaluru"}

SQLITE_COLUMNS = (
    "source_rank", "company_name", "company_link", "company_info", "round_led_by",
    "company_background", "founded_year", "location", "country", "stage",
    "primary_sector", "time_to_unicorn", "top_investors_1", "top_investors_2",
    "annual_revenue", "valuation", "total_funding_till_date", "employee_count",
    "latest_funding_round",
)
SOURCE_COLUMNS = (
    "Rank", "Company", "company_link", "company_info", "round_led_by",
    "company_background", "founded_year", "location", "country", "stage",
    "primary_sector", "time_to_unicorn", "top_investors_1", "top_investors_2",
    "annual_revenue", "valuation", "total_funding_till_date", "employee_count",
    "latest_funding_round",
)


def normalize_text(series: pd.Series) -> pd.Series:
    """Collapse whitespace and convert placeholder strings to missing values."""

    normalized = (
        series.astype("string")
        .str.replace("\u00a0", " ", regex=False)
        .str.replace(r"\s+", " ", regex=True)
        .str.strip()
    )
    normalized = normalized.str.replace(r"^\?(\d)", r"₹\1", regex=True)
    return normalized.mask(normalized.str.casefold().isin(MISSING_MARKERS))


def normalize_dataset(df: pd.DataFrame) -> pd.DataFrame:
    """Return a normalized copy while preserving all rows and source columns."""

    result = df.copy()
    for column in result.select_dtypes(include=["object", "string"]).columns:
        result[column] = normalize_text(result[column])

    if "location" in result.columns:
        location_key = result["location"].str.casefold()
        result["location"] = location_key.map(LOCATION_ALIASES).fillna(
            result["location"]
        )
    return result


def get_kaggle_environment() -> dict[str, str]:
    """Return an environment compatible with the current Kaggle CLI."""

    environment = os.environ.copy()
    # The project uses KAGGLE_API_KEY in .env. The Kaggle CLI expects this value
    # under KAGGLE_API_TOKEN when the download command is invoked.
    if api_key := environment.get("KAGGLE_API_KEY"):
        environment["KAGGLE_API_TOKEN"] = api_key
    return environment


def download_raw_dataset() -> None:
    """Download and extract the source CSV when it is not already present."""

    kaggle_command = shutil.which("kaggle")
    if kaggle_command is None:
        raise RuntimeError(
            "The raw dataset is missing and the Kaggle CLI is not installed. "
            "Run `pip install -r requirements.txt`."
        )

    RAW_PATH.parent.mkdir(parents=True, exist_ok=True)
    command = [
        kaggle_command,
        "datasets",
        "download",
        DATASET_HANDLE,
        "--path",
        str(RAW_PATH.parent),
        "--unzip",
    ]
    result = subprocess.run(
        command,
        env=get_kaggle_environment(),
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or "No details provided."
        raise RuntimeError(
            "Kaggle could not download the dataset. Set KAGGLE_API_KEY in .env "
            "if authentication is required.\n\n"
            f"Kaggle output:\n{detail}"
        )
    if not RAW_PATH.exists():
        raise RuntimeError(f"Kaggle completed but did not create {RAW_PATH}.")


def ensure_raw_dataset() -> None:
    """Use the existing raw CSV or download it."""

    if RAW_PATH.exists():
        print(f"Using existing raw dataset: {RAW_PATH}")
        return

    print(f"Downloading Kaggle dataset: {DATASET_HANDLE}")
    download_raw_dataset()


def process_dataset() -> pd.DataFrame:
    """Normalize the raw CSV and write a UTF-8 processed copy."""

    raw = pd.read_csv(RAW_PATH, encoding="cp1252")
    processed = normalize_dataset(raw)
    PROCESSED_CSV_PATH.parent.mkdir(parents=True, exist_ok=True)
    processed.to_csv(PROCESSED_CSV_PATH, index=False, encoding="utf-8")
    return processed


def sqlite_value(value: object) -> str | int | None:
    """Convert pandas values to SQLite-compatible scalar values."""

    if pd.isna(value):
        return None
    if isinstance(value, Integral):
        return int(value)
    return str(value)


def create_sqlite_database(df: pd.DataFrame) -> None:
    """Rebuild the local SQLite database and its full-text search index."""

    create_companies_table = """
        CREATE TABLE companies (
            id INTEGER PRIMARY KEY,
            source_rank INTEGER,
            company_name TEXT NOT NULL UNIQUE,
            company_link TEXT,
            company_info TEXT,
            round_led_by TEXT,
            company_background TEXT,
            founded_year INTEGER,
            location TEXT,
            country TEXT,
            stage TEXT,
            primary_sector TEXT,
            time_to_unicorn TEXT,
            top_investors_1 TEXT,
            top_investors_2 TEXT,
            annual_revenue TEXT,
            valuation TEXT,
            total_funding_till_date TEXT,
            employee_count TEXT,
            latest_funding_round TEXT
        )
    """
    insert_statement = (
        f"INSERT INTO companies ({', '.join(SQLITE_COLUMNS)}) "
        f"VALUES ({', '.join('?' for _ in SQLITE_COLUMNS)})"
    )
    records = [
        tuple(sqlite_value(row[column]) for column in SOURCE_COLUMNS)
        for _, row in df.iterrows()
    ]

    try:
        with sqlite3.connect(SQLITE_PATH) as connection:
            connection.execute("DROP TABLE IF EXISTS companies_fts")
            connection.execute("DROP TABLE IF EXISTS companies")
            connection.execute(create_companies_table)
            connection.execute("CREATE INDEX idx_companies_location ON companies(location)")
            connection.execute("CREATE INDEX idx_companies_sector ON companies(primary_sector)")
            connection.executemany(insert_statement, records)
            connection.execute(
                "CREATE VIRTUAL TABLE companies_fts USING fts5("
                "company_name, company_info, company_background)"
            )
            connection.execute(
                "INSERT INTO companies_fts(rowid, company_name, company_info, company_background) "
                "SELECT id, company_name, COALESCE(company_info, ''), "
                "COALESCE(company_background, '') FROM companies"
            )
    except sqlite3.Error as error:
        raise RuntimeError(f"Could not create the SQLite database: {error}") from error

    print(f"Created SQLite database: {SQLITE_PATH}")
    print(f"Indexed {len(records)} companies for full-text search.")


def main() -> None:
    if len(sys.argv) != 1:
        raise SystemExit("This script does not accept command-line arguments.")

    try:
        ensure_raw_dataset()
        processed = process_dataset()
        create_sqlite_database(processed)
    except RuntimeError as error:
        raise SystemExit(f"Error: {error}") from error

    print(f"Created processed dataset: {PROCESSED_CSV_PATH}")
    print(f"Rows: {len(processed)} | Columns: {len(processed.columns)}")
    print(f"Missing values retained: {int(processed.isna().sum().sum())}")


if __name__ == "__main__":
    main()
