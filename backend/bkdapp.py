import threading
import asyncio
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi_socketio import SocketManager
import time
import socket
import sys
# Add the data-server directory to the Python path
sys.path.append('./data-server')
import mapParse as mpp
import dataParse as dap
import subprocess
import logging
import json
import uvicorn
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

app = FastAPI()

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

sio = SocketManager(app=app, cors_allowed_origins="*")

# Define the map center coordinates from env
map_center = {
    "lat": float(os.getenv('MAP_CENTER_LAT', 34.1054162)),
    "lng": float(os.getenv('MAP_CENTER_LNG', -118.2918061))
}

# Define the markers coordinates
markers = [
    {"lat": 34.105423, "lng": -118.291189}
    # Add more coordinates here
]

# Serve the API key
@app.get('/api/key')
async def get_api_key():
    return JSONResponse({"api_key": os.getenv('GOOGLE_MAPS_API_KEY')})

# Serve the map center coordinates
@app.get('/api/map_center')
async def get_map_center():
    return JSONResponse(map_center)

@app.get('/api/markers')
async def get_markers():
    return JSONResponse(markers)

# set the intersection list, having name and center for each intersection
intxn_list = []
maps_hex = {}
intxn_json = {}

# get the intersection list, e.g. /api/intxn_list?site=ECR
# returns the list of intersections for the given site
# return: [{"name": "intxn1", "center": {"lat": 34.1054162, "lng": -118.2918061}}, ...]
@app.get('/api/intxn_list')
async def get_intxns(site: str):
    global maps_hex, intxn_json
    if site == 'HLWD':
        # Read the MAP payload from the file
        maps_hex = mpp.read_mapsHex_from_file('maps/LA-Hollywood-55-hgt.payload')
    elif site == 'ECR':
        maps_hex = mpp.read_mapsHex_from_file('maps/ECR-Testbed-2025.payload')
    elif site == 'RFS':
        maps_hex = mpp.read_mapsHex_from_file('maps/RFS-Testbed.payload')    
    else:
        return JSONResponse({"error": "Invalid site parameter"}, status_code=400)

    intxn_list = []
    for intxn_name in maps_hex.keys():
        map_payload = maps_hex[intxn_name]
        intxn_json[intxn_name] = mpp.MessageFrame_payload_to_json(map_payload)
        intxn_center = mpp.get_intersection_center(intxn_json[intxn_name])
        intxn_list.append({"name": intxn_name, "center": intxn_center})
    return JSONResponse(intxn_list)

# set lanes for the given intersection
@app.post('/api/intxn_lanes')
async def get_intxn_lanes(request: Request):
    global maps_hex, intxn_json
    data = await request.json()
    post_name = data.get('name')
    if post_name in maps_hex.keys():
        all_lane_points = mpp.get_all_lanes(intxn_json[post_name], format='JSON', verbose=False)
        return JSONResponse(all_lane_points)
    else:
        return JSONResponse({"error": f"{post_name} not found"}, status_code=404)

# RSU configuration from env
#RSU_AUTH = os.getenv('RSU_AUTH', "-t 2 -v 3 -l authPriv -a SHA512 -A XjXJ5wU@3 -x AES256 -X XjXJ5wU#3 -u rsp")
RSU_AUTH = os.getenv('RSU_AUTH', "-t 2 -v 3 -l authPriv -a SHA512 -A Path$%@106 -x AES256 -X Path$%@106 -u datasvr")
OID_ROOT = os.getenv('OID_ROOT', "1.3.6.1.4.1.1206.4.2.18")
        
# get the equipment states of RCU, e.g. /api/rsu_state?rsnode=ecr-pgml
# return the Radio states 
@app.get('/api/rsu_state')
async def get_rsu_state(rsnode: str):
    # RSU_UDP = os.getenv('RSU_UDP', "udp:192.168.1.108:161")
    RSU_UDP = os.getenv('RSU_UDP', "udp:192.168.1.108:161")
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
        return JSONResponse(rsu_state)
    except Exception as e:
        return JSONResponse({"error": f"Failed to get RSU state: {str(e)}"}, status_code=500)
            

# Global termination flag
should_stop = threading.Event()

# Global variable to hold SPaT timings
spat_phases = []

# get Controller state, e.g. /api/tsc_state?rsnode=ecr-pgml
@app.get('/api/tsc_state')
async def get_controller_state(rsnode: str):
    global spat_phases
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
    return JSONResponse(spat_state)


# get Signal Phases and Timing upon incoming SPaT messages
def spat_update():
    global spat_phases

    listen_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    LISTEN_PORT = int(os.getenv('SPAT_LISTEN_PORT', 15009))
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
    
    # Clean up resources
    listen_socket.close()

# get MEC status
@app.get('/api/mec_state')
async def get_mec_status():
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
    return JSONResponse(mec_status)

# get message statistics
@app.get('/api/msg_stats')
async def get_msg_stats():
    # Return mock message statistics
    # In a real implementation, you would track actual message counts
    current_time = time.strftime("%H:%M:%S", time.localtime())
    msg_stats = [
        {"type": "BSM", "count": 1234, "last_received": current_time},
        {"type": "SPaT", "count": 567, "last_received": current_time},
        {"type": "MAP", "count": 89, "last_received": current_time},
        {"type": "TIM", "count": 45, "last_received": current_time}
    ]
    return JSONResponse(msg_stats)


# Update markers based on incoming UDP messages
async def marker_update_task():
    # Create a UDP socket for listening
    listen_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    LISTEN_PORT = int(os.getenv('MARKER_LISTEN_PORT', 17001))
    listen_socket.bind(('', LISTEN_PORT))

    while not should_stop.is_set():
        try:
            message, address = listen_socket.recvfrom(1024)  # Buffer size is 1024 bytes
            veh_pos = {}
            veh_pos['id'], markers[0]['lat'], markers[0]['lng'], veh_speed, veh_heading = mpp.parse_bsm(message)
            await sio.emit('marker_update', markers[0])
        except socket.timeout:
            # This is expected, just continue the loop
            continue
        except Exception as e:
            print(f"Error in marker update: {e}")

    # Clean up resources
    listen_socket.close()

def cleanup_bkgd_tasks(tasks):
    logging.info("Cleaning up background tasks...")
    
    # Signal tasks to stop
    should_stop.set()
    # Give tasks time to clean up
    time.sleep(2)
    # Reset the flag for next run
    should_stop.clear()

@app.on_event("startup")
async def startup_event():
    """Start background tasks when the app starts"""
    logging.info("Starting background tasks...")
    # Start SPaT update task in background
    threading.Thread(target=spat_update, daemon=True).start()
    # Uncomment if you want to start marker update task
    # asyncio.create_task(marker_update_task())

@app.on_event("shutdown")
async def shutdown_event():
    """Clean up when the app shuts down"""
    logging.info("Shutting down background tasks...")
    should_stop.set()

if __name__ == '__main__':
    
    # Configure logging for better error tracking
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
    
    # Get configuration from environment
    host = os.getenv('HOST', '0.0.0.0')
    port = int(os.getenv('PORT', 5000))
    
    while True:
        try:
            logging.info(f"Starting the FastAPI server on {host}:{port}...")
            
            # Run the server
            uvicorn.run(
                app,
                host=host,
                port=port
            )
                               
        except Exception as e:
            logging.error(f"An unexpected error occurred: {e}")
            # Wait before retrying
            logging.info("Retrying to start the server in 5 seconds...")
            time.sleep(5)  # Wait before retrying