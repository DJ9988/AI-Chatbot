"""Unit and integration tests for data/create_dataset.py.

Tests cover all components of the dataset preparation pipeline:
- Text and dataset normalization (whitespace, missing markers, location aliases)
- Kaggle CLI environment preparation and download handling (error paths & success)
- Dataset processing (CP1252 reading, normalization, UTF-8 CSV writing)
- SQLite conversion, table creation, indexes, and FTS5 search indexing
- CLI argument validation and error handling in main()
- Schema and column constant integrity
"""

from __future__ import annotations

import io
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd

# Ensure the project root is in sys.path so data module can be imported
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import data.create_dataset as cd


def make_sample_dataframe(rows: list[dict] | None = None) -> pd.DataFrame:
    """Helper to create a DataFrame matching the SOURCE_COLUMNS schema."""
    default_record = {
        "Rank": 1,
        "Company": "TestPay",
        "company_link": "https://example.com/testpay",
        "company_info": "TestPay joined the Unicorn Club in 2021.",
        "round_led_by": "Test Ventures",
        "company_background": "Provider of digital payments and financial services.",
        "founded_year": 2015,
        "location": "Bengaluru",
        "country": "India",
        "stage": "Series D",
        "primary_sector": "FinTech",
        "time_to_unicorn": "6 years",
        "top_investors_1": "Investor A",
        "top_investors_2": "Investor B",
        "annual_revenue": "$100M",
        "valuation": "$1.5B",
        "total_funding_till_date": "$250M",
        "employee_count": "500",
        "latest_funding_round": "Series D, 2021",
    }
    if rows is None:
        return pd.DataFrame([default_record])

    full_rows = []
    for row in rows:
        merged = dict(default_record)
        merged.update(row)
        full_rows.append(merged)
    return pd.DataFrame(full_rows)


class TestConstantsAndSchema(unittest.TestCase):
    """Test schema constants and column alignment."""

    def test_column_lengths_match(self):
        self.assertEqual(len(cd.SQLITE_COLUMNS), len(cd.SOURCE_COLUMNS))
        self.assertEqual(len(cd.SQLITE_COLUMNS), 19)

    def test_column_mapping_alignments(self):
        # First two map 'Rank' -> 'source_rank' and 'Company' -> 'company_name'
        self.assertEqual(cd.SOURCE_COLUMNS[0], "Rank")
        self.assertEqual(cd.SQLITE_COLUMNS[0], "source_rank")
        self.assertEqual(cd.SOURCE_COLUMNS[1], "Company")
        self.assertEqual(cd.SQLITE_COLUMNS[1], "company_name")
        # Remaining 17 columns have identical names
        for src, sql in zip(cd.SOURCE_COLUMNS[2:], cd.SQLITE_COLUMNS[2:]):
            self.assertEqual(src, sql)

    def test_missing_markers_set(self):
        expected_markers = {"", "?", "n/a", "na", "none", "null", "unknown"}
        self.assertEqual(cd.MISSING_MARKERS, expected_markers)

    def test_location_aliases_mapping(self):
        self.assertEqual(cd.LOCATION_ALIASES["bangalore"], "Bengaluru")
        self.assertEqual(cd.LOCATION_ALIASES["bengaluru"], "Bengaluru")


class TestNormalizeText(unittest.TestCase):
    """Test text cleaning and missing value handling in normalize_text()."""

    def test_strips_leading_and_trailing_whitespace(self):
        series = pd.Series(["  hello  ", "\tworld\n", "   "])
        result = cd.normalize_text(series)
        self.assertEqual(result.iloc[0], "hello")
        self.assertEqual(result.iloc[1], "world")
        self.assertTrue(pd.isna(result.iloc[2]))

    def test_collapses_consecutive_whitespace(self):
        series = pd.Series(["FinTech   Startup   Platform"])
        result = cd.normalize_text(series)
        self.assertEqual(result.iloc[0], "FinTech Startup Platform")

    def test_replaces_non_breaking_space(self):
        series = pd.Series(["Razorpay\u00a0Software", "\u00a0\u00a0Value\u00a0\u00a0"])
        result = cd.normalize_text(series)
        self.assertEqual(result.iloc[0], "Razorpay Software")
        self.assertEqual(result.iloc[1], "Value")

    def test_masks_all_missing_markers_case_insensitively(self):
        markers = ["", "?", "N/A", "n/a", "NA", "na", "None", "NONE", "null", "NULL", "Unknown", "UNKNOWN"]
        series = pd.Series(markers)
        result = cd.normalize_text(series)
        for idx in range(len(markers)):
            self.assertTrue(pd.isna(result.iloc[idx]), f"Marker {markers[idx]!r} was not masked as missing")

    def test_preserves_valid_strings_containing_marker_substrings(self):
        valid_words = ["Banana", "North America", "Not unknown at all", "Question?", "12345"]
        series = pd.Series(valid_words)
        result = cd.normalize_text(series)
        for idx, word in enumerate(valid_words):
            self.assertEqual(result.iloc[idx], word)

    def test_handles_already_missing_inputs(self):
        series = pd.Series([None, pd.NA, np.nan])
        result = cd.normalize_text(series)
        self.assertTrue(result.isna().all())


