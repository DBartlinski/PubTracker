"""Tag Dimensions publications with VA ORD Broad Portfolios and Actively Managed Portfolios.

Dimensions has no dedicated ORD field, so this infers portfolio membership from
free text (Funding, Acknowledgements, Authors Affiliations, Title, Abstract, MeSH
terms) using two independent signals:

1. Broad Portfolio (high confidence) - VA grant award number prefixes and explicit
   service names. ORD's four legacy R&D services were renamed "Broad Portfolios"
   but kept the same award-number prefixes (verified against research.va.gov):
     CX -> Clinical Science R&D / "Brain, Behavioral and Mental Health"
     BX -> Biomedical Laboratory R&D / "Medical Health"
     RX -> Rehabilitation R&D / "Rehabilitation Research, Development, and Translation"
     HX -> Health Services R&D / "Health Systems Research"
   CSP and QUERI are funding sub-programs surfaced separately when named explicitly.

2. Actively Managed Portfolio (lower confidence) - six cross-cutting, topic-based
   portfolios that span multiple Broad Portfolios. Detected via keyword matching
   against title/abstract/MeSH text since there is no grant-prefix equivalent.

A publication can carry zero, one, or multiple tags in each dimension.
"""
from __future__ import annotations

import re

import pandas as pd

BROAD_PORTFOLIO_NAMES = {
    "CSRD": "Brain, Behavioral and Mental Health",
    "BLRD": "Medical Health",
    "RRD": "Rehabilitation Research, Development, and Translation",
    "HSRD": "Health Systems Research",
    "CSP": "Cooperative Studies Program",
    "QUERI": "Quality Enhancement Research Initiative",
}

# Grant award number prefixes, e.g. "I01CX001849", "1IK6BX006184", "IK2 CX002351", "BX006438".
_GRANT_PREFIX_PATTERNS = {
    "CSRD": re.compile(r"\b(?:\d[A-Z]{0,3})?\s?CX[\s-]?\d{5,7}\b", re.IGNORECASE),
    "BLRD": re.compile(r"\b(?:\d[A-Z]{0,3})?\s?BX[\s-]?\d{5,7}\b", re.IGNORECASE),
    "RRD": re.compile(r"\b(?:\d[A-Z]{0,3})?\s?RX[\s-]?\d{5,7}\b", re.IGNORECASE),
    "HSRD": re.compile(r"\b(?:\d[A-Z]{0,3})?\s?HX[\s-]?\d{5,7}\b", re.IGNORECASE),
}

# Explicit service/program names as written in acknowledgements and affiliations.
_SERVICE_NAME_PATTERNS = {
    "CSRD": re.compile(
        r"clinical science(?:s)? research(?: and| &)? development|"
        r"clinical sciences? r ?& ?d|\bcsr ?& ?d\b|\bcsrd\b",
        re.IGNORECASE,
    ),
    "BLRD": re.compile(
        r"biomedical laboratory research(?: and| &)? development|"
        r"biomedical laboratory r ?& ?d|\bblr ?& ?d\b|\bblrd\b",
        re.IGNORECASE,
    ),
    "RRD": re.compile(
        r"rehabilitation research(?:,)? development(?:,)?(?: and)? translation|"
        r"rehabilitation research(?: and| &)? development|"
        r"rehab(?:ilitation)? r ?& ?d|\brr ?& ?d\b(?!\s*service)|\brrd\b",
        re.IGNORECASE,
    ),
    "HSRD": re.compile(
        r"health services research(?: and| &)? development|"
        r"health systems research(?: and| &)? development|"
        r"\bhsr ?& ?d\b|\bhsrd\b",
        re.IGNORECASE,
    ),
    "CSP": re.compile(
        r"cooperative studies program|\bcsp\s?#?\s?\d{2,4}\b",
        re.IGNORECASE,
    ),
    "QUERI": re.compile(
        r"quality enhancement research initiative|\bqueri\b",
        re.IGNORECASE,
    ),
}

