import struct
import time
from waveshare_can import WaveshareCANA

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

TOTAL_ROWS       = 11
TOTAL_COLS       = 4
TOTAL_PARAMS     = 44
CAN_ID_READ_REQ  = 0xE0
CAN_ID_READ_RESP = 0xE1

def send_read_request(adapter, row, col):
    data = [0x00, 0xFF, row, col,
            0x00, 0x00, 0x00, 0x00]
    adapter.send(CAN_ID_READ_REQ, data)
    return True

def receive_one_parameter(adapter):
    result = adapter.receive(timeout=1.0)
    if result is None:
        return None

    can_id, data = result

    if can_id == CAN_ID_READ_RESP and len(data) >= 8:
        param_id    = data[3]
        float_bytes = bytes(data[4:8])
        value       = struct.unpack('f', float_bytes)[0]
        return (param_id, value)

    return None

def print_summary(params):
    print("\n══════════════════════════════════════════════")
    print("PARAMETER SUMMARY")
    print("══════════════════════════════════════════════")
    for param_id, value in sorted(params.items()):
        name = PARAM_NAMES.get(param_id, "Unknown")
        print(f"  0x{param_id:02X}  {name:<35} = {value:.4f}")
    print(f"\nTotal received: {len(params)}/{TOTAL_PARAMS}")
    print("══════════════════════════════════════════════")

def main():
    try:
        adapter = WaveshareCANA(
            port='COM8',
            baudrate=2000000,    # Waveshare default!
            can_bitrate=500000   # match PIC32 MHC
        )
    except Exception as e:
        print(f"Connection failed: {e}")
        return

    try:
        print("\nEnter 'r' to read all parameters")
        choice = input("Choice: ").strip().lower()

        if choice == 'r':
            params = {}
            count  = 0
            print("\nReading all 44 parameters row by row...")
            print("══════════════════════════════════════════════")

            for row in range(1, TOTAL_ROWS + 1):
                for col in range(1, TOTAL_COLS + 1):
                    send_read_request(adapter, row, col)
                    result = receive_one_parameter(adapter)

                    if result is not None:
                        param_id, value = result
                        params[param_id] = value
                        count += 1
                        name = PARAM_NAMES.get(
                            param_id,
                            f"Unknown 0x{param_id:02X}")
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

            print_summary(params)

        else:
            print("Invalid — enter r to read")

    except KeyboardInterrupt:
        print("\nStopped!")

    finally:
        adapter.close()

if __name__ == "__main__":
    main()