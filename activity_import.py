from __future__ import annotations

import csv
import io
from collections import Counter, defaultdict
from datetime import datetime
from typing import Any


def build_import_preview(csv_text: str, preview_limit: int = 100) -> dict[str, Any]:
    headers, rows = _read_csv(csv_text)
    mapping = _detect_mapping(headers, rows)
    activities = [_row_to_activity(mapping, row) for row in rows]
    importable = [activity for activity in activities if activity["id"] and activity["date"]]

    dates = sorted(activity["date"] for activity in importable if activity["date"])
    type_counts = Counter(activity["type"] or "Unknown" for activity in importable)
    year_distance = defaultdict(float)
    total_distance_km = 0.0
    total_moving_seconds = 0.0

    for activity in importable:
        total_distance_km += activity["distance_km"] or 0
        total_moving_seconds += activity["moving_time_seconds"] or 0
        if activity["date"]:
            year_distance[str(activity["date"].year)] += activity["distance_km"] or 0

    sorted_preview = sorted(
        importable,
        key=lambda activity: activity["date"] or datetime.min,
        reverse=True,
    )[:preview_limit]

    return {
        "summary": {
            "rows_received": len(rows),
            "rows_importable": len(importable),
            "columns": len(headers),
            "date_start": dates[0].date().isoformat() if dates else None,
            "date_end": dates[-1].date().isoformat() if dates else None,
            "total_distance_km": round(total_distance_km, 1),
            "total_moving_hours": round(total_moving_seconds / 3600, 1),
            "activity_types": len(type_counts),
        },
        "mapping": {
            key: headers[index] if index >= 0 else None
            for key, index in mapping.items()
        },
        "quality": _build_quality(importable, mapping),
        "type_counts": dict(type_counts.most_common(12)),
        "year_distance_km": {
            year: round(distance, 1)
            for year, distance in sorted(year_distance.items())
        },
        "preview": [_serialize_activity(activity) for activity in sorted_preview],
    }


def _read_csv(csv_text: str) -> tuple[list[str], list[list[str]]]:
    if not csv_text.strip():
        raise ValueError("CSV is empty.")

    reader = csv.reader(io.StringIO(csv_text))
    try:
        raw_headers = next(reader)
    except StopIteration as exc:
        raise ValueError("CSV is empty.") from exc

    headers = _make_unique_headers(raw_headers)
    rows = [row for row in reader if any(cell.strip() for cell in row)]
    if not rows:
        raise ValueError("CSV has headers but no activity rows.")

    return headers, rows


def _make_unique_headers(headers: list[str]) -> list[str]:
    seen: dict[str, int] = {}
    unique_headers: list[str] = []
    for raw_header in headers:
        header = raw_header.strip() or "Column"
        count = seen.get(header, 0)
        seen[header] = count + 1
        unique_headers.append(f"{header} #{count + 1}" if count else header)
    return unique_headers


def _base_header(header: str) -> str:
    if " #" not in header:
        return header
    name, suffix = header.rsplit(" #", 1)
    return name if suffix.isdigit() else header


def _detect_mapping(headers: list[str], rows: list[list[str]]) -> dict[str, int]:
    def find(name: str) -> int:
        for index, header in enumerate(headers):
            if _base_header(header) == name:
                return index
        return -1

    def find_all(name: str) -> list[int]:
        return [
            index
            for index, header in enumerate(headers)
            if _base_header(header) == name
        ]

    return {
        "id": find("Activity ID"),
        "date": find("Activity Date"),
        "name": find("Activity Name"),
        "type": find("Activity Type"),
        "distance": _choose_distance_column(find_all("Distance"), rows),
        "moving_time": find("Moving Time"),
        "average_heart_rate": find("Average Heart Rate"),
        "elevation_gain": find("Elevation Gain"),
    }


def _choose_distance_column(indices: list[int], rows: list[list[str]]) -> int:
    if not indices:
        return -1

    scored: list[tuple[float, int]] = []
    for index in indices:
        values = sorted(
            value
            for row in rows[:200]
            if (value := _number(_cell(row, index))) is not None
        )
        median = values[len(values) // 2] if values else 0
        scored.append((median, index))

    scored.sort(reverse=True)
    return scored[0][1]


def _row_to_activity(mapping: dict[str, int], row: list[str]) -> dict[str, Any]:
    def get(key: str) -> str:
        return _cell(row, mapping.get(key, -1)).strip()

    distance = _number(get("distance"))
    moving_time = _number(get("moving_time"))
    elevation_gain = _number(get("elevation_gain"))
    average_heart_rate = _number(get("average_heart_rate"))
    parsed_date = _parse_strava_date(get("date"))

    return {
        "id": get("id"),
        "date": parsed_date,
        "date_raw": get("date"),
        "name": get("name") or "Untitled activity",
        "type": get("type") or "Unknown",
        "distance_km": _normalize_distance_km(distance),
        "moving_time_seconds": moving_time,
        "average_heart_rate": average_heart_rate,
        "elevation_gain": elevation_gain,
    }


def _build_quality(
    activities: list[dict[str, Any]],
    mapping: dict[str, int],
) -> list[dict[str, Any]]:
    total = len(activities) or 1
    checks = [
        ("Activity ID", "id", "id"),
        ("Activity Date", "date", "date"),
        ("Activity Name", "name", "name"),
        ("Activity Type", "type", "type"),
        ("Distance", "distance", "distance_km"),
        ("Moving Time", "moving_time", "moving_time_seconds"),
    ]
    quality = []
    for label, mapping_key, activity_key in checks:
        present = mapping.get(mapping_key, -1) >= 0
        filled = sum(1 for activity in activities if activity.get(activity_key))
        ratio = filled / total if present else 0
        quality.append(
            {
                "field": label,
                "present": present,
                "filled": filled,
                "ratio": round(ratio, 3),
                "status": "ok" if present and ratio >= 0.95 else "warn" if present else "missing",
            }
        )
    return quality


def _serialize_activity(activity: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": activity["id"],
        "date": activity["date"].date().isoformat() if activity["date"] else activity["date_raw"],
        "name": activity["name"],
        "type": activity["type"],
        "distance_km": round(activity["distance_km"], 2) if activity["distance_km"] is not None else None,
        "moving_time_minutes": round(activity["moving_time_seconds"] / 60) if activity["moving_time_seconds"] is not None else None,
        "average_heart_rate": round(activity["average_heart_rate"]) if activity["average_heart_rate"] is not None else None,
        "elevation_gain": round(activity["elevation_gain"]) if activity["elevation_gain"] is not None else None,
    }


def _cell(row: list[str], index: int) -> str:
    if index < 0 or index >= len(row):
        return ""
    return row[index]


def _number(value: str | None) -> float | None:
    if value is None or not str(value).strip():
        return None
    try:
        return float(str(value).replace(",", "").strip())
    except ValueError:
        return None


def _normalize_distance_km(value: float | None) -> float | None:
    if value is None:
        return None
    return value / 1000 if value > 1000 else value


def _parse_strava_date(value: str) -> datetime | None:
    if not value:
        return None
    formats = (
        "%b %d, %Y, %I:%M:%S %p",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S",
    )
    for date_format in formats:
        try:
            return datetime.strptime(value, date_format)
        except ValueError:
            pass
    return None
