from __future__ import annotations

import html
import struct
import threading
import time
import zipfile
from dataclasses import dataclass, field
from io import BytesIO
from xml.etree import ElementTree

from flask import Flask, Response, jsonify, render_template, request
from serial.tools import list_ports

from can_tuner3 import (
    CAN_BITRATE,
    CAN_ID_READ_RESP,
    PARAM_NAMES,
    READ_COMMAND,
    SERIAL_BAUDRATE,
    WRITE_COMMAND,
    ZERO_ANGLE_ROW,
    read_matching_response,
    read_zero_angle_frame,
    send_read_request,
    send_write_complete_request,
    send_write_request,
)
from waveshare_can import CAN_BITRATE_CODES, WaveshareCANA


app = Flask(__name__)
XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
AUTO_DETECT_FRAME = [0x03, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00]
PIC_ID_CAN_REQ = 0xE0
PIC_ID_CAN_RESP = 0xE1
PIC_ID_1_REQUEST_PAYLOAD = [0x04, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00]
PIC_ID_2_REQUEST_PAYLOAD = [0x05, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00]
SYSTEM_ID_CAN_REQ = 0xE0
SYSTEM_ID_CAN_RESP = 0xE1
PROJECT_ID_SLOT = 0x01
FIRMWARE_ID_SLOT = 0x02
PARAM_ROW_COUNT = 15
PARAM_EDITABLE_ROW_COUNT = 12
PARAM_COL_COUNT = 4
PARAM_TOTAL = PARAM_ROW_COUNT * PARAM_COL_COUNT
AUTO_DETECT_BITRATES = [
    CAN_BITRATE,
    250_000,
    125_000,
    1_000_000,
    800_000,
    400_000,
    200_000,
    100_000,
    50_000,
    20_000,
    10_000,
    5_000,
]


DISPLAY_NAMES = {
    (1, 1): "ESC_ID",
    (1, 2): "Peak current (Arms)",
    (1, 3): "Max rpm",
    (1, 4): "No. of poles",
    (2, 1): "Phase resistance (m ohm)",
    (2, 2): "D-Inductance (mH)",
    (2, 3): "Q-inductance (mH)",
    (2, 4): "Flux (mWb)",
    (3, 1): "Zero angle (degree)",
    (3, 2): "Sensor reversal",
    (3, 3): "Zero angle estimate",
    (3, 4): "Sensor reversal estimate",
    (4, 1): "Rotation direction",
    (4, 2): "NA",
    (4, 3): "kmph/rpm",
    (4, 4): "rpm fault",
    (5, 1): "Motor derate (C)",
    (5, 2): "Motor T fault (C)",
    (5, 3): "ESC derate (C)",
    (5, 4): "ESC T fault (C)",
    (6, 1): "Battery max Voltage (V)",
    (6, 2): "Ibat default (A)",
    (6, 3): "Over voltage fault (V)",
    (6, 4): "Under voltage fault (V)",
    (7, 1): "Max battery current (A)",
    (7, 2): "Max regen current (A)",
    (7, 3): "Phase Ifault (Arms)",
    (7, 4): "battery Ifault (A)",
    (8, 1): "Driving mode",
    (8, 2): "Reverse rpm (%)",
    (8, 3): "L mode rpm (%)",
    (8, 4): "M mode rpm(%)",
    (9, 1): "Throttle Zero (V)",
    (9, 2): "Throttle max (V)",
    (9, 3): "Brake limit Voltage (V)",
    (9, 4): "auto brake (%)",
    (10, 1): "rpm kp",
    (10, 2): "rpm ki",
    (10, 3): "L mode Acceleration (%)",
    (10, 4): "M mode Acceleration (%)",
    (11, 1): "L mode battery current (%)",
    (11, 2): "M mode battery current (%)",
    (11, 3): "L mode phase current (%)",
    (11, 4): "M mode phase current (%)",
    (12, 1): "Braking current(A)",
    (12, 2): "Braking time(Sec)",
    (12, 3): "Generation voltage margin(V)",
    (12, 4): "NA",
    (13, 1): "Max IPhase(A)",
    (13, 2): "Max frequency(Hz)",
    (13, 3): "Max motor temp(degC)",
    (13, 4): "Max ESC temperature(degC)",
    (14, 1): "Max voltage(V)",
    (14, 2): "Min voltage(V)",
    (14, 3): "Max battery current(A)",
    (14, 4): "NA",
    (15, 1): "Min kp",
    (15, 2): "Max kp",
    (15, 3): "Min Ki",
    (15, 4): "Max Ki",
}


