# Data Reply through VM Server 

import socket
import os

if __name__ == '__main__':
    # Create a UDP socket for receiving packets
    sock_rx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    LISTEN_PORT = int(os.getenv('SPAT_LISTEN_PORT', 4520))
    sock_rx.bind(('', LISTEN_PORT))

    sock_tx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    while True:
        data, addr = sock_rx.recvfrom(1024)
        # print(f"Received message from {addr}: {data.decode()}")
        # Send a reply back to the client
        if len(data) != 0 :
            sock_rx.sendto(data, ('128.32.129.118', 4520))

