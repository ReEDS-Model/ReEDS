#!/usr/bin/env python3
"""Shared helpers for municipality-to-region PR100 staging inputs."""

from __future__ import annotations

import csv
import re
import unicodedata
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as stream:
        return list(csv.DictReader(stream))


def write_csv(path: Path, rows: Iterable[dict[str, Any]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def normalize_name(value: str) -> str:
    """Normalize municipality/project labels for deterministic joins."""
    decomposed = unicodedata.normalize("NFKD", str(value))
    ascii_text = "".join(char for char in decomposed if not unicodedata.combining(char))
    return " ".join(re.sub(r"[^a-z0-9]+", " ", ascii_text.lower()).split())


def is_true(value: Any) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes"}


def municipality_region_weights(
    bus_to_region_path: Path,
    assets_path: Path,
) -> tuple[dict[str, list[tuple[str, float]]], list[dict[str, Any]]]:
    """Build fixed municipality-to-region allocation weights from base loads.

    Active StandardLoad nameplate capacity is the primary weight. If a
    municipality has no active load component, mapped bus counts provide a
    deterministic fallback.
    """
    bus_rows = read_csv(bus_to_region_path)
    bus_lookup = {
        int(row["bus_number"]): row
        for row in bus_rows
        if row.get("region") and is_true(row.get("mapped", False))
    }
    municipality_labels: dict[str, str] = {}
    bus_counts: dict[tuple[str, str], int] = defaultdict(int)
    for row in bus_lookup.values():
        key = normalize_name(row.get("municipality", ""))
        if not key:
            continue
        municipality_labels.setdefault(key, row["municipality"])
        bus_counts[(key, row["region"])] += 1

    load_capacity: dict[tuple[str, str], float] = defaultdict(float)
    for asset in read_csv(assets_path):
        if asset.get("asset_type") != "StandardLoad" or not is_true(asset.get("available")):
            continue
        bus = bus_lookup.get(int(asset["bus_number"]))
        if bus is None:
            continue
        key = normalize_name(bus.get("municipality", ""))
        if key:
            load_capacity[(key, bus["region"])] += float(asset.get("capacity_mw") or 0.0)

    weights: dict[str, list[tuple[str, float]]] = {}
    audit_rows: list[dict[str, Any]] = []
    for municipality in sorted(municipality_labels):
        regions = sorted(
            {region for key, region in bus_counts if key == municipality}
            | {region for key, region in load_capacity if key == municipality}
        )
        raw = {region: load_capacity[(municipality, region)] for region in regions}
        method = "active_standard_load_capacity"
        if sum(raw.values()) <= 0:
            raw = {region: float(bus_counts[(municipality, region)]) for region in regions}
            method = "mapped_bus_count_fallback"
        total = sum(raw.values())
        if total <= 0:
            raise ValueError(f"No region allocation basis for municipality {municipality!r}")
        weights[municipality] = [(region, raw[region] / total) for region in regions]
        for region, weight in weights[municipality]:
            audit_rows.append(
                {
                    "municipality": municipality_labels[municipality],
                    "municipality_key": municipality,
                    "region": region,
                    "weight": weight,
                    "weight_method": method,
                    "active_load_capacity_mw": load_capacity[(municipality, region)],
                    "mapped_bus_count": bus_counts[(municipality, region)],
                }
            )
    return weights, audit_rows