# ORD's six cross-cutting Actively Managed Portfolios (research.va.gov/isrm/amp).
AMP_KEYWORD_PATTERNS = {
    "Gulf War Illness": re.compile(
        r"gulf war illness(?:es)?|\bgwi\b|gulf war veterans?['\u2019]?\s+illness",
        re.IGNORECASE,
    ),
    "Military Exposures": re.compile(
        r"military exposure|burn pit|agent orange|toxic exposure|\bpact act\b|"
        r"airborne hazards|particulate matter exposure",
        re.IGNORECASE,
    ),
    "Pain/Opioid Use (POU)": re.compile(
        r"opioid use disorder|opioid misuse|opioid overdose|opioid prescri|"
        r"chronic pain management|\bopioid\b",
        re.IGNORECASE,
    ),
    "Precision Oncology": re.compile(
        r"precision oncology|\blpop\b|lung precision oncology program|"
        r"precision medicine.{0,20}cancer|genomic.{0,20}oncology",
        re.IGNORECASE,
    ),
    "Suicide Prevention": re.compile(
        r"suicide prevention|suicidal ideation|suicide risk|suicide attempt",
        re.IGNORECASE,
    ),
    "Traumatic Brain Injury": re.compile(
        r"traumatic brain injury|\btbi\b|blast[- ]related brain injury",
        re.IGNORECASE,
    ),
}

FUNDING_TEXT_COLUMNS = ("Funding", "Acknowledgements", "Authors Affiliations")
TOPIC_TEXT_COLUMNS = ("Title", "Abstract", "MeSH terms")


def _combine_text(row: pd.Series, columns: tuple[str, ...]) -> str:
    parts = []
    for column in columns:
        value = row.get(column)
        if pd.notna(value) and str(value).strip():
            parts.append(str(value))
    return " \n ".join(parts)


def extract_broad_portfolios(text: str) -> set[str]:
    """Return the set of Broad Portfolio codes with detectable evidence in `text`."""
    if not text:
        return set()
    found = set()
    for code, pattern in _GRANT_PREFIX_PATTERNS.items():
        if pattern.search(text):
            found.add(code)
    for code, pattern in _SERVICE_NAME_PATTERNS.items():
        if pattern.search(text):
            found.add(code)
    return found


def extract_actively_managed_portfolios(text: str) -> set[str]:
    """Return the set of Actively Managed Portfolio names with keyword matches in `text`."""
    if not text:
        return set()
    return {name for name, pattern in AMP_KEYWORD_PATTERNS.items() if pattern.search(text)}


def tag_publication(row: pd.Series) -> dict:
    """Tag a single Dimensions publication row with ORD portfolio evidence."""
    funding_text = _combine_text(row, FUNDING_TEXT_COLUMNS)
    topic_text = _combine_text(row, TOPIC_TEXT_COLUMNS)

    broad_codes = extract_broad_portfolios(funding_text)
    amps = extract_actively_managed_portfolios(topic_text)
    # Funding text can also carry an explicit AMP name (e.g. "PACT Act Toxic Exposure Funds").
    amps |= extract_actively_managed_portfolios(funding_text)

    broad_names = sorted(BROAD_PORTFOLIO_NAMES[code] for code in broad_codes)
    return {
        "ORD Broad Portfolio Codes": "; ".join(sorted(broad_codes)),
        "ORD Broad Portfolios": "; ".join(broad_names),
        "ORD Actively Managed Portfolios": "; ".join(sorted(amps)),
        "Has ORD Funding Evidence": bool(broad_codes),
    }


def tag_publications(frame: pd.DataFrame) -> pd.DataFrame:
    """Return `frame` with ORD portfolio columns appended."""
    tags = frame.apply(tag_publication, axis=1, result_type="expand")
    return pd.concat([frame, tags], axis=1)
