"""
Bus seat layout (3 + 2 coach with aisle):
- Seat 1 is the driver (front-left, not sold).
- Front row: driver (left block) | aisle | seats 2, 3 (right).
- Every row after: 3 seats left | aisle | 2 seats right (4–8, 9–13, … up to 70).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

DRIVER_SEAT_NUMBER = 1
SEATS_PER_ROW = 5  # 3 left + 2 right
LAYOUT_VERSION = 5
LEFT_BLOCK_COLSPAN = 3

LEFT_COLUMNS = ("L1", "L2", "L3")  # window -> aisle
RIGHT_COLUMNS = ("R2", "R1")  # window -> aisle
ROW_COLUMN_ORDER = LEFT_COLUMNS + RIGHT_COLUMNS

COL_DRIVER = 0
COL_L1 = 1
COL_L2 = 2
COL_L3 = 3
COL_R2 = 4
COL_R1 = 5

COLUMN_LABELS = {
    "L1": "Window (left)",
    "L2": "Middle (left)",
    "L3": "Aisle (left)",
    "R1": "Aisle (right)",
    "R2": "Window (right)",
}

COLUMN_SHORT = {
    "L1": "Window",
    "L2": "Middle",
    "L3": "Aisle",
    "R1": "Aisle",
    "R2": "Window",
}


@dataclass(frozen=True)
class SeatPosition:
    row: int
    column_key: str
    seat_number: int | None


def is_driver_seat(seat_number) -> bool:
    try:
        return int(seat_number) == DRIVER_SEAT_NUMBER
    except (TypeError, ValueError):
        return False


def max_seat_number(capacity: int) -> int:
    cap = max(1, int(capacity or 70))
    return min(cap, 70)


def passenger_row_count(capacity: int) -> int:
    """Rows after the front row that use the 3+2 pattern."""
    cap = max(0, int(capacity or 0))
    if cap <= 3:
        return 0
    remaining = cap - 3
    return (remaining + SEATS_PER_ROW - 1) // SEATS_PER_ROW


def _passenger_row_start_number(passenger_row: int) -> int:
    """First seat number in a 3+2 passenger row (row 1 -> seat 4)."""
    return 4 + (passenger_row - 1) * SEATS_PER_ROW


def seat_number_for_position(passenger_row: int, column_key: str) -> int | None:
    if passenger_row < 1:
        return None
    if column_key not in ROW_COLUMN_ORDER:
        return None
    return _passenger_row_start_number(passenger_row) + ROW_COLUMN_ORDER.index(column_key)


def position_for_seat_number(seat_number: int) -> SeatPosition | None:
    try:
        n = int(seat_number)
    except (TypeError, ValueError):
        return None
    if n == DRIVER_SEAT_NUMBER:
        return SeatPosition(row=0, column_key="DRV", seat_number=n)
    if n == 2:
        return SeatPosition(row=0, column_key="R2", seat_number=n)
    if n == 3:
        return SeatPosition(row=0, column_key="R1", seat_number=n)
    if n < 4:
        return None

    offset = n - 4
    passenger_row = offset // SEATS_PER_ROW + 1
    col_key = ROW_COLUMN_ORDER[offset % SEATS_PER_ROW]
    return SeatPosition(row=passenger_row, column_key=col_key, seat_number=n)


def build_layout_grid(capacity: int) -> list[dict[str, Any]]:
    cap = max(1, min(70, int(capacity or 70)))
    rows: list[dict[str, Any]] = []

    # Front row: driver (left block), aisle, seats 2–3 on the right
    rows.append(
        {
            "row_index": 0,
            "label": "",
            "cells": [
                {
                    "type": "seat",
                    "seat_number": DRIVER_SEAT_NUMBER,
                    "column_key": "DRV",
                    "label": "",
                    "is_window": False,
                    "is_driver": True,
                    "colspan": LEFT_BLOCK_COLSPAN,
                },
                {"type": "aisle", "label": ""},
                (
                    {
                        "type": "seat",
                        "seat_number": 2,
                        "column_key": "R2",
                        "label": "",
                        "is_window": True,
                        "is_driver": False,
                    }
                    if cap >= 2
                    else {"type": "empty", "label": ""}
                ),
                (
                    {
                        "type": "seat",
                        "seat_number": 3,
                        "column_key": "R1",
                        "label": "",
                        "is_window": False,
                        "is_driver": False,
                    }
                    if cap >= 3
                    else {"type": "empty", "label": ""}
                ),
            ],
        }
    )

    for pr in range(1, passenger_row_count(cap) + 1):
        cells: list[dict[str, Any]] = []

        def _seat_cell(col_key: str) -> dict[str, Any]:
            sn = seat_number_for_position(pr, col_key)
            if sn is None or sn > cap:
                return {"type": "empty", "label": ""}
            return {
                "type": "seat",
                "seat_number": sn,
                "column_key": col_key,
                "label": "",
                "is_window": col_key in ("L1", "R2"),
                "is_driver": False,
            }

        cells.append(_seat_cell("L1"))
        cells.append(_seat_cell("L2"))
        cells.append(_seat_cell("L3"))
        cells.append({"type": "aisle", "label": ""})
        cells.append(_seat_cell("R2"))
        cells.append(_seat_cell("R1"))

        rows.append({"row_index": pr, "label": "", "cells": cells})

    return rows


def iter_seat_numbers(capacity: int) -> list[int]:
    cap = max(1, min(70, int(capacity or 70)))
    return list(range(1, cap + 1))


def layout_metadata() -> dict[str, Any]:
    return {
        "type": "3-plus-2",
        "version": LAYOUT_VERSION,
        "description": (
            "Driver seat 1 on the left; aisle; front-right seats 2–3; "
            "each row has 3 seats left and 2 seats right of the aisle."
        ),
        "columns": [
            {"key": "L1", "side": "left", "window": True, "label": COLUMN_LABELS["L1"]},
            {"key": "L2", "side": "left", "window": False, "label": COLUMN_LABELS["L2"]},
            {"key": "L3", "side": "left", "window": False, "label": COLUMN_LABELS["L3"]},
            {"key": "R1", "side": "right", "window": False, "label": COLUMN_LABELS["R1"]},
            {"key": "R2", "side": "right", "window": True, "label": COLUMN_LABELS["R2"]},
        ],
        "driver_seat": DRIVER_SEAT_NUMBER,
        "max_seat_number": 70,
        "left_seats_per_row": 3,
        "right_seats_per_row": 2,
    }


def seat_from_bus_record(seat_row: int, seat_column: int, capacity: int) -> int | None:
    """Map legacy Seat row/column to seat number."""
    cap = max(1, min(70, int(capacity or 70)))

    if seat_row == 0 or (seat_row == 1 and seat_column == COL_DRIVER):
        return DRIVER_SEAT_NUMBER if cap >= 1 else None
    if seat_row == 0 and seat_column == COL_R2:
        return 2 if cap >= 2 else None
    if seat_row == 0 and seat_column == COL_R1:
        return 3 if cap >= 3 else None

    col_map = {
        COL_L1: "L1",
        COL_L2: "L2",
        COL_L3: "L3",
        COL_R2: "R2",
        COL_R1: "R1",
    }
    if seat_row >= 1 and seat_column in col_map:
        sn = seat_number_for_position(seat_row, col_map[seat_column])
        if sn is not None and sn <= cap:
            return sn
    return None
