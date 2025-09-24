from flask import Flask, request, jsonify #, send_from_directory
from flask_cors import CORS     # CORS is needed to allow cross-origin requests
from flask_socketio import SocketIO, emit
import time
import socket
import mapParse as mpp

app = Flask(__name__)
CORS(app)
socketio = SocketIO(app, cors_allowed_origins="*")

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
@app.route('/api/test', methods=['GET'])
def get_api_key():
    return jsonify({"test": "AIzaSyAL3C-ABJFAXoCjrbAUVrEcBnIMegajL7M"})

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


def update_marker():
    
    # Create a UDP socket for listening
    listen_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    LISTEN_PORT = 17001
    listen_socket.bind(('', LISTEN_PORT))

    cnt = 0
    veh_pos = {}
    while True:

        # Receive message from the listening socket
        message, address = listen_socket.recvfrom(1024)  # Buffer size is 1024 bytes

        veh_pos['id'], markers[0]['lat'], markers[0]['lng'], veh_speed, veh_heading = mpp.parse_bsm(message)
        if False:
            print(f"loc: {markers[0]['lat']}")   

        socketio.emit('marker_update', markers[0])

if __name__ == '__main__':
    socketio.start_background_task(update_marker)
    socketio.run(app, host='0.0.0.0', port=5000, ssl_context=('conf/auth/cert.pem', 'conf/auth/key.pem'))