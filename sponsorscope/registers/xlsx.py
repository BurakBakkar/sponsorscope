from __future__ import annotations

import io
from collections.abc import Iterator

from python_calamine import CalamineWorkbook


def sheet_rows(data: bytes, index: int = 0) -> Iterator[list]:
    """Rows of one sheet. calamine holds the sheet in Rust memory (~2.8 GB for the 250 MB US file)."""
    workbook = CalamineWorkbook.from_filelike(io.BytesIO(data))
    yield from workbook.get_sheet_by_index(index).iter_rows()


def cell_str(value: object) -> str:
    if value is None:
        return ""
    return str(value).replace("\xa0", " ").strip()


def cell_int(value: object) -> int:
    try:
        return int(float(value)) if value not in (None, "") else 0
    except (TypeError, ValueError):
        return 0