def key_for(row: int, col: int) -> str:
    return f"{row}-{col}"


def build_parameters() -> list[dict]:
    parameters = []
    for row in range(1, PARAM_ROW_COUNT + 1):
        for col in range(1, PARAM_COL_COUNT + 1):
            parameters.append(
                {
                    "row": row,
                    "col": col,
                    "key": key_for(row, col),
                    "name": DISPLAY_NAMES.get((row, col), PARAM_NAMES.get((row, col), "Unknown")),
                    "writable": row <= PARAM_EDITABLE_ROW_COUNT,
                }
            )
    return parameters


def cell_ref(col_index: int, row_index: int) -> str:
    letters = ""
    while col_index:
        col_index, remainder = divmod(col_index - 1, 26)
        letters = chr(65 + remainder) + letters
    return f"{letters}{row_index}"


def xlsx_cell(value, col_index: int, row_index: int) -> str:
    ref = cell_ref(col_index, row_index)
    if value is None or value == "":
        return f'<c r="{ref}"/>'
    if isinstance(value, (int, float)):
        return f'<c r="{ref}"><v>{value}</v></c>'
    escaped = html.escape(str(value), quote=True)
    return f'<c r="{ref}" t="inlineStr"><is><t>{escaped}</t></is></c>'


def build_tuning_xlsx(items: list[dict]) -> bytes:
    rows = [["Row", "Column", "Parameter", "Value"]]
    for item in items:
        rows.append(
            [
                item["row"],
                item["col"],
                DISPLAY_NAMES.get((item["row"], item["col"]), ""),
                item.get("value", ""),
            ]
        )

    sheet_rows = []
    for row_index, row_values in enumerate(rows, start=1):
        cells = "".join(
            xlsx_cell(value, col_index, row_index)
            for col_index, value in enumerate(row_values, start=1)
        )
        sheet_rows.append(f'<row r="{row_index}">{cells}</row>')

    sheet_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        '<sheetData>'
        f'{"".join(sheet_rows)}'
        '</sheetData>'
        '</worksheet>'
    )

    output = BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "[Content_Types].xml",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
            '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
            '</Types>',
        )
        archive.writestr(
            "_rels/.rels",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
            '</Relationships>',
        )
        archive.writestr(
            "xl/workbook.xml",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
            'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
            '<sheets><sheet name="Tuning Values" sheetId="1" r:id="rId1"/></sheets>'
            '</workbook>',
        )
        archive.writestr(
            "xl/_rels/workbook.xml.rels",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>'
            '</Relationships>',
        )
        archive.writestr("xl/worksheets/sheet1.xml", sheet_xml)
    return output.getvalue()


