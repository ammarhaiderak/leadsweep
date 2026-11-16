"""Multi-Format Dataset Exporter (Phase G & Surgical Export Fix).

Provides streaming generators, multi-format export (csv, json, jsonl, xlsx, tsv, xml),
UTF-8 BOM support for Excel, CSV formula injection mitigation, and HTML unescaping.
"""
# NEW FEATURE: Enhanced Multi-Format Streaming Exporter
from __future__ import annotations

import csv
import html
import io
import json
import re
from collections.abc import Iterable, Sequence
from typing import Any

EXPORT_FORMATS: tuple[str, ...] = ("json", "jsonl", "csv", "tsv", "xlsx", "xml")

MEDIA_TYPES: dict[str, str] = {
    "json": "application/json; charset=utf-8",
    "jsonl": "application/x-ndjson; charset=utf-8",
    "csv": "text/csv; charset=utf-8",
    "tsv": "text/tab-separated-values; charset=utf-8",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "xml": "application/xml; charset=utf-8",
}

# Standard column schemas
LEADS_EXPORT_COLUMNS: list[str] = [
    "platform",
    "author/channel",
    "post URL",
    "published date",
    "text",
    "evaluator",
    "model",
    "category",
    "score",
    "poster role",
    "reason",
    "evidence quote",
    "likes",
    "replies",
    "views",
    "job id",
]

RAW_EXPORT_COLUMNS: list[str] = [
    "id",
    "platform",
    "username",
    "displayName",
    "url",
    "content",
    "likes",
    "retweets",
    "replies",
    "followers",
    "createdAt",
    "sentiment",
    "scrapedAt",
]

PROFILE_EXPORT_COLUMNS: list[str] = [
    "handle",
    "name",
    "bio",
    "location",
    "website",
    "followers",
    "following",
    "posts",
    "verified",
    "profile url",
    "fetched at",
]


def _clean_cell_value(val: Any) -> str:
    """Unescape HTML, clean line endings, and protect against formula injection."""
    if val is None:
        return ""
    if isinstance(val, list):
        s = "; ".join(str(x) for x in val)
    elif isinstance(val, dict):
        s = json.dumps(val, ensure_ascii=False)
    else:
        s = str(val)

    # Decode HTML entities (e.g. &amp; -> &)
    s = html.unescape(s)
    # Normalize line endings
    s = s.replace("\r\n", "\n").replace("\r", "\n")

    # CSV injection prevention: If string starts with =, +, -, @, prefix with a single quote '
    if s and s[0] in ("=", "+", "-", "@"):
        s = f"'{s}"
    return s


# Alias for testability
sanitize_cell_value = _clean_cell_value


