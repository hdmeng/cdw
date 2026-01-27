import threading
import asyncio
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi_socketio import SocketManager

import time
import socket
import sys
import subprocess
import logging
import json
import uvicorn
import os
from dotenv import load_dotenv
import base64

# Add the data-server directory to the Python path
sys.path.append('./data-server')
import mapParse as mpp
import dataParse as dap

from port_split import run_splitter as port_split

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

#sio = SocketManager(app=app, cors_allowed_origins="*", mount_location="/ws", socketio_path="socket.io")
#sio = SocketManager(app=app, cors_allowed_origins="*")
sio = SocketManager(app=app, cors_allowed_origins="http://128.32.129.118:5000")

# Define the map center coordinates from env
# map_center = {
#     "lat": float(os.getenv('MAP_CENTER_LAT', 34.1054162)),
#     "lng": float(os.getenv('MAP_CENTER_LNG', -118.2918061))
# }

# Define the markers coordinates
markers = [
    # {"lat": 34.105423, "lng": -118.291189},  # another place @ Hollywood
    {"lat": 34.094408, "lng": -118.330568},  # Cole PI @ Hollywood
    {"lat": 37.439616, "lng": -122.162708},  # Medical @ ECR
    {"lat": 37.915572, "lng": -122.334873},  # COIN @ RFS
    # Add more coordinates here
]

# Serve the API key
@app.get('/api/key')
async def get_api_key():
    return JSONResponse({"api_key": os.getenv('GOOGLE_MAPS_API_KEY')})

# Serve the map center coordinates
@app.get('/api/map_center')
async def get_map_center(site: str):
    if site == 'HLWD':
        # Read the MAP payload from the file
        map_center = markers[0]
    elif site == 'ECR':
        map_center = markers[1]
        #map_center = {"lat": float(os.getenv('MAP_CENTER_LAT', 37.439616)),
        #             "lng": float(os.getenv('MAP_CENTER_LNG', -122.162708))}
    elif site == 'RFS':
        map_center = markers[2]
    else:
        return JSONResponse({"error": "Invalid site parameter"}, status_code=400)

    return JSONResponse(map_center)

@app.get('/api/markers')
async def get_markers():
    return JSONResponse(markers[0])

# set the intersection list, having name and center for each intersection
intxn_list = []
maps_hex = {}
intxn_json = {}

# get the intersection list, e.g. /api/intxn_list?site=ECR
# returns the list of intersections for the given site
# return: [{"name": "intxn1", "center": {"lat": 34.1054162, "lng": -118.2918061}}, ...]
@app.get('/api/intxn_list')
async def get_intxns(site: str):
    global maps_hex, intxn_json, maps_hex_interim
    if site == 'HLWD':
        # Read the MAP payload from the file
        maps_hex = mpp.read_mapsHex_from_file('maps/LA-Hollywood-55-hgt.payload')
    elif site == 'ECR':
        maps_hex = mpp.read_mapsHex_from_file('maps/ECR-Testbed-2025.payload')
        maps_hex_interim = mpp.read_mapsHex_from_file('maps/D4-ECR_interim.payload')
    elif site == 'RFS':
        maps_hex = mpp.read_mapsHex_from_file('maps/RFS-Testbed.payload')    
    else:
        return JSONResponse({"error": "Invalid site parameter"}, status_code=400)

    intxn_list = []
    for intxn_name in maps_hex.keys():
        map_payload = maps_hex[intxn_name]
        _, _, intxn_json[intxn_name] = mpp.MAP_payload_to_json(map_payload)
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

# get the map files for the given intersection
@app.get('/api/mapfiles')
async def get_map_files(intxn: str):
    # read the MAP payload from the file /home/cdw/data-server/maps/D4-ECR_interim.payload
    global maps_hex_interim
    if intxn in maps_hex_interim.keys():
        map_payload = maps_hex_interim[intxn]
        map_payload_hex = map_payload.hex().upper()
        map_payload_str = ' '.join(map_payload_hex[i:i+2] for i in range(0, len(map_payload_hex), 2))
        map_json_raw, map_json, _ = mpp.MAP_payload_to_json(map_payload)
        # eliminate duplicate lanes and convert back to payload
        map_payload_rev = mpp.MAP_json_to_payload(map_json_raw, True)
        return JSONResponse({
            "map_payload_bytes": map_payload_str,
            "map_json": map_json,
            "map_payload": map_payload_hex,
            "map_payload_len": len(map_payload),
            "map_payload_rev": map_payload_rev.hex().upper(),
            "map_payload_rev_len": len(map_payload_rev),
        })
    else:
        return JSONResponse({"error": f"{intxn} not found"}, status_code=404)
    