class TestNormalizeDataset(unittest.TestCase):
    """Test dataframe-level normalization and location alias resolution."""

    def test_normalizes_object_and_string_columns(self):
        df = pd.DataFrame({
            "Company": ["  Razorpay\u00a0  ", "Zerodha"],
            "sector": ["FinTech   Payments", "N/A"],
            "founded_year": [2014, 2010],
        })
        normalized = cd.normalize_dataset(df)
        self.assertEqual(normalized["Company"].iloc[0], "Razorpay")
        self.assertEqual(normalized["sector"].iloc[0], "FinTech Payments")
        self.assertTrue(pd.isna(normalized["sector"].iloc[1]))
        # Numeric column preserved unchanged
        self.assertEqual(normalized["founded_year"].iloc[0], 2014)
        self.assertEqual(normalized["founded_year"].iloc[1], 2010)

    def test_normalizes_location_aliases(self):
        df = pd.DataFrame({
            "Company": ["A", "B", "C", "D", "E", "F"],
            "location": [
                "bangalore",
                "Bengaluru",
                "  Bangalore  ",
                "BENGALURU",
                "Mumbai",
                None,
            ],
        })
        normalized = cd.normalize_dataset(df)
        self.assertEqual(normalized["location"].iloc[0], "Bengaluru")
        self.assertEqual(normalized["location"].iloc[1], "Bengaluru")
        self.assertEqual(normalized["location"].iloc[2], "Bengaluru")
        self.assertEqual(normalized["location"].iloc[3], "Bengaluru")
        self.assertEqual(normalized["location"].iloc[4], "Mumbai")
        self.assertTrue(pd.isna(normalized["location"].iloc[5]))

    def test_handles_dataframe_without_location_column(self):
        df = pd.DataFrame({"name": ["Test"], "val": ["OK"]})
        normalized = cd.normalize_dataset(df)
        self.assertEqual(normalized["val"].iloc[0], "OK")

    def test_does_not_mutate_original_dataframe(self):
        original = pd.DataFrame({"location": ["bangalore"]})
        _ = cd.normalize_dataset(original)
        self.assertEqual(original["location"].iloc[0], "bangalore")


class TestSqliteValue(unittest.TestCase):
    """Test conversion of pandas values to SQLite types."""

    def test_missing_values_return_none(self):
        self.assertIsNone(cd.sqlite_value(None))
        self.assertIsNone(cd.sqlite_value(np.nan))
        self.assertIsNone(cd.sqlite_value(pd.NA))
        self.assertIsNone(cd.sqlite_value(float("nan")))

    def test_integral_values_return_int(self):
        self.assertEqual(cd.sqlite_value(2021), 2021)
        self.assertIsInstance(cd.sqlite_value(2021), int)
        self.assertEqual(cd.sqlite_value(np.int64(118)), 118)
        self.assertIsInstance(cd.sqlite_value(np.int64(118)), int)
        self.assertEqual(cd.sqlite_value(np.int32(42)), 42)
        self.assertIsInstance(cd.sqlite_value(np.int32(42)), int)

    def test_strings_and_other_scalars_return_str(self):
        self.assertEqual(cd.sqlite_value("Razorpay"), "Razorpay")
        self.assertEqual(cd.sqlite_value(12.34), "12.34")

    def test_boolean_is_integral_in_sqlite(self):
        # In Python, bool is an instance of numbers.Integral, mapping True -> 1, False -> 0
        self.assertEqual(cd.sqlite_value(True), 1)
        self.assertEqual(cd.sqlite_value(False), 0)


