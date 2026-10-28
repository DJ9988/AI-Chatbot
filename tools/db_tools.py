"""Database and knowledge retrieval tools for the Indian unicorn startups dataset.

Provides focused retrieval functions and LangChain tools for:
1. get_available_filters: inspecting exact unique sectors and locations from the dataset
2. lookup_company: retrieving comprehensive facts for a single company
3. filter_companies_tool: filtering companies by sector(s), city, and/or founded year
4. search_companies_tool: keyword and capability search across company backgrounds
"""

from __future__ import annotations

import difflib
import json
import re
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional

from langchain_core.tools import tool

from config.settings import get_settings


def get_db_connection(db_path: Optional[Path] = None) -> sqlite3.Connection:
    """Return a SQLite connection with dict-like row access."""
    path = db_path or get_settings().db_path
    if not path.exists():
        raise FileNotFoundError(
            f"Database file not found at {path}. Please run `python data/create_dataset.py` first."
        )
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def get_all_company_names(db_path: Optional[Path] = None) -> List[str]:
    """Return all unique company names in the database."""
    with get_db_connection(db_path) as conn:
        rows = conn.execute("SELECT company_name FROM companies ORDER BY company_name").fetchall()
        return [r["company_name"] for r in rows]


def get_all_sectors(db_path: Optional[Path] = None) -> List[str]:
    """Return all unique primary sectors from the database."""
    with get_db_connection(db_path) as conn:
        rows = conn.execute(
            "SELECT DISTINCT primary_sector FROM companies WHERE primary_sector IS NOT NULL ORDER BY primary_sector"
        ).fetchall()
        return [r["primary_sector"] for r in rows]


def get_all_locations(db_path: Optional[Path] = None) -> List[str]:
    """Return all unique locations from the database."""
    with get_db_connection(db_path) as conn:
        rows = conn.execute(
            "SELECT DISTINCT location FROM companies WHERE location IS NOT NULL ORDER BY location"
        ).fetchall()
        return [r["location"] for r in rows]


def get_company_by_name(name: str, db_path: Optional[Path] = None) -> Dict[str, Any]:
    """Retrieve detailed facts for a single company by name."""
    cleaned_name = name.strip()
    if not cleaned_name:
        return {
            "status": "error",
            "message": "Company name query cannot be empty.",
            "suggestions": [],
        }

    with get_db_connection(db_path) as conn:
        # 1. Exact match
        row = conn.execute(
            "SELECT * FROM companies WHERE company_name = ?", (cleaned_name,)
        ).fetchone()

        # 2. Case-insensitive match
        if not row:
            row = conn.execute(
                "SELECT * FROM companies WHERE company_name = ? COLLATE NOCASE",
                (cleaned_name,),
            ).fetchone()

        # 3. Substring match
        if not row:
            row = conn.execute(
                "SELECT * FROM companies WHERE company_name LIKE ? COLLATE NOCASE",
                (f"%{cleaned_name}%",),
            ).fetchone()

        # 4. Alphanumeric normalization match (handles "Byjus" -> "BYJU'S", "Razor pay" -> "Razorpay", "cult fit" -> "Cult.fit")
        if not row:
            target_alpha = re.sub(r"[^a-zA-Z0-9]", "", cleaned_name).casefold()
            if target_alpha:
                all_rows = conn.execute("SELECT * FROM companies").fetchall()
                for r in all_rows:
                    if re.sub(r"[^a-zA-Z0-9]", "", r["company_name"]).casefold() == target_alpha:
                        row = r
                        break

        if row:
            return {
                "status": "success",
                "match_type": "exact_or_substring",
                "company": dict(row),
            }

        # 4. If not found, find genuinely close spelling matches (cutoff >= 0.72)
        all_names = get_all_company_names(db_path)
        close_matches = difflib.get_close_matches(cleaned_name, all_names, n=3, cutoff=0.72)
        if not close_matches:
            name_map = {n.casefold(): n for n in all_names}
            lower_matches = difflib.get_close_matches(cleaned_name.casefold(), list(name_map.keys()), n=3, cutoff=0.72)
            close_matches = [name_map[m] for m in lower_matches]

        return {
            "status": "not_found",
            "message": f"Company '{cleaned_name}' was not found in the dataset.",
            "suggestions": close_matches,
            "guidance": (
                f"Did you mean one of: {close_matches}? Or call `search_companies_tool` with keywords."
                if close_matches
                else "No similar company names found in the dataset. Try `search_companies_tool` with general keywords."
            ),
        }