def load_shared_strings(archive: zipfile.ZipFile) -> list[str]:
    try:
        xml_data = archive.read("xl/sharedStrings.xml")
    except KeyError:
        return []

    root = ElementTree.fromstring(xml_data)
    ns = {"x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    strings = []
    for item in root.findall("x:si", ns):
        parts = [node.text or "" for node in item.findall(".//x:t", ns)]
        strings.append("".join(parts))
    return strings


def read_xlsx_cell(cell, shared_strings: list[str]) -> str:
    ns = {"x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    cell_type = cell.attrib.get("t")
    if cell_type == "inlineStr":
        return "".join(node.text or "" for node in cell.findall(".//x:t", ns)).strip()

    value_node = cell.find("x:v", ns)
    if value_node is None or value_node.text is None:
        return ""

    if cell_type == "s":
        try:
            return shared_strings[int(value_node.text)].strip()
        except (ValueError, IndexError):
            return ""

    return value_node.text.strip()


def column_number(cell_reference: str) -> int:
    total = 0
    for char in cell_reference:
        if not char.isalpha():
            break
        total = (total * 26) + (ord(char.upper()) - 64)
    return total


def parse_tuning_xlsx(file_data: bytes) -> dict[str, float]:
    with zipfile.ZipFile(BytesIO(file_data)) as archive:
        shared_strings = load_shared_strings(archive)
        sheet_xml = archive.read("xl/worksheets/sheet1.xml")

    root = ElementTree.fromstring(sheet_xml)
    ns = {"x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    table_rows = []
    for row in root.findall(".//x:sheetData/x:row", ns):
        values_by_col = {}
        for cell in row.findall("x:c", ns):
            ref = cell.attrib.get("r", "")
            values_by_col[column_number(ref)] = read_xlsx_cell(cell, shared_strings)

        if values_by_col:
            max_col = max(values_by_col)
            table_rows.append([values_by_col.get(col, "") for col in range(1, max_col + 1)])

    if not table_rows:
        return {}

    header = [str(value).strip().lower() for value in table_rows[0]]
    parsed = {}
    if {"row", "column", "value"}.issubset(set(header)):
        row_index = header.index("row")
        col_index = header.index("column")
        value_index = header.index("value")
        for row_values in table_rows[1:]:
            try:
                row = int(float(row_values[row_index]))
                col = int(float(row_values[col_index]))
                value = float(row_values[value_index])
            except (IndexError, ValueError):
                continue

            if 1 <= row <= PARAM_EDITABLE_ROW_COUNT and 1 <= col <= PARAM_COL_COUNT:
                parsed[key_for(row, col)] = value
        return parsed

    for row_number, row_values in enumerate(table_rows[:PARAM_EDITABLE_ROW_COUNT], start=1):
        for col_number, raw_value in enumerate(row_values[:PARAM_COL_COUNT], start=1):
            try:
                parsed[key_for(row_number, col_number)] = float(raw_value)
            except ValueError:
                continue
    return parsed


@dataclass
class TunerState:
    adapter: WaveshareCANA | None = None
    port: str | None = None
    detected_can_bitrate: int | None = None
    pic_id: str | None = None
    project_id: float | None = None
    firmware_id: float | None = None
    values: dict[str, float] = field(default_factory=dict)
    highlight_events: list[dict] = field(default_factory=list)
    event_counter: int = 0
    connected: bool = False
    zero_active: bool = False
    busy: bool = False
    operation: str = "Idle"
    state: str = "idle"
    message: str = "Select a COM port and connect."
    progress: int = 0
    total: int = 0
    lock: threading.Lock = field(default_factory=threading.Lock)
    can_lock: threading.Lock = field(default_factory=threading.Lock)
    zero_stop_event: threading.Event | None = None
    zero_thread: threading.Thread | None = None


tuner = TunerState()


def set_status(operation: str, state: str, message: str, progress: int = 0, total: int = 0) -> None:
    with tuner.lock:
        tuner.operation = operation
        tuner.state = state
        tuner.message = message
        tuner.progress = progress
        tuner.total = total


def serialize_status() -> dict:
    with tuner.lock:
        return {
            "connected": tuner.connected,
            "port": tuner.port,
            "detected_can_bitrate": tuner.detected_can_bitrate,
            "pic_id": tuner.pic_id,
            "project_id": tuner.project_id,
            "firmware_id": tuner.firmware_id,
            "zero_active": tuner.zero_active,
            "busy": tuner.busy,
            "operation": tuner.operation,
            "state": tuner.state,
            "message": tuner.message,
            "progress": tuner.progress,
            "total": tuner.total,
            "values": tuner.values.copy(),
            "highlight_events": list(tuner.highlight_events),
        }


def require_adapter() -> WaveshareCANA | None:
    with tuner.lock:
        return tuner.adapter


def fail(message: str, status_code: int = 400):
    set_status("Request", "failed", message)
    return jsonify({"ok": False, "error": message, "status": serialize_status()}), status_code


def update_cell_value(row: int, col: int, value: float, kind: str) -> None:
    with tuner.lock:
        cell_key = key_for(row, col)
        tuner.values[cell_key] = value
        tuner.event_counter += 1
        tuner.highlight_events.append(
            {
                "id": tuner.event_counter,
                "key": cell_key,
                "kind": kind,
            }
        )
        tuner.highlight_events = tuner.highlight_events[-160:]


def format_bitrate(bitrate: int | None) -> str:
    if bitrate is None:
        return "not detected"
    if bitrate >= 1_000_000 and bitrate % 1_000_000 == 0:
        return f"{bitrate // 1_000_000}M"
    if bitrate >= 1_000:
        return f"{bitrate // 1_000}k"
    return str(bitrate)


def is_baud_detect_frame(can_id: int, data: list[int]) -> bool:
    return can_id == CAN_ID_READ_RESP and data[:8] == AUTO_DETECT_FRAME


def wait_for_baud_detect_frame(adapter: WaveshareCANA, timeout: float = 1.35) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        frame = adapter.receive(timeout=max(0.02, deadline - time.monotonic()))
        if frame is None:
            return False

        can_id, data = frame
        if is_baud_detect_frame(can_id, data):
            return True

    return False


def read_exact_can_data(adapter: WaveshareCANA, expected_can_id: int, timeout: float = 1.5) -> list[int] | None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        frame = adapter.receive(timeout=max(0.02, deadline - time.monotonic()))
        if frame is None:
            return None

        can_id, data = frame
        if can_id == expected_can_id and len(data) >= 8:
            return list(data[:8])

    return None


def clear_pending_can_frames(adapter: WaveshareCANA) -> None:
    try:
        adapter.ser.reset_input_buffer()
    except Exception:
        pass


def request_pic_id_frame(adapter: WaveshareCANA, payload: list[int]) -> list[int] | None:
    adapter.send(PIC_ID_CAN_REQ, payload)
    return read_exact_can_data(adapter, PIC_ID_CAN_RESP, timeout=2.0)


def format_pic_id(raw_bytes: list[int]) -> str:
    groups = []
    for offset in range(0, len(raw_bytes), 4):
        groups.append("".join(f"{value:02X}" for value in raw_bytes[offset:offset + 4]))
    return "-".join(groups)


def read_pic_id(adapter: WaveshareCANA) -> str:
    clear_pending_can_frames(adapter)
    first_half = request_pic_id_frame(adapter, PIC_ID_1_REQUEST_PAYLOAD)
    if first_half is None:
        raise RuntimeError("No PIC ID response from 0xE1 for request 0x04")

    second_half = request_pic_id_frame(adapter, PIC_ID_2_REQUEST_PAYLOAD)
    if second_half is None:
        raise RuntimeError("No PIC ID response from 0xE1 for request 0x05")

    return format_pic_id(first_half + second_half)


def read_system_float_id(adapter: WaveshareCANA, slot: int) -> float:
    adapter.send(SYSTEM_ID_CAN_REQ, [READ_COMMAND, 0xFF, 0x00, slot, 0x00, 0x00, 0x00, 0x00])
    deadline = time.monotonic() + 1.5
    while time.monotonic() < deadline:
        frame = adapter.receive(timeout=max(0.02, deadline - time.monotonic()))
        if frame is None:
            break

        can_id, data = frame
        if can_id != SYSTEM_ID_CAN_RESP or len(data) < 8:
            continue
        if list(data[:4]) != [READ_COMMAND, 0xFF, 0x00, slot]:
            continue
        return struct.unpack("<f", bytes(data[4:8]))[0]

    raise RuntimeError(f"No response for system ID 0x{slot:02X}")


def write_system_float_id(adapter: WaveshareCANA, slot: int, value: float) -> float | None:
    value_bytes = struct.pack("<f", value)
    adapter.send(SYSTEM_ID_CAN_REQ, bytes([WRITE_COMMAND, 0xFF, 0x00, slot]) + value_bytes)

    deadline = time.monotonic() + 1.5
    while time.monotonic() < deadline:
        frame = adapter.receive(timeout=max(0.02, deadline - time.monotonic()))
        if frame is None:
            return None

        can_id, data = frame
        if can_id != SYSTEM_ID_CAN_RESP or len(data) < 8:
            continue
        if list(data[:4]) != [WRITE_COMMAND, 0xFF, 0x00, slot]:
            continue
        return struct.unpack("<f", bytes(data[4:8]))[0]

    return None


def detect_can_bitrate(port: str) -> tuple[WaveshareCANA, int]:
    tried = set()
    bitrates = []
    for bitrate in AUTO_DETECT_BITRATES:
        if bitrate in CAN_BITRATE_CODES and bitrate not in tried:
            tried.add(bitrate)
            bitrates.append(bitrate)

    for bitrate in bitrates:
        set_status("Connect", "running", f"Detecting CAN baud rate: {format_bitrate(bitrate)}...")
        adapter = None
        detected = False
        try:
            adapter = WaveshareCANA(port=port, baudrate=SERIAL_BAUDRATE, can_bitrate=bitrate)
            detected = wait_for_baud_detect_frame(adapter)
        except Exception:
            if adapter is None:
                raise
        finally:
            if adapter is not None and not detected:
                try:
                    adapter.close()
                except Exception:
                    pass
        if adapter is not None and detected:
            return adapter, bitrate

    supported = ", ".join(format_bitrate(bitrate) for bitrate in bitrates)
    raise RuntimeError(f"Could not detect CAN baud rate from heartbeat 0xE1. Tried: {supported}.")


def read_all_job(initial_delay: float = 0.0) -> None:
    if initial_delay > 0:
        set_status("Read", "running", "Connected. Preparing automatic read...", 0, PARAM_TOTAL)
        time.sleep(initial_delay)

    received = 0

    try:
        adapter = require_adapter()
        if adapter is None:
            raise RuntimeError("CAN adapter disconnected")

        set_status("Read", "running", "Reading PIC ID...", 0, PARAM_TOTAL)
        with tuner.can_lock:
            pic_id = read_pic_id(adapter)
            project_id = read_system_float_id(adapter, PROJECT_ID_SLOT)
            firmware_id = read_system_float_id(adapter, FIRMWARE_ID_SLOT)

        with tuner.lock:
            tuner.pic_id = pic_id
            tuner.project_id = project_id
            tuner.firmware_id = firmware_id

        set_status("Read", "running", "Reading all parameters...", 0, PARAM_TOTAL)

        for row in range(1, PARAM_ROW_COUNT + 1):
            for col in range(1, PARAM_COL_COUNT + 1):
                adapter = require_adapter()
                if adapter is None:
                    raise RuntimeError("CAN adapter disconnected")

                name = DISPLAY_NAMES.get((row, col), PARAM_NAMES.get((row, col), "Unknown"))
                current = ((row - 1) * PARAM_COL_COUNT) + col
                set_status("Read", "running", f"Reading row {row}, col {col}: {name}", current - 1, PARAM_TOTAL)

                with tuner.can_lock:
                    send_read_request(adapter, row, col)
                    value = read_matching_response(
                        adapter,
                        row,
                        col,
                        command=READ_COMMAND,
                        timeout=1.5,
                    )

                if value is not None:
                    update_cell_value(row, col, value, "read")
                    received += 1

                set_status("Read", "running", f"Read {received}/{current} responses", current, PARAM_TOTAL)
                time.sleep(0.03)

        set_status("Read", "finished", f"Read finished. Received {received}/{PARAM_TOTAL} values.", PARAM_TOTAL, PARAM_TOTAL)
    except Exception as exc:
        set_status("Read", "failed", f"Read failed: {exc}")
    finally:
        with tuner.lock:
            tuner.busy = False


def zero_angle_job(stop_event: threading.Event) -> None:
    set_status("Zero Angle", "running", "Listening for row 3 updates from MCU.", 0, 0)

    try:
        while not stop_event.is_set():
            adapter = require_adapter()
            if adapter is None:
                raise RuntimeError("CAN adapter disconnected")

            with tuner.can_lock:
                frame = read_zero_angle_frame(adapter, timeout=0.05)

            if frame is None:
                continue

            col, value = frame
            update_cell_value(ZERO_ANGLE_ROW, col, value, "zero")
            with tuner.lock:
                snapshot = {
                    key_for(ZERO_ANGLE_ROW, item_col): tuner.values.get(key_for(ZERO_ANGLE_ROW, item_col))
                    for item_col in range(1, 5)
                }

            message_values = []
            for item_col in range(1, 5):
                item_name = DISPLAY_NAMES.get((ZERO_ANGLE_ROW, item_col), f"Col {item_col}")
                item_value = snapshot[key_for(ZERO_ANGLE_ROW, item_col)]
                if item_value is None:
                    message_values.append(f"{item_name}: no data")
                else:
                        message_values.append(f"{item_name}: {item_value:.2f}")

            set_status("Zero Angle", "running", " | ".join(message_values))

        set_status("Zero Angle", "finished", "Zero angle operation stopped.")
    except Exception as exc:
        set_status("Zero Angle", "failed", f"Zero angle failed: {exc}")
    finally:
        with tuner.lock:
            tuner.zero_active = False
            tuner.busy = False
            tuner.zero_stop_event = None
            tuner.zero_thread = None


@app.get("/")
def index():
    return render_template("index.html", parameters=build_parameters())


@app.get("/api/ports")
def ports():
    available = [
        {
            "device": port.device,
            "description": port.description,
        }
        for port in list_ports.comports()
    ]
    return jsonify({"ok": True, "ports": available})


@app.get("/api/status")
def status():
    return jsonify({"ok": True, "status": serialize_status()})


@app.post("/api/connect")
def connect():
    payload = request.get_json(silent=True) or {}
    port = payload.get("port")
    if not port:
        return fail("Select a COM port first.")

    with tuner.lock:
        already_connected = tuner.connected
    if already_connected:
        return fail("Already connected. Disconnect before changing port.")

    set_status("Connect", "running", f"Connecting to {port}. Detecting CAN baud rate...")
    try:
        adapter, detected_bitrate = detect_can_bitrate(port)
    except Exception as exc:
        return fail(f"Connection failed: {exc}", 500)

    with tuner.lock:
        tuner.adapter = adapter
        tuner.port = port
        tuner.detected_can_bitrate = detected_bitrate
        tuner.pic_id = None
        tuner.project_id = None
        tuner.firmware_id = None
        tuner.connected = True
        tuner.busy = True
        tuner.values.clear()
        tuner.highlight_events.clear()

    thread = threading.Thread(target=read_all_job, args=(0.8,), daemon=True)
    thread.start()

    set_status("Read", "running", f"Connected on {port} at {format_bitrate(detected_bitrate)}. Reading parameters...", 0, PARAM_TOTAL)
    return jsonify({"ok": True, "status": serialize_status()})


@app.post("/api/disconnect")
def disconnect():
    with tuner.lock:
        adapter = tuner.adapter
        zero_event = tuner.zero_stop_event
        tuner.adapter = None
        tuner.port = None
        tuner.detected_can_bitrate = None
        tuner.pic_id = None
        tuner.project_id = None
        tuner.firmware_id = None
        tuner.connected = False
        tuner.zero_active = False
        tuner.busy = False

    if zero_event is not None:
        zero_event.set()

    if adapter is not None:
        try:
            with tuner.can_lock:
                adapter.close()
        except Exception:
            pass

    set_status("Disconnect", "finished", "Disconnected.")
    return jsonify({"ok": True, "status": serialize_status()})


@app.post("/api/read")
def read_all():
    with tuner.lock:
        connected = tuner.connected
        busy = tuner.busy
        if connected and not busy:
            tuner.busy = True

    if not connected:
        return fail("Connect to a COM port first.")
    if busy:
        return fail("Another operation is already running.")

    thread = threading.Thread(target=read_all_job, daemon=True)
    thread.start()
    return jsonify({"ok": True, "status": serialize_status()})


@app.post("/api/write")
def write_values():
    payload = request.get_json(silent=True) or {}

    raw_items = payload.get("items")
    if raw_items is None:
        raw_items = [payload] if "row" in payload or "col" in payload else []
    raw_system_ids = payload.get("system_ids") or {}

    if not isinstance(raw_items, list):
        return fail("Invalid write request.")
    if not isinstance(raw_system_ids, dict):
        return fail("Invalid system ID write request.")
    if not raw_items and not raw_system_ids:
        return fail("Modify one or more values before writing.")

    items = []
    for raw_item in raw_items:
        try:
            row = int(raw_item.get("row"))
            col = int(raw_item.get("col"))
            value = float(raw_item.get("value"))
        except (AttributeError, TypeError, ValueError):
            return fail("Every modified cell must contain a numeric value.")

        if not 1 <= row <= PARAM_EDITABLE_ROW_COUNT or not 1 <= col <= PARAM_COL_COUNT:
            return fail("Invalid row or column.")

        items.append({"row": row, "col": col, "value": value})

    system_items = []
    system_id_slots = {
        "project_id": (PROJECT_ID_SLOT, "Project ID"),
        "firmware_id": (FIRMWARE_ID_SLOT, "Firmware ID"),
    }
    for key, (slot, label) in system_id_slots.items():
        if key not in raw_system_ids:
            continue
        try:
            value = round(float(raw_system_ids.get(key)), 1)
        except (TypeError, ValueError):
            return fail(f"{label} must contain a numeric value.")
        system_items.append({"key": key, "slot": slot, "label": label, "value": value})

    if not items and not system_items:
        return fail("Modify one or more values before writing.")

    with tuner.lock:
        connected = tuner.connected
        busy = tuner.busy
        if connected and not busy:
            tuner.busy = True

    if not connected:
        return fail("Connect to a COM port first.")
    if busy:
        return fail("Another operation is already running.")

    total = len(items) + len(system_items)
    set_status("Write", "running", f"Writing {total} value(s)...", 0, total)
    try:
        adapter = require_adapter()
        if adapter is None:
            raise RuntimeError("CAN adapter disconnected")

        confirmed_count = 0
        failed_items = []
        current_index = 0

        for item in items:
            current_index += 1
            row = item["row"]
            col = item["col"]
            value = item["value"]
            name = DISPLAY_NAMES.get((row, col), PARAM_NAMES.get((row, col), "Unknown"))
            set_status("Write", "running", f"Writing row {row}, col {col}: {name}", current_index - 1, total)

            with tuner.can_lock:
                send_write_request(adapter, row, col, value)
                confirmed = read_matching_response(
                    adapter,
                    row,
                    col,
                    command=WRITE_COMMAND,
                    timeout=1.5,
                )

            if confirmed is None:
                failed_items.append(f"row {row}, col {col}")
            else:
                update_cell_value(row, col, confirmed, "write")
                confirmed_count += 1

            set_status(
                "Write",
                "running",
                f"Written {confirmed_count}/{current_index} value(s)",
                current_index,
                total,
            )
            time.sleep(0.03)

        for item in system_items:
            current_index += 1
            key = item["key"]
            slot = item["slot"]
            label = item["label"]
            value = item["value"]
            set_status("Write", "running", f"Writing {label}", current_index - 1, total)

            with tuner.can_lock:
                confirmed = write_system_float_id(adapter, slot, value)

            if confirmed is None:
                failed_items.append(label)
            else:
                with tuner.lock:
                    setattr(tuner, key, confirmed)
                confirmed_count += 1

            set_status(
                "Write",
                "running",
                f"Written {confirmed_count}/{current_index} value(s)",
                current_index,
                total,
            )
            time.sleep(0.03)

        with tuner.can_lock:
            send_write_complete_request(adapter)

        if failed_items:
            failed_text = ", ".join(failed_items[:4])
            if len(failed_items) > 4:
                failed_text += f", +{len(failed_items) - 4} more"
            set_status(
                "Write",
                "failed",
                f"Write finished with missing confirmations: {failed_text}.",
                total,
                total,
            )
            return jsonify({"ok": False, "status": serialize_status()}), 504

        set_status("Write", "finished", f"Write finished. Confirmed {confirmed_count}/{total} value(s).", total, total)
        return jsonify({"ok": True, "status": serialize_status(), "written": confirmed_count})
    except Exception as exc:
        set_status("Write", "failed", f"Write failed: {exc}")
        return jsonify({"ok": False, "status": serialize_status()}), 500
    finally:
        with tuner.lock:
            tuner.busy = False


@app.post("/api/import-tuning")
def import_tuning():
    uploaded_file = request.files.get("file")
    if uploaded_file is None or not uploaded_file.filename.lower().endswith(".xlsx"):
        return fail("Select a valid .xlsx tuning file.")

    try:
        imported_values = parse_tuning_xlsx(uploaded_file.read())
    except Exception as exc:
        return fail(f"Import failed: {exc}", 400)

    if not imported_values:
        return fail("Import failed: no valid tuning values found.")

    set_status("Import", "finished", f"Imported {len(imported_values)} value(s). Review and press Write.")
    return jsonify({"ok": True, "values": imported_values, "status": serialize_status()})


@app.post("/api/export-tuning")
def export_tuning():
    payload = request.get_json(silent=True) or {}
    values = payload.get("values") or {}
    items = []

    for row in range(1, PARAM_ROW_COUNT + 1):
        for col in range(1, PARAM_COL_COUNT + 1):
            raw_value = values.get(key_for(row, col), "")
            try:
                value = float(raw_value) if raw_value != "" else ""
            except (TypeError, ValueError):
                value = ""

            items.append({"row": row, "col": col, "value": value})

    xlsx_data = build_tuning_xlsx(items)
    headers = {"Content-Disposition": 'attachment; filename="can_tuning_values.xlsx"'}
    set_status("Export", "finished", "Exported current tuning values.")
    return Response(xlsx_data, mimetype=XLSX_MIME, headers=headers)


@app.post("/api/zero-angle/toggle")
def zero_angle_toggle():
    with tuner.lock:
        connected = tuner.connected
        busy = tuner.busy
        zero_active = tuner.zero_active
        zero_stop_event = tuner.zero_stop_event

        if zero_active and zero_stop_event is not None:
            zero_stop_event.set()
            stop_requested = True
        else:
            stop_requested = False

        if not stop_requested and connected and not busy:
            stop_event = threading.Event()
            tuner.zero_stop_event = stop_event
            tuner.zero_active = True
            tuner.busy = True
        else:
            stop_event = None

    if stop_requested:
        return jsonify({"ok": True, "status": serialize_status()})
    if not connected:
        return fail("Connect to a COM port first.")
    if busy:
        return fail("Another operation is already running.")

    thread = threading.Thread(target=zero_angle_job, args=(stop_event,), daemon=True)
    with tuner.lock:
        tuner.zero_thread = thread
    thread.start()
    return jsonify({"ok": True, "status": serialize_status()})


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True, use_reloader=False)
