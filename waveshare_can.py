from __future__ import annotations

import time
from dataclasses import dataclass

import serial


SERIAL_BAUDRATE = 2_000_000

CAN_BITRATE_CODES = {
    1_000_000: 0x01,
    800_000: 0x02,
    500_000: 0x03,
    400_000: 0x04,
    250_000: 0x05,
    200_000: 0x06,
    125_000: 0x07,
    100_000: 0x08,
    50_000: 0x09,
    20_000: 0x0A,
    10_000: 0x0B,
    5_000: 0x0C,
}


@dataclass(frozen=True)
class CanFrame:
    can_id: int
    data: bytes
    extended: bool = False
    remote: bool = False


def checksum(frame_without_checksum: bytes) -> int:
    return sum(frame_without_checksum[2:19]) & 0xFF


def build_config_frame(can_bitrate: int) -> bytes:
    if can_bitrate not in CAN_BITRATE_CODES:
        supported = ", ".join(str(rate) for rate in sorted(CAN_BITRATE_CODES))
        raise ValueError(f"Unsupported CAN bitrate {can_bitrate}. Use one of: {supported}")

    frame = bytearray(20)
    frame[0:3] = b"\xAA\x55\x12"
    frame[3] = CAN_BITRATE_CODES[can_bitrate]
    frame[4] = 0x01
    frame[5:13] = b"\x00" * 8
    frame[13] = 0x00
    frame[14] = 0x00
    frame[15:19] = b"\x00" * 4
    frame[19] = checksum(frame)
    return bytes(frame)


def build_variable_frame(can_id: int, data: bytes, extended: bool = False) -> bytes:
    if not 0 <= len(data) <= 8:
        raise ValueError("CAN data length must be 0..8 bytes")

    if extended:
        if not 0 <= can_id <= 0x1FFFFFFF:
            raise ValueError("Extended CAN ID must be 0..0x1FFFFFFF")
        frame_type = 0xE0 | len(data)
        id_bytes = can_id.to_bytes(4, "little")
    else:
        if not 0 <= can_id <= 0x7FF:
            raise ValueError("Standard CAN ID must be 0..0x7FF")
        frame_type = 0xC0 | len(data)
        id_bytes = can_id.to_bytes(2, "little")

    return b"\xAA" + bytes([frame_type]) + id_bytes + data + b"\x55"


def read_exact(ser: serial.Serial, count: int, deadline: float) -> bytes | None:
    data = bytearray()
    while len(data) < count and time.monotonic() < deadline:
        chunk = ser.read(count - len(data))
        if chunk:
            data.extend(chunk)
    return bytes(data) if len(data) == count else None


def read_variable_frame(ser: serial.Serial, timeout: float) -> CanFrame | None:
    deadline = time.monotonic() + timeout

    while time.monotonic() < deadline:
        if ser.read(1) != b"\xAA":
            continue

        type_byte = read_exact(ser, 1, deadline)
        if not type_byte:
            return None

        frame_type = type_byte[0]
        data_len = frame_type & 0x0F
        is_extended = bool(frame_type & 0x20)
        is_remote = bool(frame_type & 0x10)

        if data_len > 8:
            continue

        id_len = 4 if is_extended else 2
        payload = read_exact(ser, id_len + data_len + 1, deadline)
        if not payload or payload[-1] != 0x55:
            continue

        return CanFrame(
            can_id=int.from_bytes(payload[:id_len], "little"),
            data=payload[id_len:-1],
            extended=is_extended,
            remote=is_remote,
        )

    return None


class WaveshareCANA:
    def __init__(
        self,
        port: str = "COM8",
        baudrate: int = SERIAL_BAUDRATE,
        can_bitrate: int = 500_000,
        skip_config: bool = False,
    ):
        self.ser = serial.Serial(port, baudrate, timeout=0.02)
        self.ser.reset_input_buffer()
        self.ser.reset_output_buffer()

        if not skip_config:
            self.ser.write(build_config_frame(can_bitrate))
            self.ser.flush()
            time.sleep(0.2)
            self.ser.reset_input_buffer()

    def send(self, can_id: int, data: bytes | list[int], extended: bool = False) -> None:
        payload = bytes(data)
        self.ser.write(build_variable_frame(can_id, payload, extended=extended))
        self.ser.flush()

    def receive(self, timeout: float = 1.0) -> tuple[int, list[int]] | None:
        frame = read_variable_frame(self.ser, timeout)
        if frame is None:
            return None
        return frame.can_id, list(frame.data)

    def close(self) -> None:
        self.ser.close()