# Add this endpoint to serve JSON map files
@app.get("/download/{filename}")
async def download_file(filename: str):
    """Serve JSON map files from the maps/json directory"""
    file_path = f"/home/cdw/maps/json/{filename}"
    if os.path.exists(file_path):
        headers = {"Content-Disposition": f"attachment; filename={filename}"}
        return FileResponse(file_path, headers=headers)
    else:
        return JSONResponse({"error": "File not found"}, status_code=404)

# procee map payload upload and return the revied MAP JSON and payload
@app.post('/api/process_map_payload')
async def process_map_payload(request: Request):
    try:
        data = await request.json()
        filename = data.get('filename')
        base64_content = data.get('content')
        
        if not base64_content:
            return JSONResponse({"error": "No content provided"}, status_code=400)
        
        # Decode base64 to bytes
        content = base64.b64decode(base64_content)
      
        # Process the payload (your existing logic)
        try:
            # Assume the uploaded file contains hex string
            hex_string = content.decode('utf-8').replace('\n', '').replace(' ', '')
            map_payload = bytes.fromhex(hex_string)
            
            # Convert payload to JSON
            map_json_raw, map_json, _ = mpp.MAP_payload_to_json(map_payload)
            
            # Eliminate duplicate lanes and convert back to payload
            map_payload_rev = mpp.MAP_json_to_payload(map_json_raw, elim_dupl_lanes=True)
            
            return JSONResponse({
                "map_payload_rev": map_payload_rev.hex().upper(),
                "map_payload_rev_size": len(map_payload_rev),
                "map_json": map_json,
            })
        except Exception as e:
            return JSONResponse({"error": f"Failed to process payload: {str(e)}"}, status_code=500)
            
    except Exception as e:
        return JSONResponse({"error": f"Invalid request: {str(e)}"}, status_code=400)

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

# get Controller state based on SPaT updates, e.g. /api/tsc_state?rsnode=ecr-pgml
@app.get('/api/tsc_state')
async def get_controller_state(rsnode: str):
    global spat_phases
    sig_state = ['G','R','R','R','R','R','R','R'
            ,'R','R','R','R','R','R','R','R','R']  # Default signal states
    
    spat_state = {}
    for phase in spat_phases:
        # print(f"SPaT Phase: {phase}")
        sig_state[phase['signalGroup']] = phase['eventState'] 
        spat_state[str(phase['signalGroup'])] = sig_state[phase['signalGroup']]
        
    # {    "Ph2": sig_state[2], "Ph4": sig_state[4],
    #     "Ph6": sig_state[6], "Ph8": sig_state[8],
    #     "Ph10": sig_state[10], "Ph12": sig_state[12],
    #     "Ph14": sig_state[14], "Ph16": sig_state[16]
    # }
    return JSONResponse(spat_state)


# get Signal Phases and Timing upon incoming SPaT messages
def spat_update():
    global spat_phases, data_1609

    # Create a UDP socket for listening
    listen_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    LISTEN_PORT = int(os.getenv('SPAT_LISTEN_PORT', 15009))
    listen_socket.bind(('', LISTEN_PORT))

    while not should_stop.is_set():
        try:
            message, address = listen_socket.recvfrom(1024)  # Buffer size is 1024 bytes
            data_1609 = json.loads(message.decode('utf-8'))
            # Check if the message contains SPaT data
            if (data_1609.get('PSID') == "8002") :
                # forward to another port for database logging if needed
                port_split(listen_socket, targets=[("127.0.0.1", 15010)])
                
                # Process the incoming SPaT message
                spat_phases = dap.decode_spat(data_1609.get('Payload'), data_1609.get('Spat1_mess'), verbose=False)
        except Exception as e:
            print(f"Error in SPaT update: {e}")
    
    # Clean up resources
    listen_socket.close()