class DatasetExporter:
    """Formats polymorphic dataset items into the requested representation."""

    @staticmethod
    def export(
        dataset_id: str,
        items: Sequence[dict[str, Any]],
        fmt: str = "json",
        root_tag: str = "dataset"
    ) -> tuple[bytes | str, str]:
        """Synchronous export helper returning (content, media_type)."""
        key = (fmt or "").strip().lower()
        if key not in MEDIA_TYPES:
            raise ValueError(
                f"Unsupported export format {fmt!r}. Supported: {', '.join(EXPORT_FORMATS)}"
            )
        rows = list(items or [])
        if key == "json":
            return DatasetExporter.to_json(rows), MEDIA_TYPES[key]
        elif key == "jsonl":
            return DatasetExporter.to_jsonl(rows), MEDIA_TYPES[key]
        elif key == "csv":
            return DatasetExporter.to_csv(rows), MEDIA_TYPES[key]
        elif key == "tsv":
            return DatasetExporter.to_tsv(rows), MEDIA_TYPES[key]
        elif key == "xlsx":
            return DatasetExporter.to_xlsx_bytes(rows), MEDIA_TYPES[key]
        else:
            return DatasetExporter.to_xml(rows, root_tag=root_tag or dataset_id), MEDIA_TYPES[key]

    @staticmethod
    def to_json(items: Sequence[dict[str, Any]]) -> str:
        return json.dumps(list(items), indent=2, ensure_ascii=False)

    @staticmethod
    def to_jsonl(items: Sequence[dict[str, Any]]) -> str:
        return "\n".join(json.dumps(it, ensure_ascii=False) for it in items)

    @staticmethod
    def to_csv(items: Sequence[dict[str, Any]], delimiter: str = ",", as_bytes: bool = False, fieldnames: Sequence[str] | None = None) -> str | bytes:
        """Return CSV string (or UTF-8 bytes with BOM if as_bytes=True).
        
        Begins with UTF-8 BOM (\ufeff) so both string assertions and Excel parsing work correctly.
        Always outputs header row.
        """
        out = io.StringIO()
        out.write("\ufeff")  # Excel UTF-8 BOM

        cols: list[str] = list(fieldnames) if fieldnames else []
        if not cols and items:
            for it in items:
                for k in it.keys():
                    if k not in cols:
                        cols.append(k)
        if not cols:
            cols = list(LEADS_EXPORT_COLUMNS)

        writer = csv.DictWriter(
            out,
            fieldnames=cols,
            delimiter=delimiter,
            quoting=csv.QUOTE_ALL,
            extrasaction="ignore"
        )
        writer.writeheader()
        for it in (items or []):
            row = {k: _clean_cell_value(it.get(k)) for k in cols}
            writer.writerow(row)

        val = out.getvalue()
        return val.encode("utf-8") if as_bytes else val

    @staticmethod
    def to_tsv(items: Sequence[dict[str, Any]], as_bytes: bool = False) -> str | bytes:
        return DatasetExporter.to_csv(items, delimiter="\t", as_bytes=as_bytes)

    @staticmethod
    def to_xlsx_bytes(items: Sequence[dict[str, Any]]) -> bytes:
        """Create standard XLSX workbook using openpyxl in write_only mode for memory efficiency."""
        import openpyxl

        wb = openpyxl.Workbook(write_only=True)
        ws = wb.create_sheet("LeadSweep Export")

        fieldnames: list[str] = []
        for it in items:
            for k in it.keys():
                if k not in fieldnames:
                    fieldnames.append(k)

        if fieldnames:
            ws.append(fieldnames)
            for it in items:
                row_vals = [_clean_cell_value(it.get(k)) for k in fieldnames]
                ws.append(row_vals)
        else:
            ws.append(["id", "platform", "content"])

        buf = io.BytesIO()
        wb.save(buf)
        return buf.getvalue()

    @staticmethod
    def to_xml(items: Sequence[dict[str, Any]], root_tag: str = "dataset") -> str:
        out = [f"<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n<{root_tag}>"]
        for it in items:
            out.append("  <item>")
            for k, v in it.items():
                safe_val = _clean_cell_value(v).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                out.append(f"    <{k}>{safe_val}</{k}>")
            out.append("  </item>")
        out.append(f"</{root_tag}>")
        return "\n".join(out)

    # -------------------------------------------------------------------------
    # Streaming generators for large exports
    # -------------------------------------------------------------------------
    @staticmethod
    def stream_csv(items_iter: Iterable[dict[str, Any]], fieldnames: list[str], delimiter: str = ",") -> Iterable[bytes]:
        """Yield CSV chunks starting with UTF-8 BOM."""
        # Yield UTF-8 BOM first
        yield b"\xef\xbb\xbf"

        out = io.StringIO()
        writer = csv.DictWriter(
            out,
            fieldnames=fieldnames,
            delimiter=delimiter,
            quoting=csv.QUOTE_ALL,
            extrasaction="ignore"
        )
        writer.writeheader()
        yield out.getvalue().encode("utf-8")
        out.seek(0)
        out.truncate(0)

        for it in items_iter:
            row = {k: _clean_cell_value(it.get(k)) for k in fieldnames}
            writer.writerow(row)
            yield out.getvalue().encode("utf-8")
            out.seek(0)
            out.truncate(0)

    @staticmethod
    def stream_jsonl(items_iter: Iterable[dict[str, Any]]) -> Iterable[bytes]:
        """Yield newline-delimited JSON chunks."""
        for it in items_iter:
            line = json.dumps(it, ensure_ascii=False) + "\n"
            yield line.encode("utf-8")