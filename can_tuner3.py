import struct
import threading
import time

from waveshare_can import WaveshareCANA


PORT = "COM8"
SERIAL_BAUDRATE = 2_000_000
CAN_BITRATE = 500_000

CAN_ID_READ_REQ = 0xE0
CAN_ID_READ_RESP = 0xE1
READ_COMMAND = 0x00
WRITE_COMMAND = 0x01
WRITE_COMPLETE_COMMAND = 0x02
FRAME_MARKER = 0xFF
ZERO_ANGLE_ROW = 3

PARAM_NAMES = {
    (1, 1): "ESC_ID",
    (1, 2): "Peak Current",
    (1, 3): "Max Rpm",
    (1, 4): "No.of poles",
    (2, 1): "Phase Resistance",
    (2, 2): "D-Inductance",
    (2, 3): "Q-Inductance",
    (2, 4): "Flux",
    (3, 1): "Zero Angle",
    (3, 2): "Sensor reversal",
    (3, 3): "Zero angle estimation",
    (3, 4): "Sensor reversal estimation",
    (4, 1): "Rotation direction",
    (4, 2): "NA",
    (4, 3): "kmph/rpm",
    (4, 4): "rpm fault",
    (5, 1): "Motor derate",
    (5, 2): "Motor T fault",
    (5, 3): "ESC Derate",
    (5, 4): "ESC T fault",
    (6, 1): "Battery Max Voltage",
    (6, 2): "Ibat default",
    (6, 3): "Over voltage fault",
    (6, 4): "Under voltage fault",
    (7, 1): "Max Battery Current",
    (7, 2): "Max regen current",
    (7, 3): "Phase Ifault",
    (7, 4): "Battery Ifault",
    (8, 1): "Reverse rpm",
    (8, 2): "Driving mode",
    (8, 3): "L mode rpm",
    (8, 4): "M mode rpm",
    (9, 1): "Throttle zero",
    (9, 2): "Throttle max",
    (9, 3): "Break limit voltage",
    (9, 4): "Auto break",
    (10, 1): "rpm kp",
    (10, 2): "rpm ki",
    (10, 3): "L mode acceleration",
    (10, 4): "M mode acceleration",
    (11, 1): "L mode battery current",
    (11, 2): "M mode battery current",
    (11, 3): "L mode phase current",
    (11, 4): "M mode phase current",
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

PARAM_ROW_COUNT = 15
PARAM_EDITABLE_ROW_COUNT = 12
PARAM_COL_COUNT = 4
PARAM_TOTAL = PARAM_ROW_COUNT * PARAM_COL_COUNT


def connect_bus():
    print("Connecting to Waveshare USB-CAN-A...")
    try:
        adapter = WaveshareCANA(
            port=PORT,
            baudrate=SERIAL_BAUDRATE,
            can_bitrate=CAN_BITRATE,
        )
    except Exception as exc:
        print(f"Connection failed: {exc}")
        return None

    print(f"Connected on {PORT}, CAN {CAN_BITRATE}")
    return adapter


def send_read_request(adapter, row, col):
    data = [READ_COMMAND, 0xFF, row, col, 0x00, 0x00, 0x00, 0x00]
    adapter.send(CAN_ID_READ_REQ, data)


def send_write_request(adapter, row, col, value):
    value_bytes = struct.pack("<f", value)
    data = bytes([WRITE_COMMAND, 0xFF, row, col]) + value_bytes
    adapter.send(CAN_ID_READ_REQ, data)


def send_write_complete_request(adapter):
    data = [WRITE_COMPLETE_COMMAND, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00]
    adapter.send(CAN_ID_READ_REQ, data)


def read_matching_response(adapter, row, col, command=None, timeout=1.0):
    deadline = time.monotonic() + timeout

    while time.monotonic() < deadline:
        remaining = deadline - time.monotonic()
        received = adapter.receive(timeout=remaining)
        if received is None:
            break

        can_id, data = received
        if can_id != CAN_ID_READ_RESP or len(data) < 8:
            continue

        if command is not None and data[0] != command:
            continue

        resp_row = data[2]
        resp_col = data[3]
        if resp_row != row or resp_col != col:
            continue

        return struct.unpack("<f", bytes(data[4:8]))[0]

    return None


def read_int(prompt, minimum, maximum):
    while True:
        raw = input(prompt).strip()
        try:
            value = int(raw)
        except ValueError:
            print("  enter a whole number")
            continue

        if minimum <= value <= maximum:
            return value

        print(f"  enter a number from {minimum} to {maximum}")


def read_float(prompt):
    while True:
        raw = input(prompt).strip()
        try:
            return float(raw)
        except ValueError:
            print("  enter a numeric value")


def wait_for_zero_angle_stop(stop_event):
    while not stop_event.is_set():
        command = input().strip().lower()
        if command == "z":
            stop_event.set()


def want_to_read(adapter):
    if adapter is None:
        print("bus is not connected")
        return

    results = {}

    for row in range(1, PARAM_ROW_COUNT + 1):
        for col in range(1, PARAM_COL_COUNT + 1):
            name = PARAM_NAMES.get((row, col), "Unknown")
            print(f"Reading row:{row}, col:{col} {name}")

            try:
                send_read_request(adapter, row, col)
            except Exception as exc:
                print(f"  send failed: {exc}")
                continue

            value = read_matching_response(adapter, row, col, command=READ_COMMAND, timeout=1.5)
            if value is None:
                print("  no response")
                continue

            results[(row, col)] = value
            print(f"  value: {value:.2f}")
            time.sleep(0.05)

    print_summary(results)


def want_to_write(adapter):
    if adapter is None:
        print("bus is not connected")
        return

    row = read_int(f"Enter row number (1-{PARAM_EDITABLE_ROW_COUNT}): ", 1, PARAM_EDITABLE_ROW_COUNT)
    col = read_int(f"Enter column number (1-{PARAM_COL_COUNT}): ", 1, PARAM_COL_COUNT)
    name = PARAM_NAMES.get((row, col), "Unknown")
    value = read_float(f"Enter new value for {name}: ")

    print(f"Writing row:{row}, col:{col} {name} = {value}")

    try:
        send_write_request(adapter, row, col, value)
    except Exception as exc:
        print(f"  send failed: {exc}")
        return

    confirmed = read_matching_response(adapter, row, col, command=WRITE_COMMAND, timeout=1.5)
    if confirmed is None:
        print("  no confirmation response")
        return

    print(f"  MCU confirmed value: {confirmed:.2f}")


def decode_zero_angle_value(raw_bytes):
    value_le = struct.unpack("<f", raw_bytes)[0]
    if value_le == 0.0:
        return 0.0
    if abs(value_le) >= 1e-30:
        return value_le

    value_be = struct.unpack(">f", raw_bytes)[0]
    if abs(value_be) >= 1e-30 and abs(value_be) <= 1_000_000:
        return value_be

    return float(struct.unpack("<i", raw_bytes)[0])


def read_zero_angle_frame(adapter, timeout=0.05):
    received = adapter.receive(timeout=timeout)
    if received is None:
        return None

    can_id, data = received
    if can_id != CAN_ID_READ_RESP or len(data) < 8:
        return None

    if data[1] != FRAME_MARKER:
        return None

    row = data[2]
    col = data[3]
    if row != ZERO_ANGLE_ROW or not 1 <= col <= 4:
        return None

    value = decode_zero_angle_value(bytes(data[4:8]))
    return col, value


def format_zero_angle_row(latest_values):
    return " | ".join(
        f"{PARAM_NAMES.get((ZERO_ANGLE_ROW, col), 'Unknown')}: "
        f"{latest_values[col]:.2f}" if col in latest_values else
        f"{PARAM_NAMES.get((ZERO_ANGLE_ROW, col), 'Unknown')}: no data"
        for col in range(1, 5)
    )


def want_zero_angle_row(adapter, stop_event=None, read_stop_from_terminal=True):
    if adapter is None:
        print("bus is not connected")
        return

    if stop_event is None:
        stop_event = threading.Event()

    if read_stop_from_terminal:
        stopper = threading.Thread(
            target=wait_for_zero_angle_stop,
            args=(stop_event,),
            daemon=True,
        )
        stopper.start()

    print("Listening for zero angle row data. Type z and press Enter to stop.")
    latest_values = {}

    while not stop_event.is_set():
        frame = read_zero_angle_frame(adapter)
        if frame is None:
            continue

        col, value = frame
        latest_values[col] = value
        print(format_zero_angle_row(latest_values))

    print("zero angle row read stopped")


def print_summary(results):
    print("")
    print("PARAMETER SUMMARY")
    print("=" * 72)
    for row in range(1, PARAM_ROW_COUNT + 1):
        for col in range(1, PARAM_COL_COUNT + 1):
            name = PARAM_NAMES.get((row, col), "Unknown")
            value = results.get((row, col))
            if value is None:
                print(f"[{row:02d},{col}] {name:<35} no response")
            else:
                print(f"[{row:02d},{col}] {name:<35} {value:.2f}")
    print("=" * 72)
    print(f"Total received: {len(results)}/{PARAM_TOTAL}")


def main():
    adapter = None
    try:
        while True:
            print("")
            print("Enter r to read all parameters")
            print("Enter w to write one parameter")
            print("Enter z to read zero angle row continuously")
            print("Enter q to quit")
            choice = input("Enter choice: ").strip().lower()

            if choice == "q":
                break

            if choice in ("r", "w", "z") and adapter is None:
                adapter = connect_bus()
                if adapter is None:
                    return

            if choice == "r":
                want_to_read(adapter)
            elif choice == "w":
                want_to_write(adapter)
            elif choice == "z":
                want_zero_angle_row(adapter)
            else:
                print("invalid choice")
    except KeyboardInterrupt:
        print("\nstopped by user")
    finally:
        if adapter is not None:
            adapter.close()
        print("everything done")


if __name__ == "__main__":
    main()
