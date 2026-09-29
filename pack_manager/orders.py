"""Import orders from a CSV file (the format of the organisers' sample, or a store export).

Columns: order_id and order_lines are required; channel, unit_id and client_id are optional.
order_lines is "SKU:qty;SKU:qty". Any organisation column in the file is ignored: orders
always belong to the organisation that imports them.
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field

from .models import Catalogue, Order, parse_lines

MAX_ROWS = 2000


@dataclass
class ImportResult:
    orders: list[Order] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)  # rows that were skipped, and why
    unknown_skus: set[str] = field(default_factory=set)  # imported, but not in the catalogue


def parse_orders_csv(text: str, organization_id: str, catalogue: Catalogue) -> ImportResult:
    result = ImportResult()
    reader = csv.DictReader(io.StringIO(text.lstrip("﻿")))
    headers = {h.strip().lower() for h in (reader.fieldnames or [])}
    if not {"order_id", "order_lines"} <= headers:
        result.problems.append("The file needs the columns order_id and order_lines.")
        return result
    known = set(catalogue.skus)
    seen: set[str] = set()
    for n, raw in enumerate(reader, start=2):  # row 1 is the header
        if n - 1 > MAX_ROWS:
            result.problems.append(f"Only the first {MAX_ROWS} orders were read.")
            break
        row = {(k or "").strip().lower(): (v or "").strip() for k, v in raw.items()}
        order_id = row.get("order_id", "")
        if not order_id:
            result.problems.append(f"Row {n}: no order_id.")
            continue
        if order_id in seen:
            result.problems.append(f"Row {n}: {order_id} appears twice; the first one was kept.")
            continue
        try:
            lines = parse_lines(row.get("order_lines", ""))
            if not lines:
                raise ValueError("no lines")
            order = Order(
                order_id=order_id, organization_id=organization_id, lines=lines,
                channel=row.get("channel") or None, unit_id=row.get("unit_id") or None,
                client_id=row.get("client_id") or None,
            )
        except ValueError:
            result.problems.append(f'Row {n}: order_lines must look like "SKU-A:2;SKU-B:1".')
            continue
        seen.add(order_id)
        result.unknown_skus |= {line.sku for line in lines if line.sku not in known}
        result.orders.append(order)
    return result
