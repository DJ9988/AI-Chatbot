"""Comprehensive test suite covering all query types and course-correction mechanisms in tools.db_tools.

Query Types Tested:
1. Factual Lookups:
   - Exact case company match ("Razorpay")
   - Case-insensitive company match ("cred" -> "CRED")
   - Whitespace trimming ("  Swiggy  ")
   - Punctuation / Special characters ("BYJU'S", "Cult.fit")
   - Substring company match ("Ather" -> "Ather Energy")
   - Misspelled company course correction ("Razor pay" -> suggests "Razorpay")
   - Non-existent company handling & guidance
   - Empty / whitespace query validation
2. Exploratory & Filtering Queries:
   - Exact primary sector filter ("Payments")
   - Substring sector matching ("E-Commerce", "EdTech")
   - Multi-sector comma-separated querying ("Payments, Banking Tech")
   - Exact location filter ("Mumbai")
   - Multi-location comma-separated querying ("Bengaluru, Mumbai")
   - Combined sector + location filter ("Payments" in "Bengaluru")
   - Founded year range filters (min_year, max_year)
   - Multi-condition filter (sector + location + year)
   - Near-miss filter course-correction (misspelled sector/location -> suggestions)
   - SQL Injection immunity verification
3. Keyword & Collaborative Search (FTS5):
   - Business capability keywords ("payment gateway")
   - Multi-word collaboration search ("delivery and logistics")
   - FTS5 special character escaping (quotes, brackets, boolean operators)
   - Zero-match search guidance
   - Empty search validation
4. Discovery & LangChain Tool Integration:
   - get_available_filters tool
   - Direct LangChain tool `.invoke(...)` execution
"""

import json
import sys
from pathlib import Path

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import pytest

from tools.db_tools import (
    escape_fts5_query,
    filter_companies,
    filter_companies_tool,
    get_all_locations,
    get_all_sectors,
    get_available_filters,
    get_company_by_name,
    lookup_company,
    search_companies_fts,
    search_companies_tool,
)


# ============================================================================
# 1. Factual Company Lookup Query Tests
# ============================================================================


def test_lookup_exact_name():
    """Verify exact case-sensitive lookup for a known company."""
    res = get_company_by_name("Razorpay")
    assert res["status"] == "success"
    assert res["company"]["company_name"] == "Razorpay"
    assert res["company"]["primary_sector"] == "Payments"
    assert res["company"]["location"] == "Bengaluru"


def test_lookup_case_insensitive():
    """Verify case-insensitive lookup."""
    res = get_company_by_name("cred")
    assert res["status"] == "success"
    assert res["company"]["company_name"] == "CRED"


def test_lookup_with_whitespace():
    """Verify company name with surrounding whitespace."""
    res = get_company_by_name("   Swiggy   ")
    assert res["status"] == "success"
    assert res["company"]["company_name"] == "Swiggy"


def test_lookup_special_characters():
    """Verify company names with apostrophes or dots (e.g. BYJU'S, Cult.fit)."""
    res = get_company_by_name("BYJU'S")
    assert res["status"] == "success"
    assert res["company"]["company_name"] == "BYJU'S"

    res2 = get_company_by_name("Cult.fit")
    assert res2["status"] == "success"
    assert res2["company"]["company_name"] == "Cult.fit"


def test_lookup_alphanumeric_punctuation_variations():
    """Verify informal or unpunctuated user queries match canonical names."""
    # "Byjus" matches "BYJU'S"
    res_byjus = get_company_by_name("Byjus")
    assert res_byjus["status"] == "success"
    assert res_byjus["company"]["company_name"] == "BYJU'S"

    # "cult fit" matches "Cult.fit"
    res_cult = get_company_by_name("cult fit")
    assert res_cult["status"] == "success"
    assert res_cult["company"]["company_name"] == "Cult.fit"

    # "Razor pay" matches "Razorpay"
    res_rp = get_company_by_name("Razor pay")
    assert res_rp["status"] == "success"
    assert res_rp["company"]["company_name"] == "Razorpay"


