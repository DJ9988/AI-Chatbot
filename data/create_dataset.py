"""Download (when needed) and normalize the Kaggle dataset for the chatbot.

The raw Kaggle export is saved unchanged to ``data/raw/tracxn.csv``. The
normalized UTF-8 version used by the application is written to
``data/processed/tracxn.csv``.

Run from the project root:

    python data/create_dataset.py
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATASET_HANDLE = "srisankargiri/list-of-118-unicorn-startups-in-indiamay-2025"
DEFAULT_RAW_PATH = PROJECT_ROOT / "data" / "raw" / "tracxn.csv"
DEFAULT_OUTPUT_PATH = PROJECT_ROOT / "data" / "processed" / "tracxn.csv"

# These values mean that information was not supplied. They are retained as
# missing values; no unavailable company information is fabricated or imputed.
MISSING_MARKERS = {"", "?", "n/a", "na", "none", "null", "unknown"}

# Keep aliases small and explicit so that normalization does not silently alter
# valid names. This supports filters such as “companies in Bangalore”.
LOCATION_ALIASES = {
    "bangalore": "Bengaluru",
    "bengaluru": "Bengaluru",
}


def normalize_text(series: pd.Series) -> pd.Series:
    """Collapse whitespace and convert placeholder strings to missing values."""

    normalized = (
        series.astype("string")
        .str.replace("\u00a0", " ", regex=False)
        .str.replace(r"\s+", " ", regex=True)
        .str.strip()
    )
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


def get_kaggle_environment(token_file: Path | None) -> dict[str, str]:
    """Return subprocess environment, optionally adding a token from a file."""

    environment = os.environ.copy()
    if token_file is None:
        return environment

    try:
        token = token_file.read_text(encoding="utf-8").strip()
    except OSError as error:
        raise RuntimeError(f"Could not read Kaggle token file: {token_file}") from error

    if not token:
        raise RuntimeError(f"Kaggle token file is empty: {token_file}")

    environment["KAGGLE_API_TOKEN"] = token
    return environment


def download_raw_dataset(
    raw_path: Path, *, force_download: bool, token_file: Path | None
) -> None:
    """Download and extract the source CSV using the installed Kaggle CLI."""

    kaggle_command = shutil.which("kaggle")
    if kaggle_command is None:
        raise RuntimeError(
            "The raw dataset is missing and the Kaggle CLI is not installed. "
            "Install dependencies with `pip install -r requirements.txt`, then "
            "authenticate with `kaggle auth login` or set KAGGLE_API_TOKEN."
        )

    raw_path.parent.mkdir(parents=True, exist_ok=True)
    command = [
        kaggle_command,
        "datasets",
        "download",
        DATASET_HANDLE,
        "--path",
        str(raw_path.parent),
        "--unzip",
    ]
    if force_download:
        command.append("--force")

    result = subprocess.run(
        command,
        env=get_kaggle_environment(token_file),
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or "No details provided."
        raise RuntimeError(
            "Kaggle could not download the dataset. Authenticate with `kaggle auth "
            "login`, set KAGGLE_API_TOKEN, or pass --kaggle-api-token-file.\n\n"
            f"Kaggle output:\n{detail}"
        )

    if not raw_path.exists():
        raise RuntimeError(
            f"Kaggle completed but the expected file was not found: {raw_path}."
        )


def ensure_raw_dataset(args: argparse.Namespace) -> None:
    """Use an existing raw file or download it when it is missing/forced."""

    if args.raw_path.exists() and not args.force_download:
        print(f"Using existing raw dataset: {args.raw_path}")
        return

    if args.skip_download:
        raise RuntimeError(
            f"Raw dataset not found at {args.raw_path}. Remove --skip-download to "
            "download it, or provide --raw-path."
        )

    print(f"Downloading Kaggle dataset: {DATASET_HANDLE}")
    download_raw_dataset(
        args.raw_path,
        force_download=args.force_download,
        token_file=args.kaggle_api_token_file,
    )


def process_dataset(raw_path: Path, output_path: Path) -> pd.DataFrame:
    """Read the raw CSV, normalize it, and save a UTF-8 processed copy."""

    # The Kaggle export contains Windows-1252 characters, such as NBSP bytes.
    raw = pd.read_csv(raw_path, encoding="cp1252")
    processed = normalize_dataset(raw)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    processed.to_csv(output_path, index=False, encoding="utf-8")
    return processed


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-path", type=Path, default=DEFAULT_RAW_PATH)
    parser.add_argument("--output-path", type=Path, default=DEFAULT_OUTPUT_PATH)
    parser.add_argument(
        "--force-download",
        action="store_true",
        help="Download the Kaggle dataset again even when the raw CSV exists.",
    )
    parser.add_argument(
        "--skip-download",
        action="store_true",
        help="Fail instead of downloading if the raw CSV is missing.",
    )
    parser.add_argument(
        "--kaggle-api-token-file",
        type=Path,
        help=(
            "File containing a KAGGLE_API_TOKEN. Prefer this or the environment "
            "variable to passing credentials through command-line history."
        ),
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    try:
        ensure_raw_dataset(args)
        processed = process_dataset(args.raw_path, args.output_path)
    except RuntimeError as error:
        raise SystemExit(f"Error: {error}") from error

    print(f"Created processed dataset: {args.output_path}")
    print(f"Rows: {len(processed)} | Columns: {len(processed.columns)}")
    print(f"Missing values retained: {int(processed.isna().sum().sum())}")


if __name__ == "__main__":
    main()
