import threading
from flask import Flask, request, jsonify #, send_from_directory
from flask_cors import CORS     # CORS is needed to allow cross-origin requests
from flask_socketio import SocketIO, emit
import time
import socket
import mapParse as mpp
import sys
sys.path.append('/home/cdw/data-server')
import dataParse as dap
import subprocess
import logging
import json

app = Flask(__name__)
CORS(app)
socketio = SocketIO(app, cors_allowed_origins="*")
#CORS(app, resources={r"/*": {"origins": ["http://127.0.0.1", "http://128.32.129.118"]}})
#socketio = SocketIO(app, cors_allowed_origins=["http://127.0.0.1", "http://128.32.129.118"], ssl_verify=False)

# Define the map center coordinates
map_center = {
    "lat": 34.1054162,
    "lng": -118.2918061
}

# Define the markers coordinates
markers = [
    {"lat": 34.105423, "lng": -118.291189}
    # Add more coordinates here
]

net_config = {
    "server_url": "http://127.0.0.1",
    "server_port": 5000,
    "socket_port": 5000
}

# Serve the netconfig.json file
@app.route('/config/netconfig', methods=['GET'])
def get_config():
    return jsonify(net_config)

# Serve the API key
@app.route('/api/key', methods=['GET'])
def get_api_key():
    return jsonify({"api_key": "AIzaSyAL3C-ABJFAXoCjrbAUVrEcBnIMegajL7M"})

# Serve the map center coordinates
@app.route('/api/map_center', methods=['GET'])
def get_map_center():
    return jsonify(map_center)

@app.route('/api/markers', methods=['GET'])
def get_markers():
    return jsonify(markers)

# set the intersection list, haivng name and center for each intersection
intxn_list = []
maps_hex = {}
intxn_json = {}

# get the intersection list, e.g. /api/intxn_list?site=ECR
# returns the list of intersections for the given site
# return: [{"name": "intxn1", "center": {"lat": 34.1054162, "lng": -118.2918061}}, ...]
@app.route('/api/intxn_list', methods=['GET'])
def get_intxns():
    global maps_hex, intxn_json
    site = request.args.get('site')
    if site == 'HLWD':
        # Read the MAP payload from the file
        maps_hex = mpp.read_mapsHex_from_file('maps/LA-Hollywood-55-hgt.payload')
    elif site == 'ECR':
        maps_hex = mpp.read_mapsHex_from_file('maps/ECR-Testbed-2025.payload')
    elif site == 'RFS':
        maps_hex = mpp.read_mapsHex_from_file('maps/RFS-Testbed.payload')    
    else:
        return jsonify({"error": "Invalid site parameter"}), 400

    intxn_list = []
    for intxn_name in maps_hex.keys():
        map_payload = maps_hex[intxn_name]
        intxn_json[intxn_name] = mpp.MessageFrame_payload_to_json(map_payload)
        intxn_center = mpp.get_intersection_center(intxn_json[intxn_name])
        intxn_list.append({"name": intxn_name, "center": intxn_center})
    return jsonify(intxn_list)

# set lanes for the given intersection
@app.route('/api/intxn_lanes', methods=['POST'])
def get_intxn_lanes():
    global maps_hex, intxn_json
    data = request.get_json()
    post_name = data.get('name')
    if post_name in maps_hex.keys():
        all_lane_points = mpp.get_all_lanes(intxn_json[post_name], format='JSON', verbose=False)
        return jsonify(all_lane_points)
    else:
        return jsonify({"error": f"{post_name} not found"}), 404

RSU_AUTH = "-t 2 -v 3 -l authPriv -a SHA512 -A XjXJ5wU@3 -x AES256 -X XjXJ5wU#3 -u rsp"
OID_ROOT = "1.3.6.1.4.1.1206.4.2.18"
        
