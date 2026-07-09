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
import xml.etree.ElementTree as ET
from pathlib import Path
from functools import lru_cache
from datetime import datetime, timedelta

# Add the data-server directory to the Python path
sys.path.append('./data-server')
import mapParse as mpp
import dataParse as dap
import driveFilter

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

DRIVE_SOURCE_PATH = Path(__file__).resolve().parent.parent / 'maps' / 'xml' 
DRIVE_ORG_FILE = 'Get_Drives_All.json'
DRIVE_FILTERED_FILE = 'Filtered_Get_Drives.json'
DRIVE_WINDOW_MINUTES = driveFilter.DEFAULT_WINDOW_MINUTES

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
        intxn_id = intxn_json[intxn_name].get('id', {}).get('id', 'unknown')
        intxn_center = mpp.get_intersection_center(intxn_json[intxn_name])
        intxn_list.append({"name": intxn_name, "id": intxn_id, "center": intxn_center})
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
        map_payload_rev, _ = mpp.MAP_json_to_payload(map_json_raw, True)
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


@lru_cache(maxsize=1)
def load_viz_cameras():
    camera_file = Path(__file__).resolve().parent.parent / 'maps' / 'xml' / 'CamerasInPolygon.xml'

    if not camera_file.exists():
        raise FileNotFoundError('Camera XML not found')

    tree = ET.parse(camera_file)
    root = tree.getroot()
    namespace = {'cam': 'http://tempuri.org/DataSetCameras.xsd'}

    cameras = []
    for camera_node in root.findall('.//cam:Cameras', namespace):
        lat_text = camera_node.findtext('cam:Latitude', default='', namespaces=namespace)
        lng_text = camera_node.findtext('cam:Longitude', default='', namespaces=namespace)

        try:
            lat = float(lat_text)
            lng = float(lng_text)
        except (TypeError, ValueError):
            continue

        cameras.append({
            'camera_id': camera_node.findtext('cam:CameraID', default='', namespaces=namespace),
            'region_id': camera_node.findtext('cam:RegionID', default='', namespaces=namespace),
            'name': camera_node.findtext('cam:Name', default='Unnamed camera', namespaces=namespace),
            'lat': lat,
            'lng': lng,
            'view': camera_node.findtext('cam:View', default='', namespaces=namespace),
            'closest_lane': camera_node.findtext('cam:ClosestLane', default='', namespaces=namespace),
            'marker_post': camera_node.findtext('cam:MarkerPost', default='', namespaces=namespace),
            'stream_url': camera_node.findtext('cam:StreamWebAddress', default='', namespaces=namespace),
            'stream_url_2': camera_node.findtext('cam:StreamWebAddress2', default='', namespaces=namespace),
            'out_of_service': camera_node.findtext('cam:DetectedOutOfService', default='false', namespaces=namespace).lower() == 'true',
        })

    return cameras


@lru_cache(maxsize=1)
def load_viz_drives():
    drive_file = DRIVE_SOURCE_PATH / DRIVE_FILTERED_FILE

    if not drive_file.exists():
        raise FileNotFoundError('Drive trajectory JSON not found')

    with drive_file.open('r', encoding='utf-8') as handle:
        drive_data = json.load(handle)

    trajectories = []
    time_values = []
    for feature in drive_data.get('features', []):
        coordinates = feature.get('geometry', {}).get('coordinates', [])
        if len(coordinates) < 2:
            continue

        points = []
        for lng, lat in coordinates:
            points.append({'lat': lat, 'lng': lng})

        properties = feature.get('properties', {})
        time_value = properties.get('Time')
        if time_value:
            time_values.append(time_value)
        trajectories.append({
            'vehicle_id': properties.get('VehicleId'),
            'speed': properties.get('Speed'),
            'heading': properties.get('Heading'),
            'seconds': properties.get('Seconds'),
            'time': time_value,
            'online': properties.get('Online'),
            'points': points,
        })

    unique_vehicle_ids = {traj['vehicle_id'] for traj in trajectories if traj.get('vehicle_id') is not None}

    return {
        'trajectories': trajectories,
        'summary': {
            'trajectory_count': len(trajectories),
            'vehicle_count': len(unique_vehicle_ids),
            'time_start': min(time_values) if time_values else None,
            'time_end': max(time_values) if time_values else None,
            'source_file': drive_file.name,
        }
    }


def load_viz_drive_source_bounds():
    return driveFilter.DEFAULT_SOURCE_TIME_RANGE


def build_drive_window(start_time_text=None):
    source_bounds = load_viz_drive_source_bounds()
    default_start = source_bounds.get('start')
    selected_start = start_time_text or default_start
    if not selected_start:
        raise ValueError('Drive source time range is unavailable')

    start_dt = datetime.fromisoformat(selected_start.replace('Z', '+00:00'))
    end_dt = start_dt + timedelta(minutes=DRIVE_WINDOW_MINUTES)
    selected_end = end_dt.isoformat(timespec='milliseconds').replace('+00:00', 'Z')

    source_end = source_bounds.get('end')
    if source_end and selected_end > source_end:
        selected_end = source_end

    return {
        'start': selected_start,
        'end': selected_end,
    }


def refresh_viz_drives(start_time_text=None):
    window = build_drive_window(start_time_text)
    # get the date from the start time
    filter_date = window['start'].split('T')[0]
    driveFilter.filter_drive_data(
        str(DRIVE_SOURCE_PATH / f"BayArea_{filter_date}_{DRIVE_ORG_FILE}"),
        str(DRIVE_SOURCE_PATH / DRIVE_FILTERED_FILE),
        driveFilter.DEFAULT_FILTER_LOC_BOX,
        window,
        max_features=None,
    )
    load_viz_drives.cache_clear()
    return window


