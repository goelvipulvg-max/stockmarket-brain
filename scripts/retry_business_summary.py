#!/usr/bin/env python
"""Targeted retry: re-fetch business_summary for 7 companies with stub summaries."""

import json
import os
import sys
import time
from dotenv import load_dotenv

load_dotenv(override=True)

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils.neon_client import get_neon_connection

import yfinance as yf
from openai import OpenAI

DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-v4-flash")
DEEPSEEK_BASE_URL = "https://api.deepseek.com"
API_TIMEOUT = 30

deepseek = OpenAI(
    api_key=os.getenv("DEEPSEEK_API_KEY"),
    base_url=DEEPSEEK_BASE_URL,
)

TARGET = [
    "COFORGE.NS", "GSPL.NS", "HSCL.NS", "JINDALSTEL.NS",
    "NMDC.NS", "WELCORP.NS", "ZYDUSLIFE.NS",
]


def fetch_yfinance_profile(symbol: str) -> dict | None:
    try:
        ticker = yf.Ticker(symbol)
        info = ticker.info
        if not info or not isinstance(info, dict):
            return None
        return {
            "sector": info.get("sector") or info.get("industryDisp") or "",
            "industry": info.get("industry") or "",
            "longBusinessSummary": info.get("longBusinessSummary") or "",
            "longName": info.get("longName") or info.get("shortName") or symbol,
        }
    except Exception as e:
        print(f"yFinance failed: {e}")
        return None


def generate_summary(company_name: str, symbol: str, profile: dict) -> str:
    prompt = (
        f"You are a financial analyst. Given this company data for {company_name} ({symbol}), "
        f"write a 3-sentence investment profile summary covering: what the company does, "
        f"its sector position, and key financial characteristic. "
        f"Data: sector={profile['sector']}, industry={profile['industry']}, "
        f"summary={profile['longBusinessSummary'][:500]}. "
        f"Be concise and factual."
    )
    for attempt in range(2):
        try:
            resp = deepseek.chat.completions.create(
                model=DEEPSEEK_MODEL,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=300,
                temperature=0.3,
                timeout=API_TIMEOUT,
            )
            text = resp.choices[0].message.content.strip()
            if text:
                return text
            if attempt == 0:
                print(f"DeepSeek empty, retrying... ", end="", flush=True)
                time.sleep(2)
        except Exception as e:
            print(f"DeepSeek failed: {e}  ", end="", flush=True)
            if attempt == 1:
                break
            time.sleep(2)

    fallback = (profile.get("longBusinessSummary") or "").strip()
    if fallback:
        print(f"yFinance fallback... ", end="", flush=True)
        return fallback[:1000]
    return ""


def main():
    conn = get_neon_connection()
    cur = conn.cursor()

    success = []
    failed = []

    for symbol in TARGET:
        print(f"  {symbol:<20s} ", end="", flush=True)

        # Fetch current company_name from DB
        cur.execute("SELECT company_name FROM company_profiles WHERE symbol = %s", (symbol,))
        row = cur.fetchone()
        if not row:
            print("SKIP -- not in DB")
            continue
        company_name = row[0]

        # Fetch yFinance profile
        profile = fetch_yfinance_profile(symbol)
        if not profile:
            print("FAIL -- no yFinance data")
            failed.append(symbol)
            continue

        # Generate summary
        summary = generate_summary(company_name, symbol, profile)

        if not summary or len(summary) <= 10:
            print(f"FAIL -- summary too short ({len(summary)} chars)")
            failed.append(symbol)
            continue

        # Update DB
        cur.execute("""
            UPDATE company_profiles
            SET business_summary = %s, updated_at = NOW()
            WHERE symbol = %s
        """, (summary, symbol))

        print(f"OK ({len(summary)} chars)")
        success.append(symbol)

    conn.commit()
    cur.close()
    conn.close()

    print(f"\n  Success: {len(success)}/7 -- {success}")
    if failed:
        print(f"  Failed:  {len(failed)}/7 -- {failed}")
    else:
        print("  All 7 fixed.\n")


if __name__ == "__main__":
    main()