# get the exampled spat files for the given intersection
@app.get('/api/spatfiles')
async def get_spat_files(intxn: str):
    # read the MAP payload from the file /home/cdw/data-server/maps/D4-ECR_interim.payload
    global spat_phases, data_1609
    spat_payload = data_1609.get('Payload')
    spat_payload_str = ' '.join(spat_payload[i:i+2] for i in range(0, len(spat_payload), 2))
    spat_json = spat_phases
    return JSONResponse({
        "spat_payload_bytes": spat_payload_str,
        "spat_json": spat_json,
    })
    

# get RSP status
@app.get('/api/rsp_state')
async def get_rsp_status():

    # Implement your logic to retrieve RSP status
    rsp_status = {
        "Status": "active",
        "Connection": "connected",
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
    return JSONResponse(rsp_status)

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

# get detector loop positions for the given intersections
@app.get('/api/intxn_loops')
async def get_detector_loop_positions(site: str):
    # retrieve detector loop positions
    # loop_positions = [
    #     {"id": "501A", "position": "B1", "lat": 34.094381, "lng": -118.330265},
    #     {"id": "503R", "position": "B2", "lat": 34.094372, "lng": -118.331398},
    #     {"id": "503A", "position": "B3", "LatLng": {"lat": 34.094320, "lng": -118.331854}},
    #     {"id": "504R", "position": "B4", "LatLng": {"lat": 34.094328, "lng": -118.330512}}
    # ]
    if site == 'HLWD':
        # Read the MAP payload from the file
        detc_file = 'maps/Fountain-Ave-Detectors.csv'   
    else:
        return JSONResponse({"error": "Invalid site parameter"}, status_code=400)

    loop_positions = mpp.get_detector_pos(detc_file)

    return JSONResponse(loop_positions)


# get vehicle locations based on BSM updates, e.g. /api/veh_loc?vehid=02405
@app.get('/api/veh_loc')
async def get_vehicle_location(vehid: int):
    global fleet_pos
    # Just return the last known vehicle position for the given ID
    if vehid in fleet_pos:
        return JSONResponse(fleet_pos[vehid])
    else:
        return JSONResponse({"error": "Vehicle not found"}, status_code=404)


# Update markers based on incoming UDP messages
async def bsm_update_task(BSM_RAW=False):
    #loop = asyncio.get_running_loop()
    # Create a UDP socket for listening
    listen_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    LISTEN_PORT = int(os.getenv('BSM_LISTEN_PORT', 17001))
    listen_socket.bind(('', LISTEN_PORT))
    listen_socket.setblocking(False)  # Important for async operation

    global fleet_pos
    fleet_pos = {}  # Dictionary to hold positions of all vehicles
    message = None
    while not should_stop.is_set():
        try:
            # Use asyncio to handle non-blocking socket operations
            try:
                message, address = listen_socket.recvfrom(1024)
            except BlockingIOError:
                await asyncio.sleep(0.01)  # Small delay to prevent CPU spinning
                continue
            veh_pos = {}
            
            try:
                if BSM_RAW:
                    # parse J2735 raw BSM message
                    veh_pos = mpp.parse_bsm(message, withMsgFrame=True)
                else:
                    # parse processing result message in Tuple format
                    # sending message: str(veh_pos).encode('utf-8')
                    veh_pos = eval(message.decode('utf-8'))
                    # print(f"{veh_pos['id']}", end="", flush=True)

            except Exception as e:
                # print(f"Error parsing BSM: {e}")
                continue

            # Emit the updated vehicle position to all connected clients
            if len(veh_pos) > 0:
                # convert the vehicle ID hex to an integer for indexing
                # tmpid = int(veh_pos['id'][2:4].hex(), 16)
                tmpid = veh_pos['id']
                # print(f"veh: {tmpid}", end=' ')
                # update fleet_pos for the vehicle ID in the message
                # having all the vehicle attributes in fleet_pos
                fleet_pos[tmpid] = veh_pos
                # await sio.emit('veh_update', veh_pos)
        except socket.timeout:
            # This is expected, just continue the loop
            continue
        except Exception as e:
            print(f"Error in vehicle update: {e}")

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
    asyncio.create_task(bsm_update_task())

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
            
            # Run the server for http and websocket
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