class TestKaggleEnvironment(unittest.TestCase):
    """Test Kaggle CLI environment variable mapping."""

    def test_get_kaggle_environment_with_api_key(self):
        with patch.dict(os.environ, {"KAGGLE_API_KEY": "test-key-123"}, clear=True):
            env = cd.get_kaggle_environment()
            self.assertEqual(env.get("KAGGLE_API_KEY"), "test-key-123")
            self.assertEqual(env.get("KAGGLE_API_TOKEN"), "test-key-123")

    def test_get_kaggle_environment_without_api_key(self):
        with patch.dict(os.environ, {}, clear=True):
            env = cd.get_kaggle_environment()
            self.assertNotIn("KAGGLE_API_KEY", env)
            self.assertNotIn("KAGGLE_API_TOKEN", env)


class TestDownloadRawDataset(unittest.TestCase):
    """Test download_raw_dataset() including error branches and successful invocation."""

    @patch("shutil.which", return_value=None)
    def test_missing_kaggle_cli_raises_runtime_error(self, mock_which):
        with self.assertRaises(RuntimeError) as ctx:
            cd.download_raw_dataset()
        self.assertIn("Kaggle CLI is not installed", str(ctx.exception))

    @patch("shutil.which", return_value="/usr/bin/kaggle")
    @patch("subprocess.run")
    def test_kaggle_command_failure_raises_runtime_error(self, mock_run, mock_which):
        mock_run.return_value = subprocess.CompletedProcess(
            args=["kaggle"],
            returncode=1,
            stdout="",
            stderr="401 - Unauthorized: Invalid credentials",
        )
        with self.assertRaises(RuntimeError) as ctx:
            cd.download_raw_dataset()
        self.assertIn("Kaggle could not download the dataset", str(ctx.exception))
        self.assertIn("401 - Unauthorized", str(ctx.exception))

    @patch("shutil.which", return_value="/usr/bin/kaggle")
    @patch("subprocess.run")
    def test_file_not_found_after_kaggle_success_raises_runtime_error(self, mock_run, mock_which):
        mock_run.return_value = subprocess.CompletedProcess(
            args=["kaggle"],
            returncode=0,
            stdout="Download complete",
            stderr="",
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            temp_raw = Path(tmpdir) / "raw" / "tracxn.csv"
            with patch.object(cd, "RAW_PATH", temp_raw):
                with self.assertRaises(RuntimeError) as ctx:
                    cd.download_raw_dataset()
                self.assertIn("did not create", str(ctx.exception))

    @patch("shutil.which", return_value="/usr/bin/kaggle")
    @patch("subprocess.run")
    def test_download_success(self, mock_run, mock_which):
        with tempfile.TemporaryDirectory() as tmpdir:
            temp_raw = Path(tmpdir) / "raw" / "tracxn.csv"

            def simulate_download(*args, **kwargs):
                temp_raw.parent.mkdir(parents=True, exist_ok=True)
                temp_raw.write_text("Rank,Company\n1,Test\n", encoding="utf-8")
                return subprocess.CompletedProcess(args=args[0], returncode=0, stdout="Done", stderr="")

            mock_run.side_effect = simulate_download

            with patch.object(cd, "RAW_PATH", temp_raw):
                cd.download_raw_dataset()
                self.assertTrue(temp_raw.exists())
                # Verify subprocess call arguments
                mock_run.assert_called_once()
                call_args = mock_run.call_args[0][0]
                self.assertEqual(call_args[0], "/usr/bin/kaggle")
                self.assertIn("datasets", call_args)
                self.assertIn("download", call_args)
                self.assertIn(cd.DATASET_HANDLE, call_args)
                self.assertIn(str(temp_raw.parent), call_args)


class TestEnsureRawDataset(unittest.TestCase):
    """Test ensure_raw_dataset() caching and trigger behavior."""

    @patch("builtins.print")
    @patch("data.create_dataset.download_raw_dataset")
    def test_uses_existing_raw_dataset_when_present(self, mock_download, mock_print):
        with tempfile.TemporaryDirectory() as tmpdir:
            temp_raw = Path(tmpdir) / "tracxn.csv"
            temp_raw.write_text("sample content", encoding="utf-8")
            with patch.object(cd, "RAW_PATH", temp_raw):
                cd.ensure_raw_dataset()
                mock_download.assert_not_called()
                mock_print.assert_called_with(f"Using existing raw dataset: {temp_raw}")

    @patch("builtins.print")
    @patch("data.create_dataset.download_raw_dataset")
    def test_downloads_raw_dataset_when_missing(self, mock_download, mock_print):
        with tempfile.TemporaryDirectory() as tmpdir:
            temp_raw = Path(tmpdir) / "tracxn.csv"
            with patch.object(cd, "RAW_PATH", temp_raw):
                cd.ensure_raw_dataset()
                mock_download.assert_called_once()
                mock_print.assert_any_call(f"Downloading Kaggle dataset: {cd.DATASET_HANDLE}")


class TestProcessDataset(unittest.TestCase):
    """Test process_dataset() reads CP1252 source and writes normalized UTF-8 CSV."""

    def test_process_dataset_end_to_end(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            raw_path = Path(tmpdir) / "raw" / "tracxn.csv"
            processed_path = Path(tmpdir) / "processed" / "tracxn.csv"

            # Create sample raw data with CP1252 encoded characters (e.g. currency symbol \x80 or non-breaking space \xA0)
            sample_df = make_sample_dataframe([
                {
                    "Rank": 1,
                    "Company": "Razorpay\u00a0  ",
                    "location": "bangalore",
                    "primary_sector": "FinTech   Payments",
                    "stage": "n/a",
                },
                {
                    "Rank": 2,
                    "Company": "Zerodha",
                    "location": "bengaluru",
                    "primary_sector": "Stock Broker",
                    "stage": "Series A",
                },
            ])
            raw_path.parent.mkdir(parents=True, exist_ok=True)
            sample_df.to_csv(raw_path, index=False, encoding="cp1252")

            with patch.object(cd, "RAW_PATH", raw_path), patch.object(cd, "PROCESSED_CSV_PATH", processed_path):
                result = cd.process_dataset()

                self.assertTrue(processed_path.exists())
                self.assertEqual(len(result), 2)
                # Verify company name had NBSP replaced and stripped
                self.assertEqual(result["Company"].iloc[0], "Razorpay")
                # Verify location alias normalized
                self.assertEqual(result["location"].iloc[0], "Bengaluru")
                self.assertEqual(result["location"].iloc[1], "Bengaluru")
                # Verify whitespace collapsed in primary_sector
                self.assertEqual(result["primary_sector"].iloc[0], "FinTech Payments")
                # Verify missing marker replaced with NA
                self.assertTrue(pd.isna(result["stage"].iloc[0]))
                self.assertEqual(result["stage"].iloc[1], "Series A")

                # Verify written CSV file is readable as UTF-8
                written_df = pd.read_csv(processed_path, encoding="utf-8")
                self.assertEqual(len(written_df), 2)
                self.assertEqual(written_df["Company"].iloc[0], "Razorpay")


class TestCreateSqliteDatabase(unittest.TestCase):
    """Test SQLite database creation, schema, records, indexes, and FTS5 search."""

    def test_creates_tables_indexes_and_populates_data(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "companies.db"
            sample_df = make_sample_dataframe([
                {
                    "Rank": 1,
                    "Company": "Juspay",
                    "company_info": "Payments orchestration platform founded in Bangalore.",
                    "company_background": "Provider of a global payments operating system.",
                    "founded_year": 2012,
                    "location": "Bengaluru",
                    "primary_sector": "Payments",
                },
                {
                    "Rank": 2,
                    "Company": "Ather Energy",
                    "company_info": "Electric vehicle manufacturer.",
                    "company_background": "Smart electric scooters and charging networks.",
                    "founded_year": 2013,
                    "location": "Bengaluru",
                    "primary_sector": "Electric Vehicles",
                },
                {
                    "Rank": 3,
                    "Company": "NullInfo Corp",
                    "company_info": None,
                    "company_background": None,
                    "founded_year": 2020,
                    "location": "Mumbai",
                    "primary_sector": "Logistics",
                },
            ])

            with patch.object(cd, "SQLITE_PATH", db_path):
                cd.create_sqlite_database(sample_df)

                self.assertTrue(db_path.exists())

                with sqlite3.connect(db_path) as conn:
                    cursor = conn.cursor()

                    # Check companies table schema
                    cursor.execute("PRAGMA table_info(companies)")
                    cols = {row[1]: row[2] for row in cursor.fetchall()}
                    self.assertIn("id", cols)
                    self.assertEqual(cols["id"], "INTEGER")
                    for col in cd.SQLITE_COLUMNS:
                        self.assertIn(col, cols)

                    # Check total count
                    cursor.execute("SELECT COUNT(*) FROM companies")
                    self.assertEqual(cursor.fetchone()[0], 3)

                    # Check row details and data types
                    cursor.execute("SELECT id, source_rank, company_name, founded_year, location FROM companies WHERE company_name = 'Juspay'")
                    row = cursor.fetchone()
                    self.assertIsNotNone(row)
                    self.assertEqual(row[1], 1)
                    self.assertEqual(row[2], "Juspay")
                    self.assertEqual(row[3], 2012)
                    self.assertEqual(row[4], "Bengaluru")

                    # Check indexes
                    cursor.execute("PRAGMA index_list(companies)")
                    index_names = [idx[1] for idx in cursor.fetchall()]
                    self.assertIn("idx_companies_location", index_names)
                    self.assertIn("idx_companies_sector", index_names)

                    # Check FTS5 virtual table
                    cursor.execute("SELECT rowid, company_name FROM companies_fts WHERE companies_fts MATCH 'orchestration'")
                    fts_match = cursor.fetchall()
                    self.assertEqual(len(fts_match), 1)
                    self.assertEqual(fts_match[0][1], "Juspay")

                    cursor.execute("SELECT rowid, company_name FROM companies_fts WHERE companies_fts MATCH 'scooters'")
                    fts_scooters = cursor.fetchall()
                    self.assertEqual(len(fts_scooters), 1)
                    self.assertEqual(fts_scooters[0][1], "Ather Energy")

                    # Check NULL handling with COALESCE in FTS5
                    cursor.execute("SELECT company_info, company_background FROM companies_fts WHERE company_name = 'NullInfo Corp'")
                    null_corp = cursor.fetchone()
                    self.assertEqual(null_corp[0], "")
                    self.assertEqual(null_corp[1], "")

    def test_replaces_existing_database_without_errors(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "companies.db"
            df1 = make_sample_dataframe([{"Company": "Company A"}])
            df2 = make_sample_dataframe([{"Company": "Company B"}])

            with patch.object(cd, "SQLITE_PATH", db_path):
                cd.create_sqlite_database(df1)
                # Second invocation should drop and recreate cleanly
                cd.create_sqlite_database(df2)

                with sqlite3.connect(db_path) as conn:
                    cursor = conn.cursor()
                    cursor.execute("SELECT company_name FROM companies")
                    rows = cursor.fetchall()
                    self.assertEqual(len(rows), 1)
                    self.assertEqual(rows[0][0], "Company B")

    def test_sqlite_error_raises_runtime_error(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            # Point to a path inside an invalid / unwriteable file path
            invalid_db_path = Path(tmpdir) / "not_a_dir" / "file.txt" / "sub" / "companies.db"
            df = make_sample_dataframe()

            with patch.object(cd, "SQLITE_PATH", invalid_db_path):
                with self.assertRaises(RuntimeError) as ctx:
                    cd.create_sqlite_database(df)
                self.assertIn("Could not create the SQLite database", str(ctx.exception))


class TestMain(unittest.TestCase):
    """Test main() command-line handling, execution orchestration, and error exits."""

    def test_main_rejects_command_line_arguments(self):
        with patch.object(sys, "argv", ["create_dataset.py", "--unexpected"]):
            with self.assertRaises(SystemExit) as ctx:
                cd.main()
            self.assertIn("does not accept command-line arguments", str(ctx.exception))

    @patch("builtins.print")
    @patch("data.create_dataset.ensure_raw_dataset")
    @patch("data.create_dataset.process_dataset")
    @patch("data.create_dataset.create_sqlite_database")
    def test_main_success_flow(self, mock_create_db, mock_process, mock_ensure, mock_print):
        sample_df = make_sample_dataframe([{"Company": "Alpha"}, {"Company": "Beta"}])
        mock_process.return_value = sample_df

        with patch.object(sys, "argv", ["create_dataset.py"]):
            cd.main()

            mock_ensure.assert_called_once()
            mock_process.assert_called_once()
            mock_create_db.assert_called_once_with(sample_df)
            # Verify summary statistics prints
            mock_print.assert_any_call(f"Created processed dataset: {cd.PROCESSED_CSV_PATH}")

    @patch("data.create_dataset.ensure_raw_dataset", side_effect=RuntimeError("Kaggle auth failed"))
    def test_main_handles_runtime_error_gracefully(self, mock_ensure):
        with patch.object(sys, "argv", ["create_dataset.py"]):
            with self.assertRaises(SystemExit) as ctx:
                cd.main()
            self.assertEqual(str(ctx.exception), "Error: Kaggle auth failed")

    def test_module_entrypoint_execution_with_arguments(self):
        import runpy

        with patch.object(sys, "argv", ["create_dataset.py", "--invalid-arg"]):
            with self.assertRaises(SystemExit) as ctx:
                runpy.run_path(str(PROJECT_ROOT / "data" / "create_dataset.py"), run_name="__main__")
            self.assertIn("This script does not accept command-line arguments", str(ctx.exception))


class TestEndToEndPipeline(unittest.TestCase):
    """End-to-end integration test of the full create_dataset pipeline."""

    def test_full_pipeline_with_isolated_filesystem(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            temp_dir = Path(tmpdir)
            raw_path = temp_dir / "raw" / "tracxn.csv"
            processed_csv = temp_dir / "processed" / "tracxn.csv"
            sqlite_db = temp_dir / "processed" / "companies.db"

            raw_path.parent.mkdir(parents=True, exist_ok=True)
            # Create a full raw CSV with various realistic values
            raw_content = (
                "Rank,Company,company_link,company_info,round_led_by,company_background,founded_year,location,country,stage,primary_sector,time_to_unicorn,top_investors_1,top_investors_2,annual_revenue,valuation,total_funding_till_date,employee_count,latest_funding_round\n"
                '1,Swiggy,https://tracxn.com/d/swiggy,"Food delivery platform in Bangalore.",SoftBank,"Online platform for food delivery.",2014,bangalore,India,Series J,Food Tech,4 years,Prosus,SoftBank,$700M,$10B,$3.6B,"5,000",Series J\n'
                '2,Razorpay,https://tracxn.com/d/razorpay,"Payments gateway.",Tiger Global,"Payments processing for business.",2014,Bengaluru  ,India,Series F,Payments,6 years,GIC,Tiger Global,$250M,$7.5B,$740M,"2,000",Series F\n'
                '3,Zomato,https://tracxn.com/d/zomato,"Restaurant discovery & delivery.?",Info Edge,"Restaurant search platform.",2008,Gurugram,India,Public,Food Tech,10 years,Ant Financial,Info Edge,$800M,$12B,$2.1B,"4,000",Public\n'
            )
            raw_path.write_bytes(raw_content.encode("cp1252"))

            with patch.object(cd, "RAW_PATH", raw_path), \
                 patch.object(cd, "PROCESSED_CSV_PATH", processed_csv), \
                 patch.object(cd, "SQLITE_PATH", sqlite_db), \
                 patch.object(sys, "argv", ["create_dataset.py"]):

                # Execute main()
                cd.main()

                # Verify processed CSV was created and normalized
                self.assertTrue(processed_csv.exists())
                df = pd.read_csv(processed_csv)
                self.assertEqual(len(df), 3)
                # Location normalization check
                self.assertEqual(df["location"].tolist(), ["Bengaluru", "Bengaluru", "Gurugram"])

                # Verify SQLite database and FTS5 search
                self.assertTrue(sqlite_db.exists())
                with sqlite3.connect(sqlite_db) as conn:
                    cursor = conn.cursor()
                    cursor.execute("SELECT COUNT(*) FROM companies")
                    self.assertEqual(cursor.fetchone()[0], 3)

                    cursor.execute(
                        "SELECT company_name FROM companies_fts WHERE companies_fts MATCH 'gateway'"
                    )
                    matches = cursor.fetchall()
                    self.assertEqual(len(matches), 1)
                    self.assertEqual(matches[0][0], "Razorpay")


if __name__ == "__main__":
    unittest.main()