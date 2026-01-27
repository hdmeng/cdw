import socket
import json

def run_splitter(sock = None, listen_ip="0.0.0.0", listen_port=15007, targets=[("127.0.0.1", 15010)]
                 ):
    if sock is None:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.bind((listen_ip, listen_port))
        # print(f"Splitter running on {listen_port}. Forwarding to {targets}...")

    while True:
        message, address = sock.recvfrom(4096)
        
        message = json.loads(message.decode('utf-8'))
        
        wrapped_packet = {
            "original_ip": address[0],
            "original_port": address[1],
            "payload": message
        }
        wrapped_packet = json.dumps(wrapped_packet).encode('utf-8')     
           
        for target in targets:
            sock.sendto(wrapped_packet, target)
            

def forward_packet(sock, message, address, targets):
    for target in targets:
        data = json.loads(message.decode('utf-8'))
        
        wrapped_packet = {
            "original_ip": address[0],
            "original_port": address[1],
            "payload": data
        }
        sock.sendto(json.dumps(wrapped_packet).encode('utf-8'), target)
            

if __name__ == "__main__":
    run_splitter()