def filter_companies(
    sector: Optional[str] = None,
    location: Optional[str] = None,
    min_year: Optional[int] = None,
    max_year: Optional[int] = None,
    limit: int = 50,
    db_path: Optional[Path] = None,
) -> Dict[str, Any]:
    """Filter startups by sector(s), location, and/or founded year range.

    Sector and location support single values or comma-separated lists.
    Matching is case-insensitive substring matching against the database values.
    """
    conditions: List[str] = []
    params: List[Any] = []

    # 1. Sector handling (supports single value or comma-separated list)
    if sector and sector.strip():
        sector_items = [s.strip() for s in sector.split(",") if s.strip()]
        if len(sector_items) == 1:
            conditions.append("primary_sector LIKE ? COLLATE NOCASE")
            params.append(f"%{sector_items[0]}%")
        elif len(sector_items) > 1:
            sub_clauses = ["primary_sector LIKE ? COLLATE NOCASE" for _ in sector_items]
            conditions.append(f"({' OR '.join(sub_clauses)})")
            params.extend([f"%{item}%" for item in sector_items])

    # 2. Location handling (supports single value or comma-separated list)
    if location and location.strip():
        location_items = [loc.strip() for loc in location.split(",") if loc.strip()]
        if len(location_items) == 1:
            conditions.append("location LIKE ? COLLATE NOCASE")
            params.append(f"%{location_items[0]}%")
        elif len(location_items) > 1:
            sub_clauses = ["location LIKE ? COLLATE NOCASE" for _ in location_items]
            conditions.append(f"({' OR '.join(sub_clauses)})")
            params.extend([f"%{item}%" for item in location_items])

    # 3. Founded year range handling
    if min_year is not None:
        conditions.append("founded_year >= ?")
        params.append(min_year)
    if max_year is not None:
        conditions.append("founded_year <= ?")
        params.append(max_year)

    where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    sql = f"""
        SELECT id, company_name, primary_sector, location, founded_year, valuation,
               annual_revenue, stage, company_info
        FROM companies
        {where_clause}
        ORDER BY company_name
        LIMIT ?
    """
    params.append(limit)

    with get_db_connection(db_path) as conn:
        rows = conn.execute(sql, params).fetchall()
        results = [dict(r) for r in rows]

        if results:
            return {
                "status": "success",
                "count": len(results),
                "companies": results,
            }

        # If 0 results, provide suggestions from actual DB values for course correction
        all_sectors = get_all_sectors(db_path)
        all_locations = get_all_locations(db_path)

        sector_sugg = difflib.get_close_matches(sector.strip(), all_sectors, n=3, cutoff=0.7) if sector else []
        loc_sugg = difflib.get_close_matches(location.strip(), all_locations, n=3, cutoff=0.7) if location else []

        return {
            "status": "no_results",
            "count": 0,
            "companies": [],
            "message": "No companies matched the specified filter criteria.",
            "sector_suggestions": sector_sugg,
            "location_suggestions": loc_sugg,
            "guidance": (
                "Call `get_available_filters` to check exact sector and city names available in the dataset."
            ),
        }


def escape_fts5_query(query: str, operator: str = "AND") -> str:
    """Sanitize and quote free-text terms for SQLite FTS5 matching."""
    words = re.findall(r"\b[\w\-]+\b", query)
    if not words:
        return '""'
    return f" {operator} ".join(f'"{word}"' for word in words)


def search_companies_fts(
    query: str,
    limit: int = 15,
    db_path: Optional[Path] = None,
) -> Dict[str, Any]:
    """Search companies across descriptions and backgrounds using FTS5."""
    cleaned_query = query.strip()
    if not cleaned_query:
        return {
            "status": "error",
            "message": "Search query cannot be empty.",
            "companies": [],
        }

    with get_db_connection(db_path) as conn:
        try:
            # 1. First attempt: Strict AND match across all terms
            fts_and = escape_fts5_query(cleaned_query, operator="AND")
            fts_sql = """
                SELECT c.id, c.company_name, c.primary_sector, c.location, c.founded_year,
                       c.valuation, c.company_info, c.company_background
                FROM companies_fts fts
                JOIN companies c ON c.company_name = fts.company_name
                WHERE companies_fts MATCH ?
                LIMIT ?
            """
            rows = conn.execute(fts_sql, (fts_and, limit)).fetchall()
            if rows:
                return {
                    "status": "success",
                    "search_mode": "fts5",
                    "count": len(rows),
                    "companies": [dict(r) for r in rows],
                }

            # 2. Second attempt: BM25 ranked OR match for multi-word queries
            words = re.findall(r"\b[\w\-]+\b", cleaned_query)
            if len(words) > 1:
                fts_or = escape_fts5_query(cleaned_query, operator="OR")
                fts_or_sql = """
                    SELECT c.id, c.company_name, c.primary_sector, c.location, c.founded_year,
                           c.valuation, c.company_info, c.company_background
                    FROM companies_fts fts
                    JOIN companies c ON c.company_name = fts.company_name
                    WHERE companies_fts MATCH ?
                    ORDER BY bm25(companies_fts)
                    LIMIT ?
                """
                rows = conn.execute(fts_or_sql, (fts_or, limit)).fetchall()
                if rows:
                    return {
                        "status": "success",
                        "search_mode": "fts5",
                        "count": len(rows),
                        "companies": [dict(r) for r in rows],
                    }
        except sqlite3.OperationalError:
            pass

        # Fallback to multi-column LIKE if FTS yielded no results
        like_sql = """
            SELECT id, company_name, primary_sector, location, founded_year,
                   valuation, company_info, company_background
            FROM companies
            WHERE company_name LIKE ?
               OR company_info LIKE ?
               OR company_background LIKE ?
               OR primary_sector LIKE ?
            LIMIT ?
        """
        pattern = f"%{cleaned_query}%"
        fallback_rows = conn.execute(
            like_sql, (pattern, pattern, pattern, pattern, limit)
        ).fetchall()

        if fallback_rows:
            return {
                "status": "success",
                "search_mode": "fallback_like",
                "count": len(fallback_rows),
                "companies": [dict(r) for r in fallback_rows],
            }

        return {
            "status": "no_results",
            "count": 0,
            "companies": [],
            "message": f"No companies matched the search term '{cleaned_query}'.",
            "guidance": "Try broader keywords or use `get_available_filters` to browse sectors.",
        }