# get the equipment states of RCU, e.g. /api/rsu_state?rsnode=ecr-pgml
# return the Radio states 
@app.route('/api/rsu_state', methods=['GET'])
def get_rsu_state():
    rsnode = request.args.get('rsnode')
    RSU_UDP = "udp:192.168.1.108:161"
    try:
        command = f"snmpget {RSU_AUTH} {RSU_UDP} {OID_ROOT}.1.2.1.2.3"
        process = subprocess.Popen(command, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        result, error = process.communicate()
        if process.returncode != 0:
            raise Exception(f"Command failed: {error.strip()}")
        command = f"snmpget {RSU_AUTH} {RSU_UDP} {OID_ROOT}.1.2.1.3.3"
        process = subprocess.Popen(command, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        result2, error = process.communicate()
        if process.returncode != 0:
            raise Exception(f"Command failed: {error.strip()}")
            
        current_time = time.strftime("%H:%M:%S", time.localtime()) + f".{int(time.time() * 1000) % 1000:03d}"
        rsu_state = {
            "time_msec": current_time,
            "radio_mode": result.strip().split()[-1],
            "radio_enable": result2.strip().split()[-1]
        }
        return jsonify(rsu_state)
    except Exception as e:
        return jsonify({"error": f"Failed to get RSU state: {str(e)}"}), 500
            

# Global termination flag
should_stop = threading.Event()

# Global variable to hold SPaT timings
spat_phases = []

# get Controller state, e.g. /api/tsc_state?rsnode=ecr-pgml
@app.route('/api/tsc_state', methods=['GET'])
def get_controller_state():
    global spat_phases
    rsnode = request.args.get('rsnode')
    sig_state = ['R','R','R','R','R','R','R','R','R','R','R','R','R','R','R','R','R']  # Default signal states
    for phase in spat_phases:
        # print(f"SPaT Phase: {phase}")
        sig_state[phase['signalGroup']] = phase['eventState'] 
    
    spat_state = {
        "Ph2": sig_state[2], "Ph4": sig_state[4],
        "Ph6": sig_state[6], "Ph8": sig_state[8],
        "Ph10": sig_state[10], "Ph12": sig_state[12],
        "Ph14": sig_state[14], "Ph16": sig_state[16]
    }
    return jsonify(spat_state), 200


# get Signal Phases and Timing upon incoming SPaT messages
def spat_update():
    global spat_phases

    listen_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    LISTEN_PORT = 15009
    listen_socket.bind(('', LISTEN_PORT))

    while not should_stop.is_set():
        try:
            message, address = listen_socket.recvfrom(1024)  # Buffer size is 1024 bytes
            json_data = json.loads(message.decode('utf-8'))
            # Check if the message contains SPaT data
            if (json_data.get('PSID') == "8002") :
                # Process the incoming SPaT message
                spat_phases = dap.decode_spat(json_data.get('Payload'), verbose=False)

        except Exception as e:
            print(f"Error in SPaT update: {e}")

# get MEC status
@app.route('/api/mec_state', methods=['GET'])
def get_mec_status():
    # Implement your logic to retrieve MEC status
    mec_status = {
        "Status": "active", 
        "SiteName": "RFS-coin",
        "OprFuncs": {
            "MrpSpat": "Active",
            "MrpAware": "Inactive",
            "MsgFwd": "Active",
            "Tci": "Inactive",
            "DataMgr": "Inactive",
            "Sensor": "Inactive",
            "RTCM": "Inactive"
        }
    }
    return jsonify(mec_status)


# Update markers based on incoming UDP messages
def marker_update_task():
    # Create a UDP socket for listening
    listen_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    LISTEN_PORT = 17001
    listen_socket.bind(('', LISTEN_PORT))

    while not should_stop.is_set():
        try:
            message, address = listen_socket.recvfrom(1024)  # Buffer size is 1024 bytes
            veh_pos = {}
            veh_pos['id'], markers[0]['lat'], markers[0]['lng'], veh_speed, veh_heading = mpp.parse_bsm(message)
            socketio.emit('marker_update', markers[0])
        except socket.timeout:
            # This is expected, just continue the loop
            continue
        except Exception as e:
            print(f"Error in marker update: {e}")

    # Clean up resources
    listen_socket.close()

# def rsu_state_task():
#     while not should_stop.is_set():
#         try:
#             socketio.emit('rsu_state', rsu_state)
#         except Exception as e:
#             print(f"Error in RSU state update: {e}")
#         time.sleep(5)

def cleanup_bkgd_tasks(tasks):
    logging.info("Cleaning up background tasks...")
    
    # Signal tasks to stop
    should_stop.set()
    # Give tasks time to clean up
    time.sleep(2)
    # Reset the flag for next run
    should_stop.clear()

if __name__ == '__main__':
    
    # socketio.start_background_task(marker_update_task)
    # socketio.start_background_task(rsu_state_task)
    # socketio.run(app, host='0.0.0.0', port=5000, ssl_context=('conf/auth/cert.pem', 'conf/auth/key.pem'))
    
    # Configure logging for better error tracking
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
    
    # Keep track of background tasks
    background_tasks = []
    
    while True:
        try:
            logging.info("Starting the SocketIO server...")
            
            # Start background tasks and keep track of them
            # marker_task = socketio.start_background_task(marker_update_task)
            # rsu_task = socketio.start_background_task(rsu_state_task)
            spat_task = socketio.start_background_task(spat_update)
            
            background_tasks = [spat_task] #marker_task ,rsu_task
            
            # Run the server
            socketio.run(app, host='0.0.0.0', port=5000, 
                        ssl_context=('conf/auth/cert.pem', 'conf/auth/key.pem'))
                               
        except Exception as e:
            logging.error(f"An unexpected error occurred: {e}")
            # Clean up background tasks
            cleanup_bkgd_tasks(background_tasks)
            # stop the server and wait before retrying
            socketio.stop()

            logging.info("Retrying to start the server in 5 seconds...")
            time.sleep(5)  # Wait before retrying
