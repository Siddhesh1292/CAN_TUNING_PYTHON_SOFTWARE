import struct 
import can

def connect_bus():
    print("connecting to CAN bus...")
    try:
        bus = can.interface.Bus(
            interface = 'slcan',
            channel = 'COM10',
            bitrate = 500000,
            tty_baudrate = 115200,
            timeout = 1.0,
            rtscts = False
    )   
        print("bus connected")
        return bus
        
    except can.CanError as e:
        print(f"connection failed:{e}")
        return None

def want_to_read(bus):
    if bus is None:
        print("bus is not connected")
        return

    for row in range(1,12):
        for col in range(1,5):
            msg = can.Message(0xE0 ,
                            data = [0x00 , 0xFF , row , col , 0x00 , 0x00 , 0x00 , 0x00],
                            is_extended_id = False)
            print(f"sending request row:{row}, col:{col}")
            try:
                bus.send(msg, timeout=1.0)
            except can.CanError as e:
                print(f"send failed for row:{row}, col:{col}: {e}")
                continue
            receive_one_parameter(bus, row , col)

def receive_one_parameter(bus , row , col):
    received = bus.recv(timeout=1.0)
    if received is None:
        print(f"no response for row :{row} , col:{col}")
        return None
    if len(received.data) < 8:
        print(f"short response for row:{row}, col:{col}: {received}")
        return None
    rx_val =  bytes(received.data[4:8])
    value = struct.unpack('f',rx_val)[0]
    print(f"row :{row} , col:{col} ,value:{value}")
    return True

def main():
    print("print r to read all parameters")
    choice = input("Enter choice : ")
    if choice == 'r':
        bus = connect_bus()
        try:
            want_to_read(bus)
        finally:
            if bus is not None:
                bus.shutdown()

    print("everything done")

if __name__ == "__main__":
    main()
