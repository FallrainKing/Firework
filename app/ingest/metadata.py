"""arXiv metadata fetching (Task 5).

``fetch_arxiv_metadata`` queries the public arXiv Atom API
(``http://export.arxiv.org/api/query?id_list={id}``), parses the XML with
the stdlib ElementTree (no lxml), and returns a :class:`PaperMeta`. The
``arxiv_id`` argument accepts a bare id, an ``arXiv:2401.00001v2``-style
identifier, or a full abs-page URL; the version suffix is always stripped
before the request.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass

import httpx

ARXIV_API_URL = "http://export.arxiv.org/api/query?id_list={id}"

# arXiv's category elements already include the primary category, so only the
# Atom namespace is needed for parsing.
_ATOM = "http://www.w3.org/2005/Atom"


@dataclass
class PaperMeta:
    """Bibliographic metadata for one arXiv paper."""

    arxiv_id: str
    title: str
    authors: list[str]
    abstract: str
    categories: list[str]
    published: str


# New-style ids (2401.00001, 2401.00001v2) and old-style ones (hep-th/9901001).
_ABS_PATH_RE = re.compile(r"abs/([^?#]+)")
_NEW_ID_RE = re.compile(r"(\d{4}\.\d{4,5})(v\d+)?$")
_OLD_ID_RE = re.compile(r"([a-z-]+(?:\.[a-z]{2})?/\d{7})(v\d+)?$")
_VERSION_RE = re.compile(r"v\d+$")


def extract_arxiv_id(value: str) -> str:
    """Reduce any accepted input form to a bare, version-less arXiv id.

    Accepted forms: ``2401.00001``, ``2401.00001v2``, ``arXiv:2401.00001v2``,
    ``http(s)://arxiv.org/abs/2401.00001v2`` (query strings tolerated), and
    old-style ids like ``hep-th/9901001`` (bare or inside an abs URL).
    Raises ``ValueError`` when no id can be extracted.
    """
    text = value.strip()
    abs_match = _ABS_PATH_RE.search(text)
    if abs_match:
        text = abs_match.group(1)
    elif ":" in text:
        text = text.rsplit(":", 1)[-1]
    text = text.strip().lower()
    match = _NEW_ID_RE.match(text) or _OLD_ID_RE.match(text)
    if not match:
        raise ValueError(f"could not extract an arXiv id from {value!r}")
    return _VERSION_RE.sub("", match.group(1))


def parse_arxiv_atom(xml_text: str, arxiv_id: str) -> PaperMeta:
    """Parse an arXiv Atom API response into a :class:`PaperMeta`."""
    root = ET.fromstring(xml_text)
    entry = root.find(f"{{{_ATOM}}}entry")
    if entry is None:
        raise ValueError(f"arXiv response for {arxiv_id!r} contains no entry")

    title = re.sub(r"\s+", " ", entry.findtext(f"{{{_ATOM}}}title") or "").strip()
    abstract = re.sub(r"\s+", " ", entry.findtext(f"{{{_ATOM}}}summary") or "").strip()
    authors = [
        (author.findtext(f"{{{_ATOM}}}name") or "").strip()
        for author in entry.findall(f"{{{_ATOM}}}author")
    ]
    categories = [
        category.get("term")
        for category in entry.findall(f"{{{_ATOM}}}category")
        if category.get("term")
    ]
    published = (entry.findtext(f"{{{_ATOM}}}published") or "").strip()

    return PaperMeta(
        arxiv_id=arxiv_id,
        title=title,
        authors=authors,
        abstract=abstract,
        categories=categories,
        published=published,
    )


async def fetch_arxiv_metadata(arxiv_id: str) -> PaperMeta:
    """Fetch metadata for one paper from the arXiv Atom API."""
    paper_id = extract_arxiv_id(arxiv_id)
    url = ARXIV_API_URL.format(id=paper_id)
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.get(url)
        response.raise_for_status()
    return parse_arxiv_atom(response.text, paper_id)
