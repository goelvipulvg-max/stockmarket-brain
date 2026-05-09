"""Loop 1 — PDF Parser: downloads NSE announcement PDFs and extracts structured data."""

import re
import os
import tempfile

import requests
import pdfplumber
from dotenv import load_dotenv
load_dotenv(override=True)


def download_and_parse_nse_pdf(pdf_url: str) -> dict:
    """
    Downloads NSE announcement PDF and extracts key structured data.
    Returns dict with extracted fields.
    """
    result = {
        "pdf_available": False,
        "raw_text": "",
        "dividend_amount": None,
        "dividend_type": None,   # interim/final/special
        "quarter": None,
        "record_date": None,
        "revenue": None,
        "pat": None,
        "yoy_growth": None,
        "buyback_price": None,
        "buyback_quantity": None,
        "key_highlights": [],
    }

    if not pdf_url:
        return result

    try:
        headers = {
            "User-Agent": "Mozilla/5.0",
            "Accept": "application/pdf",
        }
        response = requests.get(pdf_url, headers=headers, timeout=15)
        if response.status_code != 200:
            print(f"     ⚠️  PDF download failed: HTTP {response.status_code}")
            return result

        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            tmp.write(response.content)
            tmp_path = tmp.name

        full_text = ""
        with pdfplumber.open(tmp_path) as pdf:
            for page in pdf.pages[:5]:  # First 5 pages only
                text = page.extract_text()
                if text:
                    full_text += text + "\n"

        os.unlink(tmp_path)

        if not full_text.strip():
            return result

        result["pdf_available"] = True
        result["raw_text"] = full_text[:3000]

        # Dividend amount
        div_match = re.search(
            r'(?:dividend|div)[^\d]*(\d+(?:\.\d+)?)\s*(?:per share|\/share)',
            full_text, re.IGNORECASE,
        )
        if div_match:
            result["dividend_amount"] = float(div_match.group(1))

        # Dividend type
        if re.search(r'interim', full_text, re.IGNORECASE):
            result["dividend_type"] = "interim"
        elif re.search(r'final', full_text, re.IGNORECASE):
            result["dividend_type"] = "final"
        elif re.search(r'special', full_text, re.IGNORECASE):
            result["dividend_type"] = "special"

        # Quarter
        qtr_match = re.search(
            r'(Q[1-4])\s*(?:FY|F\.Y\.?)\s*(\d{2,4})',
            full_text, re.IGNORECASE,
        )
        if qtr_match:
            result["quarter"] = f"{qtr_match.group(1)}FY{qtr_match.group(2)}"

        # Record date
        date_match = re.search(
            r'record\s+date[^\d]*(\d{1,2}[-/]\d{1,2}[-/]\d{2,4})',
            full_text, re.IGNORECASE,
        )
        if date_match:
            result["record_date"] = date_match.group(1)

        # PAT
        pat_match = re.search(
            r'(?:PAT|profit after tax)[^\d]*(\d+(?:,\d+)*(?:\.\d+)?)',
            full_text, re.IGNORECASE,
        )
        if pat_match:
            result["pat"] = pat_match.group(1).replace(",", "")

        return result

    except Exception as e:
        print(f"     ⚠️  PDF parsing error: {e}")
        return result


def get_pdf_context_summary(parsed: dict) -> str:
    """Returns a short human-readable summary of extracted PDF data for AI agents."""
    if not parsed["pdf_available"]:
        return "PDF not available — using title only."

    parts = []
    if parsed["dividend_amount"]:
        dtype = parsed["dividend_type"] or "unknown type"
        parts.append(f"Dividend: Rs{parsed['dividend_amount']}/share ({dtype})")
    if parsed["quarter"]:
        parts.append(f"Quarter: {parsed['quarter']}")
    if parsed["record_date"]:
        parts.append(f"Record date: {parsed['record_date']}")
    if parsed["pat"]:
        parts.append(f"PAT: Rs{parsed['pat']} Cr")

    if parts:
        return "PDF Data: " + " | ".join(parts)
    elif parsed["raw_text"]:
        return f"PDF Text (first 500 chars): {parsed['raw_text'][:500]}"
    else:
        return "PDF downloaded but no structured data extracted."