@app.get('/api/viz_cameras')
async def get_viz_cameras():
    try:
        return JSONResponse(load_viz_cameras())
    except FileNotFoundError:
        return JSONResponse({"error": "Camera XML not found"}, status_code=404)
    except ET.ParseError as exc:
        return JSONResponse({"error": f"Failed to parse camera XML: {exc}"}, status_code=500)


@app.get('/api/viz_drives')
async def get_viz_drives(reload: bool = False, start_time: str | None = None):
    try:
        source_bounds = load_viz_drive_source_bounds()
        window = None
        if reload or start_time:
            window = refresh_viz_drives(start_time)

        drive_payload = load_viz_drives()
        drive_payload['summary']['window_minutes'] = DRIVE_WINDOW_MINUTES
        drive_payload['summary']['available_time_start'] = source_bounds.get('start')
        drive_payload['summary']['available_time_end'] = source_bounds.get('end')
        drive_payload['summary']['selected_time_start'] = window['start'] if window else drive_payload['summary'].get('time_start')
        drive_payload['summary']['selected_time_end'] = window['end'] if window else drive_payload['summary'].get('time_end')
        return JSONResponse(drive_payload)
    except FileNotFoundError:
        return JSONResponse({"error": "Drive trajectory JSON not found"}, status_code=404)
    except json.JSONDecodeError as exc:
        return JSONResponse({"error": f"Failed to parse drive trajectory JSON: {exc}"}, status_code=500)
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)

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
            map_payload_rev, dupl_lanes = mpp.MAP_json_to_payload(map_json_raw, elim_dupl_lanes=True)
            
            return JSONResponse({
                "map_payload_org": map_payload.hex().upper(),
                "map_payload_org_size": len(map_payload),
                "map_payload_rev": map_payload_rev.hex().upper(),
                "map_payload_rev_size": len(map_payload_rev),
                "map_json": map_json,
                "duplicate_lanes": dupl_lanes,
            })
        except Exception as e:
            return JSONResponse({"error": f"Failed to process payload: {str(e)}"}, status_code=500)
            
    except Exception as e:
        return JSONResponse({"error": f"Invalid request: {str(e)}"}, status_code=400)

# RSU configuration from env
#RSU_AUTH = os.getenv('RSU_AUTH', "-t 2 -v 3 -l authPriv -a SHA512 -A XjXJ5wU@3 -x AES256 -X XjXJ5wU#3 -u rsp")
RSU_AUTH = os.getenv('RSU_AUTH', "-t 2 -v 3 -l authPriv -a SHA512 -A Path$%@106 -x AES256 -X Path$%@106 -u datasvr")
OID_ROOT = os.getenv('OID_ROOT', "1.3.6.1.4.1.1206.4.2.18")
        
# get the equipment states of RCU, e.g. /api/rsu_state?nodeid=ecr-pgml
# return the Radio states 
@app.get('/api/rsu_state')
def get_rsu_state(nodeid: str):
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
spat_phases = {}

# get Controller state based on SPaT updates, e.g. /api/tsc_state?rsnode=ecr-pgml
@app.get('/api/tsc_state')
def get_controller_state(intxnid: int):
    global spat_phases
    sig_state = ['G','R','R','R','R','R','R','R'
            ,'R','R','R','R','R','R','R','R','R']  # Default signal states
    
    spat_state = {}
    phases = spat_phases[intxnid] if intxnid in spat_phases else []
    for phase in phases:
        # print(f"SPaT Phase: {phase}")
        sig_state[phase['signalGroup']] = phase['eventState'] 
        spat_state[str(phase['signalGroup'])] = sig_state[phase['signalGroup']]
        
    return JSONResponse(spat_state)


# get Signal Phases and Timing upon incoming SPaT messages
def spat_update():
    global spat_phases, data_1609

    # Create a UDP socket for listening
    listen_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    LISTEN_PORT = int(os.getenv('SPAT_LISTEN_PORT', 15008))
    listen_socket.bind(('', LISTEN_PORT))

    while not should_stop.is_set():
        try:
            message, address = listen_socket.recvfrom(1024)  # Buffer size is 1024 bytes
            data_1609 = json.loads(message.decode('utf-8'))
            # Check if the message contains SPaT data
            if (data_1609.get('PSID') == "8002") :
                # forward the messages to a minotoring port for debugging
                # forward_packet(listen_socket, message, address, [("127.0.0.1", 15010)]) 
                # Process the incoming SPaT message
                spat_ph = dap.decode_spat(data_1609.get('Payload'), data_1609.get('Spat1_mess'), verbose=False)
                # append diffrent intersectin id to the spat_phases
                #for intersection_id, phases in spat_phases.items():
                spat_phases[spat_ph['id'].get('id')] = spat_ph['phases']
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
@app.get('/api/rsp_install')
def set_rsp_install():
    
    # set RSP connection status by pinging the RSP
    try:
        command = "sh rsp_install.sh"  # 
        process = subprocess.Popen(command, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        
        result, error = process.communicate()
    except Exception as e:
        rsp_installed = False    # 
   

# get RSP status
@app.get('/api/rsp_state')
def get_rsp_status(nodeid: str):
    # get RSP connection status by pinging the RSP
    try:
        # Implement your logic to check RSP connection
        # Ping RSP to check connection
        command = "ping -c 1 -W 2 192.168.1.108"  # Adjust IP as needed
        process = subprocess.Popen(command, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        result, error = process.communicate()
        rsp_connected = process.returncode == 0
    except Exception as e:
        rsp_connected = False

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