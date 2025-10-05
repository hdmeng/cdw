
# import matplotlib.pyplot as plt
import socket
import json
import pickle
from tabnanny import verbose
import argparse  # Import the argparse module

# Load the compiled ASN.1 specification from a file
with open('./J2735Common/pkl/j2735_spec_2.pkl', 'rb') as f:
    j2735_spec = pickle.load(f)

SigColor = {
    'protected-Movement-Allowed': 'Green',
    'stop-And-Remain': 'Red',
    'protected-clearance': 'Yellow',
    'permissive-Movement-Allowed': 'LightGreen'}

ColorMap = {'Green': '\033[92m', 'Red': '\033[91m', 'Yellow': '\033[93m', 'LightGreen': '\033[94m'}
ColorReset = '\033[0m'
            
def parse_ifm(data):

    payloadHex = data.get('Payload', '')
    return payloadHex

# Example: decode a UPER-encoded SPaT hex string
def decode_spat(hex_string, verbose=False):
    
    # Convert hex string to bytes
    byte_data = bytes.fromhex(hex_string)
    
    # Decode the SPaT message
    msgFrame_data = j2735_spec.decode('MessageFrame', byte_data)

    spat_data = j2735_spec.decode('SPAT', msgFrame_data.get('value'))

    # print(f"Decoded SPAT data: {spat_data}")

    # Extract timing for each signal group
    phases = []
    for intersection in spat_data['intersections']:
        for movement in intersection['states']:
            eventSigColor = SigColor.get(movement['state-time-speed'][0]['eventState'])
            if eventSigColor is None:
                eventSigColor = movement['state-time-speed'][0]['eventState']
                print(f"{eventSigColor}")
            phases.append({
                'signalGroup': movement['signalGroup'],
                'eventState': eventSigColor,
                'startTime': movement['state-time-speed'][0].get('timing', {}).get('startTime'),
                'minEndTime': movement['state-time-speed'][0].get('timing', {}).get('minEndTime')
            })
            #if movement['signalGroup'] == 1:
            # phases[movement['signalGroup']] = SigColor.get(movement['state-time-speed'][0]['eventState'])

        if verbose:
            secondLine = int(intersection.get('timeStamp') / 1000.0)
            print(f"{secondLine}", end='  ')

        for phase in phases:
            # Print the signal state without a line break
            color = ColorMap.get(phase['eventState'], '')

            if verbose :
                print(f"{color}{phase['signalGroup']}{ColorReset}", end=' ')
        if verbose :
            print('')  # New line 

    return phases

# function to parse the BSM message
def parse_bsm(payload, withMsgFrame=False):

    if withMsgFrame:
        # Decode the Message Frame payload using the ASN.1 specification
        decoded = j2735_spec.decode('MessageFrame', payload)
        bsm_value = decoded.get('value')
    else:
        bsm_value = payload    
    
    # Decode the BSM message using the ASN.1 specification
    decoded_bsm = j2735_spec.decode('BasicSafetyMessage', bsm_value)
    bsm_core = decoded_bsm.get('coreData')

    veh_pos = {}
    veh_pos['id'] = bsm_core.get('id') 
    veh_pos['lat'] = bsm_core.get('lat') / 10000000.0   # to degree
    veh_pos['long'] = bsm_core.get('long') / 10000000.0  # to degree
    veh_pos['speed'] = bsm_core.get('speed') * 0.02*3600/1609.34  # to mph
    veh_pos['heading'] = bsm_core.get('heading') * 0.0125  # to degree

    return veh_pos


# Visualize as a timeline 
# print phase 'G' for green, 'R' for red, 'Y' for yellow, in every 10 packets

if __name__ == '__main__':
    
    parser = argparse.ArgumentParser(description='Process MAP payload and draw intersection geometry.')
    parser.add_argument('-S', '--spat', action='store_true', help='Enable verbose output')
    parser.add_argument('-B', '--bsm', action='store_true', help='Enable figure plotting')
    args = parser.parse_args()
    
    # Create a UDP socket for receiving packets
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(('0.0.0.0', 4520))

    if args.bsm:
        with open('/home/path/la_atcmtd/bsmLog.log', 'rb') as f:
            for line in f:
                # Parse the BSM message from each line
                veh_id, veh_lat, veh_lon, veh_speed, veh_heading = parse_bsm(line)
                print(f"Vehicle ID: {veh_id}, Latitude: {veh_lat}, Longitude: {veh_lon}, Speed: {veh_speed}, Heading: {veh_heading}")

    if args.spat:
        tcnt = 0
        while True:
            data, addr = sock.recvfrom(1024)
            tcnt = (tcnt + 1) % 10
            if len(data) != 0 and tcnt == 1:
                json_data = json.loads(data.decode('utf-8'))
                # print(f"Received data from {addr}: {json_data.get('PSID')}")
            timing = decode_spat(json_data.get('Payload'), verbose=True)
            
