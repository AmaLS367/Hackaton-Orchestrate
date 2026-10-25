"""Lossless CSV boundaries with exact headers and contextual validation errors."""

import csv
from pathlib import Path
from typing import TypeVar

from ghost_audit.domain.models import StrictModel

T = TypeVar("T", bound=StrictModel)


def read_csv(path: Path, columns: list[str]) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames != columns:
            raise ValueError(f"{path.name}: expected columns {columns}, got {reader.fieldnames}")
        rows = []
        for number, row in enumerate(reader, 2):
            if None in row or any(value is None for value in row.values()):
                raise ValueError(f"{path.name}: malformed CSV row {number}")
            rows.append(row)
        return rows


def load_models[T: StrictModel](path: Path, model: type[T], unique_key: str) -> list[T]:
    result = []
    seen = set()
    for number, row in enumerate(read_csv(path, list(model.model_fields)), 2):
        try:
            item = model.model_validate(row)
        except ValueError as exc:
            raise ValueError(f"{path.name}: invalid row {number}") from exc
        key = getattr(item, unique_key)
        if key in seen:
            raise ValueError(f"{path.name}: duplicate {unique_key} at row {number}")
        seen.add(key)
        result.append(item)
    return result
