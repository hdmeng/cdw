# call snmpset to send the SpaT payload to RSU

import subprocess
import time
import logging
import json

# set socket for receiving udp packets
import socket   

should_stop = False
RSU_AUTH = "-t 2 -v 3 -l authPriv -a SHA512 -A XjXJ5wU@3 -x AES256 -X XjXJ5wU#3 -u rsp"
RSU_UDP = "udp:192.168.1.108:161" 
OID_ROOT = "1.3.6.1.4.1.1206.4.2.18"

# function to config RSU IFM
def start_ifm(payload):
    try:
        command = f"snmpset {RSU_AUTH} {RSU_UDP} \
            {OID_ROOT}.4.2.1.2.2 x 8002 \
            {OID_ROOT}.4.2.1.3.2 i 183 \
            {OID_ROOT}.4.2.1.4.2 i 1 \
            {OID_ROOT}.4.2.1.5.2 i 4 \
            {OID_ROOT}.4.2.1.6.2 i 6 \
            {OID_ROOT}.4.2.1.7.2 x 01 \
            {OID_ROOT}.4.2.1.8.2 x '{payload}' "
        
        print(f"Starting IFM ...")
        process = subprocess.Popen(command, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        result, error = process.communicate()
        if process.returncode != 0:
            raise Exception(f"Command failed: {error.strip()}")
    except Exception as e:
        logging.error(f"Error configuring RSU IFM: {e}")
        return False

def stop_ifm():
    try:
        command = f"snmpset {RSU_AUTH} {RSU_UDP} \
            {OID_ROOT}.4.2.1.2.2 x 8002 \
            {OID_ROOT}.4.2.1.3.2 i 183 \
            {OID_ROOT}.4.2.1.4.2 i 0 \
            {OID_ROOT}.4.2.1.5.2 i 6"
        print(f"Stopping IFM ...")
        process = subprocess.Popen(command, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        result, error = process.communicate()
        if process.returncode != 0:
            raise Exception(f"Command failed: {error.strip()}")
    except Exception as e:
        logging.error(f"Error configuring RSU IFM: {e}")
        return False

def send_ifm(payload):
    try:
        command = f"snmpset {RSU_AUTH} {RSU_UDP} \
            {OID_ROOT}.4.2.1.8.2 x {payload}"
        process = subprocess.Popen(command, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        result, error = process.communicate()
        if process.returncode != 0:
            raise Exception(f"Command failed: {error.strip()}")
    except Exception as e:
        logging.error(f"Error sending IFM: {e}")
        
def parse_ifm(buf, size=None):
    """
    Parse an Intermediate Format Message (IFM) from binary data.
    
    Args:
        buf (bytes or bytearray): Binary data containing the IFM message
        size (int, optional): Size of the data to parse. If None, uses the length of buf
    
    Returns:
        ifm: Dictionary containing the parsed IFM fields
    """
    if size is None:
        size = len(buf)
    
    # Convert binary data to string
    try:
        data_str = buf[:size].decode('utf-8')
    except UnicodeDecodeError:
        # Handle case where data isn't valid UTF-8
        return None
       
    # Initialize IFM structure
    ifm = {
        'PSID': '',
        'TxChannel': '',
        'Payload': ''
    }

    # Parse the data string into the IFM structure
    for line in data_str.split('\n'):
        key, value = line.split('=', 1)
        if key in ifm:
            ifm[key] = value.strip()

    return ifm

# function to receive udp packets from process spat.cpp
if __name__ == '__main__':
    # Create a UDP socket for receiving packets
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(('0.0.0.0', 15005))
    # create a UDP socket for sending packets
    sock_to_server = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock_to_server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
    
    stop_ifm()

    try:
        # receive udp packets from the socket
        sock.settimeout(1)  # Set a timeout for receiving packets
        data, addr = sock.recvfrom(1024)
        
        logging.info("Starting to receive UDP packets...")

        if len(data) != 0:
            # get IFM data from IEEE 1609.2 format
            msgDict = parse_ifm(data)
            # print(f"Received data from {addr}: {msgPayload['PSID']}")
            start_ifm(msgDict['Payload'])
        else:
            mockPayload = b'001300010001000100010001000100'  # Example payload, replace with actual data
            start_ifm(mockPayload)
    except Exception as e:
        logging.error(f"Error creating UDP socket: {e}")

    time.sleep(1)  # seconds

    while not should_stop:
        try:
            sock.settimeout(None)  # Blocking mode, will wait indefinitely for packets

            data, addr = sock.recvfrom(1024)
            if len(data) != 0:
                # get IFM data from IEEE 1609.2 format
                msgDict = parse_ifm(data)
                # print(f"Received data from {addr}: {msgPayload['PSID']}")
                send_ifm(msgDict['Payload'])
                # send the IFM to the server
                sock_to_server.sendto(json.dumps(msgDict).encode(), ('192.168.0.162', 15009))

        except Exception as e:
            logging.error(f"Error receiving UDP packets: {e}")

    sock.close()

