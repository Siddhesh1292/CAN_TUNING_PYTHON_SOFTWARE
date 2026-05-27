import serial
import struct
import time

class WaveshareCANA:

    START_BYTE = 0xAA
    END_BYTE   = 0x55

    SPEED_TABLE = {
        1000000: 0x01,
        800000:  0x02,
        500000:  0x03,
        400000:  0x04,
        250000:  0x05,
        200000:  0x06,
        125000:  0x07,
        100000:  0x08,
        50000:   0x09,
        20000:   0x0A,
        10000:   0x0B,
        5000:    0x0C
    }

    def __init__(self, port='COM8',
                 baudrate=2000000,
                 can_bitrate=500000):
        self.ser = serial.Serial(
            port=port,
            baudrate=baudrate,
            timeout=1
        )
        self.can_bitrate = can_bitrate
        print(f"Connected on {port} at {baudrate} baud")
        self._set_speed(can_bitrate)

    def _set_speed(self, bitrate):
        speed_byte = self.SPEED_TABLE.get(bitrate, 0x03)
        frame = bytes([0xAA, 0x55, speed_byte, 0x55])
        self.ser.write(frame)
        time.sleep(0.1)
        print(f"CAN speed set to {bitrate} bps")

    def send(self, can_id, data):
        dlc       = len(data)
        type_byte = 0xC0 | dlc
        id_bytes  = struct.pack('<I', can_id)
        frame     = (bytes([self.START_BYTE, type_byte]) +
                     id_bytes +
                     bytes(data) +
                     bytes([self.END_BYTE]))
        self.ser.write(frame)

    def receive(self, timeout=1.0):
        start_time = time.time()
        while time.time() - start_time < timeout:
            if self.ser.in_waiting >= 1:
                byte = self.ser.read(1)
                if byte == bytes([self.START_BYTE]):
                    type_byte = self.ser.read(1)
                    if not type_byte:
                        continue
                    dlc      = type_byte[0] & 0x0F
                    id_bytes = self.ser.read(4)
                    if len(id_bytes) < 4:
                        continue
                    can_id = struct.unpack('<I', id_bytes)[0]
                    data   = self.ser.read(dlc)
                    end    = self.ser.read(1)
                    if end == bytes([self.END_BYTE]):
                        return (can_id, list(data))
        return None

    def close(self):
        self.ser.close()
        print("Connection closed")