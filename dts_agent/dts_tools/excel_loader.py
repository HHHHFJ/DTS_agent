from __future__ import annotations

import csv
import re
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

from dts_agent.dts_tools.pr_parser import parse_pr_url_list
from dts_agent.models import DtsTicket


REQUIRED_HEADERS = (
    "序号",
    "问题单号",
    "简要描述",
    "严重程度",
    "创建时间",
    "提出方",
    "修改文件清单",
)

NS_MAIN = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
NS_REL = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
CELL_REF_RE = re.compile(r"([A-Z]+)")


class ExcelLoadError(ValueError):
    pass


def load_dts_excel(path: str | Path) -> list[DtsTicket]:
    source = Path(path)
    if not source.exists():
        raise ExcelLoadError(f"Excel file does not exist: {source}")

    suffix = source.suffix.lower()
    if suffix == ".csv":
        rows = _load_csv(source)
    elif suffix == ".xlsx":
        rows = _load_xlsx(source)
    else:
        raise ExcelLoadError(f"Unsupported input format: {suffix}. Use .xlsx or .csv.")

    if not rows:
        return []

    header = [str(value).strip() for value in rows[0]]
    missing = [name for name in REQUIRED_HEADERS if name not in header]
    if missing:
        raise ExcelLoadError(f"Missing required headers: {', '.join(missing)}")

    index = {name: header.index(name) for name in REQUIRED_HEADERS}
    tickets: list[DtsTicket] = []
    for row in rows[1:]:
        values = {name: _cell(row, index[name]) for name in REQUIRED_HEADERS}
        ticket_id = values["问题单号"].strip()
        if not ticket_id:
            continue
        pr_urls = tuple(parse_pr_url_list(values["修改文件清单"]))
        tickets.append(
            DtsTicket(
                serial_no=values["序号"],
                ticket_id=ticket_id,
                summary=values["简要描述"],
                severity=values["严重程度"],
                created_at=values["创建时间"],
                reporter=values["提出方"],
                raw=values,
                pr_urls=pr_urls,
            )
        )
    return tickets


def _cell(row: list[str], index: int) -> str:
    if index >= len(row):
        return ""
    return str(row[index] or "").strip()


def _load_csv(path: Path) -> list[list[str]]:
    for encoding in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            with path.open("r", encoding=encoding, newline="") as handle:
                return [list(row) for row in csv.reader(handle)]
        except UnicodeDecodeError:
            continue
    raise ExcelLoadError(f"Cannot decode CSV file: {path}")


def _load_xlsx(path: Path) -> list[list[str]]:
    with zipfile.ZipFile(path) as archive:
        shared_strings = _read_shared_strings(archive)
        sheet_path = _first_sheet_path(archive)
        xml = archive.read(sheet_path)

    root = ET.fromstring(xml)
    rows: list[list[str]] = []
    for row_el in root.iter(f"{NS_MAIN}row"):
        row_values: list[str] = []
        for cell_el in row_el.findall(f"{NS_MAIN}c"):
            ref = cell_el.attrib.get("r", "")
            col_index = _column_index(ref)
            while len(row_values) <= col_index:
                row_values.append("")
            row_values[col_index] = _cell_value(cell_el, shared_strings)
        rows.append(row_values)
    return rows


def _read_shared_strings(archive: zipfile.ZipFile) -> list[str]:
    if "xl/sharedStrings.xml" not in archive.namelist():
        return []
    root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
    values: list[str] = []
    for si in root.findall(f"{NS_MAIN}si"):
        fragments = [node.text or "" for node in si.iter(f"{NS_MAIN}t")]
        values.append("".join(fragments))
    return values


def _first_sheet_path(archive: zipfile.ZipFile) -> str:
    workbook = ET.fromstring(archive.read("xl/workbook.xml"))
    sheet = workbook.find(f".//{NS_MAIN}sheet")
    if sheet is None:
        return "xl/worksheets/sheet1.xml"

    relationship_id = sheet.attrib.get(f"{NS_REL}id")
    if not relationship_id or "xl/_rels/workbook.xml.rels" not in archive.namelist():
        return "xl/worksheets/sheet1.xml"

    rels = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
    for rel in rels:
        if rel.attrib.get("Id") == relationship_id:
            target = rel.attrib.get("Target", "worksheets/sheet1.xml")
            return "xl/" + target.lstrip("/")
    return "xl/worksheets/sheet1.xml"


def _cell_value(cell_el: ET.Element, shared_strings: list[str]) -> str:
    cell_type = cell_el.attrib.get("t")
    if cell_type == "inlineStr":
        return "".join(node.text or "" for node in cell_el.iter(f"{NS_MAIN}t"))

    value_el = cell_el.find(f"{NS_MAIN}v")
    raw_value = value_el.text if value_el is not None else ""
    if cell_type == "s" and raw_value:
        try:
            return shared_strings[int(raw_value)]
        except (ValueError, IndexError):
            return raw_value
    return raw_value or ""


def _column_index(cell_ref: str) -> int:
    match = CELL_REF_RE.match(cell_ref)
    if not match:
        return 0
    value = 0
    for char in match.group(1):
        value = value * 26 + (ord(char) - ord("A") + 1)
    return value - 1
