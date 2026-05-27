import can
import time
import struct
import libusb_package
import usb.core

# ── Parameter names ───────────────────────────────────────────
PARAM_NAMES = {
    0x01: "ESC_ID",
    0x02: "Peak Current",
    0x03: "Max Rpm",
    0x04: "No.of poles",
    0x05: "Phase Resistance",
    0x06: "D-Inductance",
    0x07: "Q-Inductance",
    0x08: "Flux",
    0x09: "Zero Angle",
    0x0A: "Sensor reversal",
    0x0B: "Zero angle estimation",
    0x0C: "Sensor reversal estimation",
    0x0D: "Rotation direction",
    0x0E: "NA",
    0x0F: "kmph/rpm",
    0x10: "rpm fault",
    0x11: "Motor derate",
    0x12: "Motor T fault",
    0x13: "ESC Derate",
    0x14: "ESC T fault",
    0x15: "Battery Max Voltage",
    0x16: "Ibat default",
    0x17: "Over voltage fault",
    0x18: "Under voltage fault",
    0x19: "Max Battery Current",
    0x1A: "Max regen current",
    0x1B: "Phase Ifault",
    0x1C: "Battery Ifault",
    0x1D: "Reverse rpm",
    0x1E: "Driving mode",
    0x1F: "L mode rpm",
    0x20: "M mode rpm",
    0x21: "Throttle zero",
    0x22: "Throttle max",
    0x23: "Break limit voltage",
    0x24: "Auto break",
    0x25: "rpm kp",
    0x26: "rpm ki",
    0x27: "L mode acceleration",
    0x28: "M mode acceleration",
    0x29: "L mode battery current",
    0x2A: "M mode battery current",
    0x2B: "L mode phase current",
    0x2C: "M mode phase current"
}

TOTAL_ROWS      = 11
TOTAL_COLS      = 4
TOTAL_PARAMS    = 44
CAN_ID_READ_REQ = 0xE0
CAN_ID_READ_RESP= 0xE1

def connect_bus():
    try:
        bus = can.interface.Bus(
            interface='slcan',
            channel='COM8',
            bitrate=500000,
            sleep_after_open=0.1,    # wait after open
            rtscts=False,            # no hardware flow control
            ttyBaudrate=9600       # serial port baud rate
                             # this is DIFFERENT from CAN bitrate!
                             # CH340 serial speed = 115200
)
    except Exception as e:
        print(f"Connection failed: {e}")
        print("Check if COM8 is correct in Device Manager")
        return None
# ── Send read request for one block ──────────────────────────
def send_read_request(bus, row, col):
    msg = can.Message(
        arbitration_id=CAN_ID_READ_REQ,
        data=[
            0x00,    # byte 0 = 0x00 = READ
            0xFF,    # byte 1 = always 0xFF
            row,     # byte 2 = row number 1-11
            col,     # byte 3 = col number 1-4
            0x00,    # byte 4 = unused
            0x00,    # byte 5 = unused
            0x00,    # byte 6 = unused
            0x00     # byte 7 = unused
        ],
        is_extended_id=False
    )
    try:
        bus.send(msg)
        return True
    except can.CanError as e:
        print(f"Send failed Row={row} Col={col}: {e}")
        return False

# ── Receive one parameter response ───────────────────────────
def receive_one_parameter(bus):
    rx = bus.recv(timeout=1.0)

    if rx is None:
        return None

    if rx.arbitration_id == CAN_ID_READ_RESP:
        # extract param id from byte 3
        param_id = rx.data[3]

        # extract float from bytes 4-7 using struct
        float_bytes = bytes(rx.data[4:8])
        value = struct.unpack('f', float_bytes)[0]

        return (param_id, value)

    return None

# ── Print summary ─────────────────────────────────────────────
def print_summary(params):
    print("\n══════════════════════════════════════════════")
    print("PARAMETER SUMMARY")
    print("══════════════════════════════════════════════")
    for param_id, value in sorted(params.items()):
        name = PARAM_NAMES.get(param_id, "Unknown")
        print(f"  0x{param_id:02X}  {name:<35} = {value:.4f}")
    print(f"\nTotal received: {len(params)}/{TOTAL_PARAMS}")
    print("══════════════════════════════════════════════")

# ── Main ──────────────────────────────────────────────────────
def main():
    bus = connect_bus()
    if bus is None:
        return

    try:
        print("\nEnter 'r' to read all parameters")
        choice = input("Choice: ").strip().lower()

        if choice == 'r':
            params = {}
            print("\nReading all 44 parameters row by row...")
            print("══════════════════════════════════════════════")

            count = 0
            for row in range(1, TOTAL_ROWS + 1):
                for col in range(1, TOTAL_COLS + 1):

                    # send request for this block
                    if send_read_request(bus, row, col):

                        # receive response
                        result = receive_one_parameter(bus)

                        if result is not None:
                            param_id, value = result
                            params[param_id] = value
                            count += 1
                            name = PARAM_NAMES.get(
                                param_id,
                                f"Unknown(0x{param_id:02X})")
                            print(
                                f"  [{count:02d}/44] "
                                f"Row={row} Col={col} "
                                f"ID=0x{param_id:02X} "
                                f"{name:<35} = {value:.4f}")
                        else:
                            print(
                                f"  [--/44] "
                                f"Row={row} Col={col} "
                                f"NO RESPONSE")

            # print full summary
            print_summary(params)

        else:
            print("Invalid choice — enter r to read")

    except KeyboardInterrupt:
        print("\nStopped by user")

    finally:
        bus.shutdown()
        print("Bus closed")

if __name__ == "__main__":
    main()