# ============================================================================
# LangChain Tools (Clear parameters & output schema descriptions)
# ============================================================================


@tool
def get_available_filters() -> str:
    """Return all unique sectors and locations available in the unicorn dataset.

    Use this tool whenever you need exact naming for sectors or cities before filtering,
    or when a previous filter returned no results and you need to course-correct.

    Args:
        None.

    Returns:
        JSON string containing:
        - sectors: List[str] of all distinct primary sector names (e.g. ['Payments', 'Banking Tech', ...])
        - locations: List[str] of all distinct company locations (e.g. ['Bengaluru', 'Mumbai', ...])
        - total_sectors: int
        - total_locations: int
    """
    sectors = get_all_sectors()
    locations = get_all_locations()
    return json.dumps(
        {
            "sectors": sectors,
            "locations": locations,
            "total_sectors": len(sectors),
            "total_locations": len(locations),
        },
        indent=2,
    )


@tool
def lookup_company(company_name: str) -> str:
    """Retrieve complete facts and background for a specific company by name.

    Use this tool when answering factual questions about a specific company (e.g. 'What does
    Razorpay do?', 'Who founded BYJU\\'S?', 'What is CRED\\'s valuation?').

    Args:
        company_name (str): The name of the company to look up (e.g. 'Razorpay', 'CRED').

    Returns:
        JSON string with either:
        - On success: {"status": "success", "company": {"company_name": str, "primary_sector": str,
          "location": str, "founded_year": int, "valuation": str, "annual_revenue": str,
          "company_info": str, "company_background": str, "round_led_by": str, "top_investors_1": str, ...}}
        - On not found: {"status": "not_found", "message": str, "suggestions": List[str], "guidance": str}
    """
    res = get_company_by_name(company_name)
    return json.dumps(res, indent=2)


@tool
def filter_companies_tool(
    sector: Optional[str] = None,
    location: Optional[str] = None,
    min_year: Optional[int] = None,
    max_year: Optional[int] = None,
) -> str:
    """Filter unicorn startups by sector, city/location, and/or founding year.

    Use this tool for filtering queries (e.g. 'List fintech startups', 'Which companies are in
    Bengaluru?', 'Startups founded after 2016 in Mumbai').
    Call `get_available_filters` first if you need to know the exact sector or location names.

    Args:
        sector (Optional[str]): Sector name or comma-separated sectors (e.g. 'Payments',
            or 'Payments, Banking Tech'). Substring matching is supported.
        location (Optional[str]): City name or comma-separated cities (e.g. 'Bengaluru',
            or 'Bengaluru, Mumbai').
        min_year (Optional[int]): Minimum founding year (inclusive, e.g. 2015).
        max_year (Optional[int]): Maximum founding year (inclusive, e.g. 2021).

    Returns:
        JSON string containing:
        - On success: {"status": "success", "count": int, "companies": [{"company_name": str,
          "primary_sector": str, "location": str, "founded_year": int, "valuation": str, ...}]}
        - On no results: {"status": "no_results", "count": 0, "companies": [], "message": str,
          "sector_suggestions": List[str], "location_suggestions": List[str], "guidance": str}
    """
    res = filter_companies(
        sector=sector,
        location=location,
        min_year=min_year,
        max_year=max_year,
    )
    return json.dumps(res, indent=2)


@tool
def search_companies_tool(query: str) -> str:
    """Search company backgrounds, descriptions, and capabilities using free-text keywords.

    Use this tool when answering exploratory, capability, or collaborative queries (e.g.
    'Which companies do logistics and delivery?', 'Startups working with speech or voice AI',
    'Platforms offering business loans to retailers').

    Args:
        query (str): Keyword query describing products, technology, or business capabilities.

    Returns:
        JSON string containing:
        - On success: {"status": "success", "count": int, "companies": [{"company_name": str,
          "primary_sector": str, "location": str, "company_info": str, "company_background": str, ...}]}
        - On no results: {"status": "no_results", "count": 0, "companies": [], "message": str, "guidance": str}
    """
    res = search_companies_fts(query)
    return json.dumps(res, indent=2)
