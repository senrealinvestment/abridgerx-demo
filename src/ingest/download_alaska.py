#!/usr/bin/env python3
"""Download and version Alaska DOH prior-auth medication artifacts.

Source hub: https://health.alaska.gov/en/education/prior-authorization-medication/

Deterministic ingest only — no LLM. Writes data/alaska/raw/ + MANIFEST.json.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import date
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlparse

HUB_URL = "https://health.alaska.gov/en/education/prior-authorization-medication/"
USER_AGENT = (
    "AbridgeRx-ingest/1.0 (+https://github.com/senrealinvestment/abridgerx; "
    "research; respectful; contact senrealinvestment@gmail.com)"
)
DOWNLOAD_DATE = "2026-09-26"  # America/New_York per ingest run
ROOT = Path(__file__).resolve().parents[2]
RAW_DIR = ROOT / "data" / "alaska" / "raw"
MANIFEST_PATH = RAW_DIR / "MANIFEST.json"
SOURCES_MD = RAW_DIR / "SOURCES.md"

# Non-media pages we intentionally skip / document as blockers
KNOWN_BLOCKERS = [
    {
        "label": "Drug Lookup Tool",
        "url": "https://ak.primetherapeutics.com/provider/",
        "status": "skipped",
        "reason": "JS/portal Drug Lookup Tool (Prime Therapeutics); no static export linked from hub",
        "category": "drug_lookup_portal",
    },
    {
        "label": "Electronic Prior Authorization (ePA)",
        "url": "https://www.covermymeds.health/prior-authorization-forms/prime",
        "status": "skipped",
        "reason": "CoverMyMeds ePA portal; not a DOH criteria artifact",
        "category": "epa_portal",
    },
]


class LinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[tuple[str, str, str]] = []
        self._href: str | None = None
        self._text: list[str] = []
        self._section = ""
        self._heading = False
        self._heading_buf: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        d = {k: (v or "") for k, v in attrs}
        if tag in ("h2", "h3", "h4"):
            self._heading = True
            self._heading_buf = []
        if tag == "a" and "href" in d:
            self._href = d["href"]
            self._text = []

    def handle_data(self, data: str) -> None:
        if self._href is not None:
            self._text.append(data)
        if self._heading:
            self._heading_buf.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag in ("h2", "h3", "h4") and self._heading:
            self._section = re.sub(r"\s+", " ", "".join(self._heading_buf)).strip()
            self._heading = False
        if tag == "a" and self._href is not None:
            text = re.sub(r"\s+", " ", "".join(self._text)).strip()
            self.links.append((text, self._href, self._section))
            self._href = None


def fetch_bytes(url: str, timeout: int = 120) -> tuple[bytes, str]:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "*/*",
        },
        method="GET",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = resp.read()
        ctype = resp.headers.get("Content-Type", "application/octet-stream").split(";")[0].strip()
        return data, ctype


def fetch_text(url: str, timeout: int = 60) -> str:
    data, _ = fetch_bytes(url, timeout=timeout)
    return data.decode("utf-8", errors="replace")


def classify(label: str, filename: str) -> str:
    l = label.lower()
    f = filename.lower()
    if "interim" in l or "interim" in f:
        return "interim_pa"
    if "prior-authorization-list" in f or label == "Prior Authorization Medication List":
        return "pa_list"
    if "max_units" in f or "maximum-units" in f or "Maximum Units" in label:
        return "max_units"
    if ("pdl" in f or label.startswith("Preferred Drug List")) and "legend" not in f and "legend" not in l:
        return "pdl"
    if "legend" in l or "pdl-legend" in f:
        return "pdl_legend"
    if "90-day" in l or "90-days" in f:
        return "ninety_day"
    if "cost_exceeds" in f or "Cost Exceeds" in label:
        return "form_cost_exceeds"
    if "general_pa" in f or "General Medication" in label:
        return "form_general_pa"
    if "benifits" in f or "Pamphlet" in label:
        return "pamphlet"
    if "attestation" in l or "attestation" in f:
        return "attestation"
    if label.strip() in ("Form", "| Form", "") and ("form" in f or "pa" in f):
        return "form"
    if "_pa_form" in f or f.endswith("_form.pdf"):
        return "form"
    if "criteria" in l or "criteria" in f or "Criteria" in label:
        return "criteria"
    # Oral buprenorphine MAT doc is criteria-like
    if "buprenorphine" in f or "buprenorphine" in l:
        return "criteria"
    return "other"


def guess_effective_date(label: str, filename: str, page_context: str = "") -> str | None:
    """Best-effort ISO date from filename or adjacent page text."""
    candidates: list[str] = []
    # From page label context like "effective 11/1/25" or "Effective 01/1/26"
    for m in re.finditer(
        r"(?:effective|Effective)\s+(\d{1,2})[/.-](\d{1,2})[/.-](\d{2,4})",
        page_context or label,
    ):
        mo, d, y = m.groups()
        yi = int(y)
        if yi < 100:
            yi += 2000
        candidates.append(f"{yi:04d}-{int(mo):02d}-{int(d):02d}")
    # YYYYMMDD or YYYY-MM-DD in filename
    for m in re.finditer(r"(20\d{2})(\d{2})(\d{2})", filename):
        y, mo, d = m.groups()
        candidates.append(f"{y}-{mo}-{d}")
    for m in re.finditer(r"(20\d{2})[-_](\d{2})[-_](\d{2})", filename):
        y, mo, d = m.groups()
        candidates.append(f"{y}-{mo}-{d}")
    # year-only in filename as weak signal
    if not candidates:
        ym = re.search(r"(20\d{2})", filename)
        if ym:
            return f"{ym.group(1)}-01-01"  # year-only; note as approximate elsewhere
    return candidates[-1] if candidates else None


def safe_filename(url: str, label: str, category: str) -> str:
    base = urlparse(url).path.split("/")[-1]
    base = re.sub(r"[^\w.\-]+", "_", base)
    if not base.lower().endswith((".pdf", ".xls", ".xlsx", ".csv", ".doc", ".docx", ".zip")):
        base = base + ".bin"
    # Prefix category for major lists for easy discovery
    prefix_map = {
        "pa_list": "list_pa_",
        "interim_pa": "list_interim_pa_",
        "pdl": "list_pdl_",
        "pdl_legend": "list_pdl_legend_",
        "max_units": "list_max_units_",
        "ninety_day": "list_90day_",
        "form_general_pa": "form_",
        "form_cost_exceeds": "form_",
        "form": "form_",
        "criteria": "criteria_",
        "attestation": "attestation_",
        "pamphlet": "pamphlet_",
    }
    prefix = prefix_map.get(category, "")
    # Avoid double-prefixing if already named
    if prefix and not base.startswith(prefix):
        # For criteria keep original media slug but ensure unique under criteria/
        pass
    return base


def collect_media_links(html: str) -> list[dict]:
    parser = LinkParser()
    parser.feed(html)
    by_url: dict[str, dict] = {}
    for text, href, section in parser.links:
        url = urljoin(HUB_URL, href)
        parsed = urlparse(url)
        path = parsed.path.lower()
        host = parsed.netloc.lower()
        if "health.alaska.gov" not in host and "dhss.alaska.gov" not in host:
            continue
        if "/media/" not in path:
            continue
        filename = parsed.path.split("/")[-1]
        if not filename:
            continue
        label = text or filename
        # Prefer longer Criteria labels over bare "Form"
        existing = by_url.get(url)
        cat = classify(label, filename)
        entry = {
            "label": label,
            "url": url,
            "section": section,
            "category": cat,
            "filename_hint": filename,
        }
        if existing is None:
            by_url[url] = entry
        else:
            # Upgrade label if better
            if ("Criteria" in label or "List" in label) and len(label) > len(existing["label"]):
                by_url[url] = entry
            elif existing["label"] in ("Form", "| Form", "") and label:
                by_url[url]["label"] = label
                by_url[url]["category"] = classify(label, filename)
    return list(by_url.values())


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def write_sources_md(entries: list[dict]) -> None:
    lines = [
        "# Alaska Medicaid source artifacts",
        "",
        f"Hub: {HUB_URL}",
        "",
        f"Download date: {DOWNLOAD_DATE} (America/New_York)",
        "",
        "Generated by `src/ingest/download_alaska.py`. See `MANIFEST.json` for SHA-256 and status.",
        "",
        "## Categories downloaded",
        "",
    ]
    cats: dict[str, int] = {}
    for e in entries:
        if e.get("status") == "ok":
            cats[e["category"]] = cats.get(e["category"], 0) + 1
    for c, n in sorted(cats.items()):
        lines.append(f"- `{c}`: {n}")
    lines += [
        "",
        "## Blockers / skipped",
        "",
    ]
    for b in KNOWN_BLOCKERS:
        lines.append(f"- **{b['label']}**: {b['url']} — {b['reason']}")
    lines += [
        "",
        "## Tracked lists (minimum)",
        "",
        "- Prior Authorization Medication List",
        "- Interim Prior Authorization List",
        "- Preferred Drug List (PDL) + legend",
        "- Maximum Units Medication List (all dated versions on hub)",
        "- 90-Day Generic Medication List",
        "- Per-drug Criteria PDFs + PA forms linked from hub",
        "",
        "Drug Lookup Tool export is **not** available as a static file from this hub.",
        "",
    ]
    SOURCES_MD.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Fetching hub HTML: {HUB_URL}", flush=True)
    html = fetch_text(HUB_URL)
    (RAW_DIR / "_hub_page.html").write_text(html, encoding="utf-8")
    items = collect_media_links(html)
    print(f"Discovered {len(items)} unique media URLs", flush=True)

    # Also capture page-level effective dates from link text neighborhoods
    # Re-parse with surrounding text for effective dates: store label as-is
    manifest: list[dict] = []

    # Save hub page as a recorded artifact
    hub_bytes = html.encode("utf-8")
    hub_name = "_hub_prior-authorization-medication.html"
    (RAW_DIR / hub_name).write_bytes(hub_bytes)
    manifest.append(
        {
            "filename": hub_name,
            "source_url": HUB_URL,
            "effective_date": None,
            "download_date": DOWNLOAD_DATE,
            "sha256": sha256_bytes(hub_bytes),
            "bytes": len(hub_bytes),
            "content_type": "text/html",
            "category": "hub_page",
            "label": "Prior Authorization Medication hub page",
            "status": "ok",
            "notes": "Snapshot of source hub HTML used for link discovery",
        }
    )

    for i, item in enumerate(sorted(items, key=lambda x: (x["category"], x["filename_hint"]))):
        url = item["url"]
        filename = safe_filename(url, item["label"], item["category"])
        # Disambiguate collisions
        dest = RAW_DIR / filename
        if dest.exists() and any(m.get("filename") == filename for m in manifest):
            stem = Path(filename).stem
            suf = Path(filename).suffix
            filename = f"{stem}_{sha256_bytes(url.encode())[:8]}{suf}"
            dest = RAW_DIR / filename

        eff = guess_effective_date(item["label"], item["filename_hint"])
        # Try to pull effective date from hub HTML near the link
        # Simple: search for filename slug then look for Effective nearby
        slug = item["filename_hint"]
        idx = html.find(slug)
        if idx != -1:
            window = html[max(0, idx - 400) : idx + 200]
            # strip tags for date search
            window_txt = re.sub(r"<[^>]+>", " ", window)
            eff2 = guess_effective_date(item["label"], slug, window_txt)
            if eff2:
                # Prefer page "effective" over year-only filename
                if eff is None or (eff.endswith("-01-01") and not eff2.endswith("-01-01")):
                    eff = eff2
                elif not eff.endswith("-01-01"):
                    pass
                else:
                    eff = eff2

        print(f"[{i+1}/{len(items)}] {item['category']}: {filename}", flush=True)
        try:
            data, ctype = fetch_bytes(url)
            dest.write_bytes(data)
            entry = {
                "filename": filename,
                "source_url": url,
                "effective_date": eff,
                "download_date": DOWNLOAD_DATE,
                "sha256": sha256_bytes(data),
                "bytes": len(data),
                "content_type": ctype,
                "category": item["category"],
                "label": item["label"],
                "section": item.get("section") or None,
                "status": "ok",
                "notes": None,
            }
            # Soft-check PDF magic
            if filename.lower().endswith(".pdf") and not data.startswith(b"%PDF"):
                entry["notes"] = "Downloaded but missing %PDF magic; may be HTML error page"
                if b"<html" in data[:500].lower():
                    entry["status"] = "failed"
                    entry["notes"] = "Expected PDF but received HTML"
                    dest.unlink(missing_ok=True)
            manifest.append(entry)
        except urllib.error.HTTPError as e:
            manifest.append(
                {
                    "filename": filename,
                    "source_url": url,
                    "effective_date": eff,
                    "download_date": DOWNLOAD_DATE,
                    "sha256": None,
                    "bytes": 0,
                    "content_type": None,
                    "category": item["category"],
                    "label": item["label"],
                    "section": item.get("section") or None,
                    "status": "failed",
                    "notes": f"HTTP {e.code}: {e.reason}",
                }
            )
            print(f"  FAILED HTTP {e.code}", flush=True)
        except Exception as e:  # noqa: BLE001
            manifest.append(
                {
                    "filename": filename,
                    "source_url": url,
                    "effective_date": eff,
                    "download_date": DOWNLOAD_DATE,
                    "sha256": None,
                    "bytes": 0,
                    "content_type": None,
                    "category": item["category"],
                    "label": item["label"],
                    "section": item.get("section") or None,
                    "status": "failed",
                    "notes": f"{type(e).__name__}: {e}",
                }
            )
            print(f"  FAILED {e}", flush=True)
        time.sleep(0.15)  # be polite

    for b in KNOWN_BLOCKERS:
        manifest.append(
            {
                "filename": None,
                "source_url": b["url"],
                "effective_date": None,
                "download_date": DOWNLOAD_DATE,
                "sha256": None,
                "bytes": 0,
                "content_type": None,
                "category": b["category"],
                "label": b["label"],
                "section": None,
                "status": b["status"],
                "notes": b["reason"],
            }
        )

    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    write_sources_md(manifest)
    ok = sum(1 for m in manifest if m.get("status") == "ok")
    failed = sum(1 for m in manifest if m.get("status") == "failed")
    skipped = sum(1 for m in manifest if m.get("status") == "skipped")
    total_bytes = sum(m.get("bytes") or 0 for m in manifest if m.get("status") == "ok")
    print(
        f"Done. ok={ok} failed={failed} skipped={skipped} bytes={total_bytes} "
        f"manifest={MANIFEST_PATH}",
        flush=True,
    )
    return 0 if failed == 0 else 0  # still success for partial; failures recorded


if __name__ == "__main__":
    sys.exit(main())
