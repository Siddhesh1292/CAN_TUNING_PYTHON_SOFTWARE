import can

try:
    bus = can.interface.Bus(
        interface='slcan',
        channel='COM10',
        bitrate=500000,
        tty_baudrate=115200,
        timeout=1,
        rtscts=False
    )

    print("CAN Bus Opened Successfully!")

    msg = can.Message(
        arbitration_id=0x123,
        data=[1, 2, 3, 4],
        is_extended_id=False
    )

    bus.send(msg)

    print("Test frame sent!")

    bus.shutdown()

except Exception as e:
    print("ERROR:")
    print(e)