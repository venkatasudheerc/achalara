"""Readers for the files index membership comes from.

Each reader turns a file, exactly as downloaded, into rows in one shape:
``Holding(symbol, name, kind, sector, exchange, weight)``. Lines that are not
securities (cash, money-market sweeps, futures, collateral) are dropped here,
and so are lines with no ticker. Symbols are written in the app's spelling:
share classes with a dot (``BRK.B``), upper case.
"""
import csv
import io
import re
import zipfile
from dataclasses import dataclass
from datetime import date, datetime
from typing import List, Optional, Tuple
import xml.etree.ElementTree as ET


@dataclass(frozen=True)
class Holding:
    symbol: str
    name: str
    kind: str  # stock | other (warrants, rights and the like)
    sector: Optional[str]  # as the file names it, e.g. "Information Technology"
    exchange: Optional[str]
    weight: Optional[float]  # percent of the fund


# A plain listed share, optionally with a class letter: AAPL, BRK.B, MOG.A.
_SHARE = re.compile(r"^[A-Z]{1,5}(\.[A-Z])?$")


def app_symbol(raw: str) -> str:
    """The app's spelling of a ticker: ``BRK B`` / ``BRK/B`` / ``BRK-B`` -> ``BRK.B``."""
    symbol = (raw or "").strip().upper()
    return re.sub(r"[ /-]", ".", symbol)


def _number(text) -> Optional[float]:
    text = str(text or "").replace(",", "").strip()
    try:
        return float(text)
    except ValueError:
        return None


def _date(text: str, formats: Tuple[str, ...]) -> date:
    text = (text or "").strip().strip('"')
    for fmt in formats:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"Unrecognised date {text!r}")


def read_ishares_csv(content: bytes) -> Tuple[date, List[Holding]]:
    """An iShares ``latest-holdings.csv``: a few lines of fund details, then a table."""
    text = content.decode("utf-8-sig", "replace")
    lines = text.splitlines()
    as_of = None
    for line in lines[:12]:
        if line.startswith("Fund Holdings as of"):
            as_of = _date(line.split(",", 1)[1], ("%b %d, %Y",))
    if as_of is None:
        raise ValueError("Not an iShares holdings file: no 'Fund Holdings as of' line")
    start = next(
        (i for i, line in enumerate(lines) if line.startswith("Ticker,")), None
    )
    if start is None:
        raise ValueError("Not an iShares holdings file: no table header")
    holdings: List[Holding] = []
    for row in csv.DictReader(io.StringIO("\n".join(lines[start:]))):
        if (row.get("Asset Class") or "").strip() != "Equity":
            continue  # cash, money market, futures, collateral
        symbol = app_symbol(row.get("Ticker") or "")
        if not symbol or symbol == "-" or not re.search(r"[A-Z]", symbol):
            continue
        holdings.append(
            Holding(
                symbol=symbol,
                name=(row.get("Name") or "").strip(),
                kind="stock" if _SHARE.match(symbol) else "other",
                sector=(row.get("Sector") or "").strip() or None,
                exchange=(row.get("Exchange") or "").strip() or None,
                weight=_number(row.get("Weight (%)")),
            )
        )
    return as_of, holdings


_NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"


def _xlsx_rows(content: bytes) -> List[List[str]]:
    """The first sheet of a workbook as rows of text (no spreadsheet library needed)."""
    book = zipfile.ZipFile(io.BytesIO(content))
    shared: List[str] = []
    if "xl/sharedStrings.xml" in book.namelist():
        root = ET.fromstring(book.read("xl/sharedStrings.xml"))
        shared = [
            "".join(t.text or "" for t in si.iter(_NS + "t"))
            for si in root.findall(_NS + "si")
        ]
    sheet = sorted(n for n in book.namelist() if n.startswith("xl/worksheets/sheet"))[0]
    rows: List[List[str]] = []
    for row in ET.fromstring(book.read(sheet)).iter(_NS + "row"):
        values = []
        for cell in row.findall(_NS + "c"):
            kind, value = cell.get("t"), cell.find(_NS + "v")
            if kind == "s" and value is not None:
                values.append(shared[int(value.text)])
            elif kind == "inlineStr":
                values.append("".join(t.text or "" for t in cell.iter(_NS + "t")))
            else:
                values.append(value.text if value is not None and value.text else "")
        rows.append(values)
    return rows


def read_ssga_xlsx(content: bytes) -> Tuple[date, List[Holding]]:
    """A State Street daily holdings workbook: a few header lines, then a table."""
    rows = _xlsx_rows(content)
    as_of = None
    for row in rows[:8]:
        if row and row[0].strip().startswith("Holdings:"):
            as_of = _date(row[1].replace("As of", "").strip(), ("%d-%b-%Y",))
    if as_of is None:
        raise ValueError("Not a State Street holdings file: no 'Holdings: As of' line")
    header = next(
        (i for i, row in enumerate(rows) if row[:2] == ["Name", "Ticker"]), None
    )
    if header is None:
        raise ValueError("Not a State Street holdings file: no table header")
    columns = rows[header]
    holdings: List[Holding] = []
    for row in rows[header + 1 :]:
        cells = dict(zip(columns, row + [""] * (len(columns) - len(row))))
        name, raw = (cells.get("Name") or "").strip(), (
            cells.get("Ticker") or ""
        ).strip()
        if not name or not raw or raw == "-":
            continue  # blank lines, notes, cash
        symbol = app_symbol(raw)
        if not _SHARE.match(symbol) or not (cells.get("Identifier") or "").strip():
            continue  # cash lines, rights and other leftovers
        sector = (cells.get("Sector") or "").strip()
        holdings.append(
            Holding(
                symbol=symbol,
                name=name,
                kind="stock",
                sector=None if sector in ("", "-") else sector,
                exchange=None,
                weight=_number(cells.get("Weight")),
            )
        )
    return as_of, holdings