def test_lookup_substring_match():
    """Verify partial name matching (e.g. 'Ather' matches 'Ather Energy')."""
    res = get_company_by_name("Ather")
    assert res["status"] == "success"
    assert "Ather Energy" in res["company"]["company_name"]


def test_lookup_misspelled_course_correction():
    """Verify that a misspelled company name returns close match suggestions for course-correction."""
    res = get_company_by_name("Razorpai")
    assert res["status"] == "not_found"
    assert "suggestions" in res
    assert "Razorpay" in res["suggestions"]
    assert "guidance" in res


def test_lookup_nonexistent_company():
    """Verify handling of completely non-existent company name."""
    res = get_company_by_name("TotallyFakeEnterpriseXYZ123")
    assert res["status"] == "not_found"
    assert res["suggestions"] == []
    assert "search_companies_tool" in res["guidance"]


def test_lookup_empty_query():
    """Verify empty or blank query validation."""
    res = get_company_by_name("   ")
    assert res["status"] == "error"
    assert "cannot be empty" in res["message"]


# ============================================================================
# 2. Exploratory & Filtering Query Tests
# ============================================================================


def test_filter_exact_sector():
    """Verify filtering by exact sector."""
    res = filter_companies(sector="Payments")
    assert res["status"] == "success"
    assert res["count"] > 0
    names = [c["company_name"] for c in res["companies"]]
    assert "Razorpay" in names
    assert "BharatPe" in names or "BillDesk" in names


def test_filter_substring_sector():
    """Verify substring matching across sectors (e.g. 'E-Commerce' or 'EdTech')."""
    res_ecom = filter_companies(sector="E-Commerce")
    assert res_ecom["status"] == "success"
    assert res_ecom["count"] >= 10

    res_edtech = filter_companies(sector="EdTech")
    assert res_edtech["status"] == "success"
    assert res_edtech["count"] > 0


def test_filter_multi_sector_comma_separated():
    """Verify multi-sector query passed as a comma-separated string."""
    res = filter_companies(sector="Payments, Banking Tech, Alternative Lending")
    assert res["status"] == "success"
    assert res["count"] >= 10
    sectors = {c["primary_sector"] for c in res["companies"]}
    assert len(sectors) > 1


def test_filter_exact_location():
    """Verify filtering by location."""
    res = filter_companies(location="Mumbai")
    assert res["status"] == "success"
    assert res["count"] > 0
    assert all(c["location"] == "Mumbai" for c in res["companies"])


def test_filter_multi_location_comma_separated():
    """Verify querying multiple cities in one call."""
    res = filter_companies(location="Bengaluru, Mumbai")
    assert res["status"] == "success"
    assert res["count"] > 0
    locations = {c["location"] for c in res["companies"]}
    assert "Bengaluru" in locations or "Mumbai" in locations


def test_filter_combined_sector_and_location():
    """Verify combined filtering (e.g. Payments startups in Bengaluru)."""
    res = filter_companies(sector="Payments", location="Bengaluru")
    assert res["status"] == "success"
    assert res["count"] > 0
    assert all(c["location"] == "Bengaluru" for c in res["companies"])
    names = [c["company_name"] for c in res["companies"]]
    assert "Razorpay" in names


def test_filter_founded_year_range():
    """Verify filtering by founded year range."""
    res = filter_companies(min_year=2018, max_year=2021)
    assert res["status"] == "success"
    assert res["count"] > 0
    for c in res["companies"]:
        if c["founded_year"] is not None:
            assert 2018 <= c["founded_year"] <= 2021


def test_filter_multi_condition_all():
    """Verify multi-condition filter combining sector, location, and year."""
    res = filter_companies(sector="Payments", location="Bengaluru", min_year=2014)
    assert res["status"] == "success"
    for c in res["companies"]:
        assert c["location"] == "Bengaluru"
        if c["founded_year"] is not None:
            assert c["founded_year"] >= 2014


