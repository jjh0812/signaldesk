"""Tiny local structural diagnostics, NOT a dump of any API request/response.

Contains only fixed enums, counts, schema field names and timestamps. It cannot
recover the old v0.5.0 failures (those response bodies were never saved).
No key, prompt, model output text, source URL, ticker or response ID is stored.
"""
from __future__ import annotations

import json
import os
import stat
import tempfile
from datetime import datetime, timezone
from pathlib import Path

PARSER_VERSION = "0.5.2"
CODES = frozenset({"OUTLOOK_RESPONSE_SHAPE", "OUTLOOK_NO_FINAL", "OUTLOOK_AMBIGUOUS_FINAL",
    "OUTLOOK_RESPONSE_SIZE", "OUTLOOK_JSON", "OUTLOOK_SCHEMA", "OUTLOOK_SYMBOL",
    "OUTLOOK_SOURCE_IDS", "OUTLOOK_IDENTITY", "OUTLOOK_NO_SEARCH", "OUTLOOK_SCOPE",
    "OUTLOOK_FORMAT", "AI_REFUSAL", "AI_INCOMPLETE"})
FIELDS = frozenset("schema_version symbol identity name security_type source_ids sources id url title role document_type published_date fiscal_period coverage area status note unresolved catalysts category timing event_date window_start window_end window_label date_basis date_source_ids fact why_it_matters positive_condition negative_condition watch importance importance_reason risks mechanism trigger monitor mitigating_factor state amount_basis amount_caution".split())
TYPES = frozenset({"missing", "extra_forbidden", "string_type", "string_too_long", "string_too_short",
                 "literal_error", "list_type", "too_long", "too_short", "model_type", "dict_type",
                 "string_unicode", "none_required", "validation_error"})
COUNTS = ("assistant_messages", "commentary_messages", "final_text_parts", "final_chars", "ignored_messages", "json_line", "json_column", "normalized_source_ids", "source_reference_rewrites")


def safe_diagnostic(raw, exc, scope: str) -> dict:
    raw = raw if isinstance(raw, dict) else {}
    output = raw.get("output")
    output = output if isinstance(output, list) else []
    messages = [x for x in output if isinstance(x, dict) and x.get("type") == "message" and x.get("role") == "assistant"]
    status = raw.get("status")
    d = {"parser_version": PARSER_VERSION, "scope": scope if scope in {"catalysts", "risks"} else "unknown",
         "code": exc.code if getattr(exc, "code", None) in CODES else "OUTLOOK_PARSE_ERROR",
         "response_status": status if isinstance(status, str) and status in {"completed", "incomplete", "failed", "cancelled", "queued", "in_progress"} else "unknown",
         "output_items": len(output), "assistant_messages": len(messages),
         "commentary_messages": sum(x.get("phase") == "commentary" for x in messages),
         "final_answer_messages": sum(x.get("phase") == "final_answer" for x in messages),
         "generated_at": datetime.now(timezone.utc).isoformat()}
    extras = getattr(exc, "outlook_diagnostics", {})
    if isinstance(extras, dict):
        for key in COUNTS:
            v = extras.get(key)
            if type(v) is int and 0 <= v <= 100_000_000:
                d[key] = v
        reason = extras.get("incomplete_reason")
        if isinstance(reason, str) and reason in {"max_output_tokens", "content_filter", "unknown"}:
            d["incomplete_reason"] = reason
        issues = extras.get("issues")
        if isinstance(issues, list):
            safe = []
            for issue in issues[:8]:
                if not isinstance(issue, dict):continue
                path = issue.get("path")
                if not isinstance(path, str):continue
                parts = path.split(".")[:8]
                clean = [p if p in FIELDS or p in {"?", "$"} or (p.isascii() and p.isdigit() and len(p) < 6) else "?" for p in parts]
                kind = issue.get("type")
                safe.append({"path": ".".join(clean), "type": kind if isinstance(kind, str) and kind in TYPES else "validation_error"})
            d["issues"] = safe
    return d


def _not_link(path: Path) -> None:
    if os.path.lexists(path):
        info = path.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise OSError("Diagnostic symlink/junction destination refused")


def record_failure(root: Path, raw, exc, scope: str) -> dict:
    d = safe_diagnostic(raw, exc, scope)
    d["saved_locally"] = False
    temp = None
    try:
        folder = root / "logs"
        target = folder / "outlook-last-diagnostic.json"
        for path in (root, folder, target):_not_link(path)
        folder.mkdir(parents=True, exist_ok=True)
        fd, name = tempfile.mkstemp(prefix="outlook-diagnostic-", suffix=".tmp", dir=folder)
        temp = Path(name)
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump({**d, "saved_locally": True}, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.write("\n")
        os.replace(temp, target)
        d["saved_locally"] = True
    except OSError:
        pass  # Diagnostics must not mask the actual model/validation error.
    finally:
        if temp is not None:
            try:temp.unlink(missing_ok=True)
            except OSError:pass
    print("[SIGNALDESK OUTLOOK DIAGNOSTIC] " + json.dumps(d, ensure_ascii=True, allow_nan=False), flush=True)
    return d