def test_filter_near_miss_course_correction():
    """Verify that when a filter yields 0 matches, near-miss suggestions are provided."""
    res = filter_companies(sector="PaymntsMisspelled", location="MumbaCity")
    assert res["status"] == "no_results"
    assert res["count"] == 0
    assert "guidance" in res
    assert "get_available_filters" in res["guidance"]


def test_filter_sql_injection_immunity():
    """Verify parameterized queries prevent SQL injection."""
    malicious_sector = "' OR '1'='1"
    malicious_location = "'; DROP TABLE companies; --"
    res = filter_companies(sector=malicious_sector, location=malicious_location)
    assert res["status"] == "no_results"
    assert res["count"] == 0


# ============================================================================
# 3. Keyword, Subjective & Semantic Search (FTS5) Tests
# ============================================================================


def test_search_fts_specific_keywords():
    """Verify full-text search with business keywords."""
    res = search_companies_fts("payment gateway")
    assert res["status"] == "success"
    assert res["count"] > 0
    names = [c["company_name"] for c in res["companies"]]
    assert "Razorpay" in names or "BillDesk" in names or "Cashfree" in names


def test_search_fts_collaboration_query():
    """Verify search for collaborative/capability queries (e.g. logistics delivery)."""
    res = search_companies_fts("delivery and logistics")
    assert res["status"] == "success"
    assert res["count"] > 0
    names = [c["company_name"] for c in res["companies"]]
    assert any(n in names for n in ["Delhivery", "Xpressbees", "Shadowfax", "BlackBuck"])


def test_search_fts_syntax_escaping():
    """Verify that special characters in query string do not trigger SQLite FTS syntax errors."""
    special_queries = [
        "payments AND (lending OR crypto*)",
        'test "unclosed quotes',
        "ai & ml * -> ^ :",
        "---",
        "NOT something",
    ]
    for q in special_queries:
        res = search_companies_fts(q)
        assert res["status"] in ("success", "no_results")


def test_search_fts_no_results():
    """Verify guidance when a keyword has no matches."""
    res = search_companies_fts("supercalifragilisticexpialidocious")
    assert res["status"] == "no_results"
    assert res["count"] == 0
    assert "Try broader keywords" in res["guidance"]


def test_search_fts_empty_query():
    """Verify empty search query handling."""
    res = search_companies_fts("   ")
    assert res["status"] == "error"
    assert "cannot be empty" in res["message"]


# ============================================================================
# 4. LangChain Tool Wrapper & Parameter Discovery Tests
# ============================================================================


def test_get_available_filters_tool():
    """Verify get_available_filters returns distinct sectors and locations."""
    output = get_available_filters.invoke({})
    data = json.loads(output)
    assert data["total_sectors"] > 50
    assert data["total_locations"] > 15
    assert "Payments" in data["sectors"]
    assert "Bengaluru" in data["locations"]


def test_langchain_lookup_company_tool_invoke():
    """Verify invoking the lookup_company LangChain tool."""
    raw = lookup_company.invoke({"company_name": "Zerodha"})
    data = json.loads(raw)
    assert data["status"] == "success"
    assert data["company"]["company_name"] == "Zerodha"
    assert "online trading" in data["company"]["company_background"].casefold()
    assert data["company"]["primary_sector"] == "Investment Tech"


def test_langchain_filter_tool_invoke():
    """Verify invoking the filter_companies_tool LangChain tool."""
    raw = filter_companies_tool.invoke({"sector": "Gaming", "location": "Mumbai"})
    data = json.loads(raw)
    assert data["status"] == "success"
    assert data["count"] > 0
    assert any(c["company_name"] == "Games24x7" for c in data["companies"])


def test_langchain_search_tool_invoke():
    """Verify invoking the search_companies_tool LangChain tool."""
    raw = search_companies_tool.invoke({"query": "electric vehicles"})
    data = json.loads(raw)
    assert data["status"] == "success"
    names = [c["company_name"] for c in data["companies"]]
    assert "Ola Electric" in names or "Ather Energy" in names


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__]))

