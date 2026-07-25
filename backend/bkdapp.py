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
import csv
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

DRIVE_SOURCE_PATH = Path(__file__).resolve().parent.parent / 'maps' / 'vizz' 
DRIVE_ORG_FILE = 'Get_Drives_All.json'
DRIVE_FILTERED_FILE = 'BayArea_Get_Drives'
PASS_FILTERED_FILE = 'BayArea_Grid_Passes'
DRIVE_WINDOW_MINUTES = driveFilter.DEFAULT_WINDOW_MINUTES
DRIVE_WINDOW_OPTIONS = [30, 60, 180, 360, 720, 1440]
DRIVE_HEATMAP_RADIUS_METERS = driveFilter.DEFAULT_GRID_PASS_RADIUS_METERS
DRIVE_GRID_FILE = 'BayArea_Grid.json'
IMAGE_DATA_PATH = Path(__file__).resolve().parent.parent / 'image-data'
IMAGE_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.webp'}
MAX_IMAGE_OFFSET = 180
MAX_IMAGE_RESULTS = 30
NHS_GEOJSON_FILES = {
    'interstate_nisr': Path(__file__).resolve().parent.parent / 'maps' / 'gisCal' / 'NHS_interstate_nisr.geojson',
    'cc_pa': Path(__file__).resolve().parent.parent / 'maps' / 'gisCal' / 'NHS_CC_PA.geojson',
    'fl_brwd': Path(__file__).resolve().parent.parent / 'maps' / 'gisCal' / 'NHS_FL_Brwd.geojson',
}
NHS_CSV_FILES = {
    'interstate_nisr': Path(__file__).resolve().parent.parent / 'maps' / 'gisCal' / 'NHS_interstate_nisr.csv',
    'cc_pa': Path(__file__).resolve().parent.parent / 'maps' / 'gisCal' / 'NHS_CC_PA.csv',
    'fl_brwd': Path(__file__).resolve().parent.parent / 'maps' / 'gisCal' / 'NHS_FL_Brwd.csv',
}
NHS_DATASET_JOIN_KEYS = {
    'interstate_nisr': 'OBJECTID',
    'cc_pa': 'OBJECTID',
    'fl_brwd': 'FID',
}
NHS_DATASET_LENGTH_FIELDS = {
    'interstate_nisr': 'Shape_Length',
    'cc_pa': 'Shape_Length',
    'fl_brwd': 'Shape_Leng',
}
DRIVE_HEATMAP_DATASETS = {
    'ca_shs': {
        'file_glob': 'CA_SHS_Grid_Passes_*.json',
        'file_prefix': 'CA_SHS_Grid_Passes_',
        'label': 'CA SHS Grid Passes',
    },
	'cc_pa': {
		'file_glob': 'CC_PA_Grid_Passes_*.json',
		'file_prefix': 'CC_PA_Grid_Passes_',
		'label': 'CC PA Grid Passes',
	},
    'fl_brwd': {
        'file_glob': 'FL_Brwd_Grid_Pass-*.json',
        'file_prefix': 'FL_Brwd_Grid_Pass-',
        'label': 'Florida Broward NHS Grid Passes',
    },
}


def resolve_named_drive_heatmap_dataset(dataset):
    dataset_config = DRIVE_HEATMAP_DATASETS.get(dataset)
    if dataset_config is None:
        raise ValueError('Drive heatmap dataset is unavailable')

    if dataset_config.get('grid_passes_file'):
        source_file = Path(dataset_config['grid_passes_file'])
        if not source_file.exists():
            raise FileNotFoundError('Drive heatmap grid pass JSON not found')
        selected_date = dataset_config.get('selected_date') or driveFilter.infer_drive_file_date(source_file.name)
        return source_file, selected_date, dataset_config

    matching_files = sorted(DRIVE_SOURCE_PATH.glob(dataset_config['file_glob']))
    if not matching_files:
        raise FileNotFoundError('Drive heatmap grid pass JSON not found')

    source_file = matching_files[-1]
    selected_date = driveFilter.infer_drive_file_date(source_file.name)
    return source_file, selected_date, dataset_config

def load_viz_drive_heatmap_dates():
    available_dates = set()
    for grid_passes_file in sorted(DRIVE_SOURCE_PATH.glob('BayArea_*Grid_Passes*.json')):
        file_date = driveFilter.infer_drive_file_date(grid_passes_file.name)
        if file_date:
            available_dates.add(file_date)
    return sorted(available_dates)


def resolve_grid_passes_file(date_text):
    candidate_files = [
        DRIVE_SOURCE_PATH / driveFilter.get_grid_passes_file_name(date_text),
        DRIVE_SOURCE_PATH / f'{PASS_FILTERED_FILE}_{date_text}.json',
    ]

    for candidate_file in candidate_files:
        if candidate_file.exists():
            return candidate_file

    matching_files = sorted(DRIVE_SOURCE_PATH.glob(f'*{date_text}*Grid_Passes*.json'))
    if matching_files:
        return matching_files[-1]

    raise FileNotFoundError('Drive heatmap grid pass JSON not found')


def resolve_drive_day_source_file(date_text):
    candidate_files = [
        DRIVE_SOURCE_PATH / f'BayArea_Get_Drives_{date_text}.json',
        # DRIVE_SOURCE_PATH / f'BayArea_{date_text}_Get_Drives_All.json',
        DRIVE_SOURCE_PATH / f'{DRIVE_FILTERED_FILE}_{date_text}.json',
    ]

    for candidate_file in candidate_files:
        if candidate_file.exists():
            return candidate_file

    matching_files = sorted(DRIVE_SOURCE_PATH.glob(f'*{date_text}*Get_Driv*.json'))
    if matching_files:
        return matching_files[-1]

    raise FileNotFoundError('Drive trajectory JSON not found')


def resolve_filtered_drive_file():
    candidate_files = [
        DRIVE_SOURCE_PATH / f'{DRIVE_FILTERED_FILE}_Plot.json',
        DRIVE_SOURCE_PATH / DRIVE_ORG_FILE,
    ]

    for candidate_file in candidate_files:
        if candidate_file.exists():
            return candidate_file

    matching_files = sorted(DRIVE_SOURCE_PATH.glob('BayArea_Get_Drives_*.json'))
    if matching_files:
        return matching_files[-1]

    raise FileNotFoundError('Drive trajectory JSON not found')


@lru_cache(maxsize=16)
def load_grid_source_indices(grid_file_name):
    grid_file = DRIVE_SOURCE_PATH / grid_file_name
    if not grid_file.exists():
        return {}

    with grid_file.open('r', encoding='utf-8') as handle:
        grid_payload = json.load(handle)

    raw_grid_points = grid_payload.get('points', []) if isinstance(grid_payload, dict) else grid_payload
    source_indices = {}
    for source_index, point in enumerate(raw_grid_points):
        coordinates = point.get('coordinates', [])
        if len(coordinates) < 2:
            continue
        coord_key = (round(float(coordinates[0]), 6), round(float(coordinates[1]), 6))
        source_indices.setdefault(coord_key, source_index)

    return source_indices


def attach_grid_source_indices(grid_passes_payload):
    grid_file_name = (grid_passes_payload.get('summary') or {}).get('grid_file')
    if not grid_file_name:
        return grid_passes_payload

    source_indices = load_grid_source_indices(grid_file_name)
    if not source_indices:
        return grid_passes_payload

    for point in grid_passes_payload.get('points', []):
        if point.get('source_index') is not None:
            continue
        coordinates = point.get('coordinates', [])
        if len(coordinates) < 2:
            continue
        coord_key = (round(float(coordinates[0]), 6), round(float(coordinates[1]), 6))
        if coord_key in source_indices:
            point['source_index'] = source_indices[coord_key]

    return grid_passes_payload


def parse_drive_image_file(image_path):
    name_parts = image_path.stem.split('_')
    if len(name_parts) < 2:
        return None

    vehicle_id = name_parts[0]
    capture_time_text = name_parts[1]
    try:
        capture_time = datetime.strptime(capture_time_text, '%Y%m%d%H%M%S')
    except ValueError:
        return None

    return {
        'vehicle_id': vehicle_id,
        'capture_time_text': capture_time_text,
        'capture_time': capture_time,
        'capture_time_iso': capture_time.isoformat(timespec='seconds') + 'Z',
        'relative_path': image_path.relative_to(IMAGE_DATA_PATH).as_posix(),
    }


@lru_cache(maxsize=1)
def load_drive_image_index():
    if not IMAGE_DATA_PATH.exists():
        return []

    image_entries = []
    for category_dir in sorted(IMAGE_DATA_PATH.iterdir()):
        if not category_dir.is_dir():
            continue

        for image_path in sorted(category_dir.iterdir()):
            if not image_path.is_file() or image_path.suffix.lower() not in IMAGE_EXTENSIONS:
                continue

            parsed_entry = parse_drive_image_file(image_path)
            if parsed_entry:
                image_entries.append(parsed_entry)

    return image_entries

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


@app.get('/api/viz_drive_image')
async def get_viz_drive_image(relative_path: str):
    resolved_image_path = (IMAGE_DATA_PATH / relative_path).resolve()
    image_root_path = IMAGE_DATA_PATH.resolve()

    if image_root_path not in resolved_image_path.parents:
        return JSONResponse({"error": "Invalid image path"}, status_code=400)

    if not resolved_image_path.exists() or not resolved_image_path.is_file():
        return JSONResponse({"error": "Image not found"}, status_code=404)

    return FileResponse(resolved_image_path)


@lru_cache(maxsize=len(NHS_GEOJSON_FILES))
def load_nhs_geojson(dataset):
    geojson_path = NHS_GEOJSON_FILES.get(dataset)
    if geojson_path is None:
        raise ValueError('Invalid NHS GeoJSON dataset')

    if not geojson_path.exists():
        raise FileNotFoundError('NHS GeoJSON not found')

    with geojson_path.open('r', encoding='utf-8') as handle:
        geojson_data = json.load(handle)

    csv_shape_lengths = load_nhs_csv_shape_lengths(dataset)
    join_key = NHS_DATASET_JOIN_KEYS.get(dataset, 'OBJECTID')
    for feature in geojson_data.get('features', []):
        properties = feature.get('properties') or {}
        feature_key = str(properties.get(join_key, '')).strip()
        if feature_key in csv_shape_lengths:
            properties['Shape_Length'] = csv_shape_lengths[feature_key]
        feature['properties'] = properties

    return geojson_data


@lru_cache(maxsize=len(NHS_CSV_FILES))
def load_nhs_csv_shape_lengths(dataset):
    csv_path = NHS_CSV_FILES.get(dataset)
    if csv_path is None:
        raise ValueError('Invalid NHS CSV dataset')

    if not csv_path.exists():
        raise FileNotFoundError('NHS CSV not found')

    shape_lengths = {}
    join_key = NHS_DATASET_JOIN_KEYS.get(dataset, 'OBJECTID')
    length_field = NHS_DATASET_LENGTH_FIELDS.get(dataset, 'Shape_Length')
    with csv_path.open(newline='', encoding='utf-8-sig') as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            feature_key = row.get(join_key, '').strip()
            if not feature_key:
                continue

            try:
                shape_lengths[feature_key] = float(row.get(length_field, 0) or 0)
            except ValueError:
                continue

    return shape_lengths


@app.get('/api/viz_nhs_geojson')
async def get_viz_nhs_geojson(dataset: str):
    if dataset not in NHS_GEOJSON_FILES or dataset not in NHS_CSV_FILES:
        return JSONResponse({'error': 'Invalid NHS GeoJSON dataset'}, status_code=400)

    try:
        return JSONResponse(load_nhs_geojson(dataset))
    except FileNotFoundError:
        return JSONResponse({'error': 'NHS source file not found'}, status_code=404)
    except json.JSONDecodeError as exc:
        return JSONResponse({'error': f'Failed to parse NHS GeoJSON: {exc}'}, status_code=500)


@lru_cache(maxsize=1)
def load_viz_cameras():
    camera_file = Path(__file__).resolve().parent.parent / 'maps' / 'vizz' / 'CamerasInPolygon.xml'

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
    drive_file = resolve_filtered_drive_file()

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


@lru_cache(maxsize=16)
def load_drive_grid_passes(source_file_text):
    source_file = Path(source_file_text)

    if not source_file.exists():
        raise FileNotFoundError('Drive grid pass JSON not found')

    with source_file.open('r', encoding='utf-8') as handle:
        return attach_grid_source_indices(json.load(handle))


@lru_cache(maxsize=32)
def load_viz_drive_heatmap(source_file_text, online_only):
    grid_passes_payload = load_drive_grid_passes(source_file_text)
    heatmap_payload = driveFilter.build_drive_heatmap_from_grid_passes(grid_passes_payload, online_only=online_only)
    heatmap_payload['summary']['source_file'] = Path(source_file_text).name
    return heatmap_payload


@lru_cache(maxsize=256)
def load_viz_drive_heatmap_point_detail(source_file_text, point_lat, point_lng, online_only):
    grid_passes_payload = load_drive_grid_passes(source_file_text)
    point_detail = driveFilter.build_drive_heatmap_point_detail(
        grid_passes_payload,
        point_lat,
        point_lng,
        online_only=online_only,
    )
    if point_detail is None:
        raise ValueError('Drive heatmap point not found')
    point_detail['source_file'] = Path(source_file_text).name
    return point_detail


@lru_cache(maxsize=1)
def load_viz_drive_grid():
    grid_file = DRIVE_SOURCE_PATH / DRIVE_GRID_FILE

    if not grid_file.exists():
        raise FileNotFoundError('Drive grid JSON not found')

    with grid_file.open('r', encoding='utf-8') as handle:
        raw_grid_points = json.load(handle)

    aggregated_points = {}
    for point in raw_grid_points:
        coordinates = point.get('coordinates', [])
        if len(coordinates) < 2:
            continue

        direction = point.get('dir')
        if direction is None:
            continue

        coord_key = (round(float(coordinates[0]), 6), round(float(coordinates[1]), 6))
        if coord_key in aggregated_points:
            continue

        aggregated_points[coord_key] = {
            'coordinates': [coord_key[0], coord_key[1]],
            'dir': round(float(direction)),
        }

    grid_points = []
    for point_state in aggregated_points.values():
        grid_points.append(point_state)

    return {
        'points': grid_points,
        'summary': {
            'point_count': len(grid_points),
            'source_file': grid_file.name,
            'raw_point_count': len(raw_grid_points),
        },
    }


def load_viz_drive_source_bounds():
    return driveFilter.DEFAULT_SOURCE_TIME_RANGE


def load_named_drive_heatmap_dataset(dataset, online_only):
    source_file, selected_date, dataset_config = resolve_named_drive_heatmap_dataset(dataset)
    heatmap_payload = load_viz_drive_heatmap(str(source_file), online_only)
    heatmap_payload['summary']['selected_date'] = selected_date
    heatmap_payload['summary']['available_dates'] = [selected_date] if selected_date else []
    heatmap_payload['summary']['radius_threshold_meters'] = DRIVE_HEATMAP_RADIUS_METERS
    heatmap_payload['summary']['online_only'] = online_only
    heatmap_payload['summary']['dataset'] = dataset
    heatmap_payload['summary']['dataset_label'] = dataset_config.get('label', dataset)
    return heatmap_payload


def build_drive_window(start_time_text=None, window_minutes=None):
    source_bounds = load_viz_drive_source_bounds()
    default_start = source_bounds.get('start')
    selected_start = start_time_text or default_start
    if not selected_start:
        raise ValueError('Drive source time range is unavailable')

    selected_window_minutes = window_minutes or DRIVE_WINDOW_MINUTES
    if selected_window_minutes not in DRIVE_WINDOW_OPTIONS:
        raise ValueError('Unsupported drive window duration')

    start_dt = datetime.fromisoformat(selected_start.replace('Z', '+00:00'))
    end_dt = start_dt + timedelta(minutes=selected_window_minutes)
    selected_end = end_dt.isoformat(timespec='milliseconds').replace('+00:00', 'Z')

    source_end = source_bounds.get('end')
    if source_end and selected_end > source_end:
        selected_end = source_end

    return {
        'start': selected_start,
        'end': selected_end,
        'window_minutes': selected_window_minutes,
    }


def refresh_viz_drives(start_time_text=None, window_minutes=None):
    window = build_drive_window(start_time_text, window_minutes)
    filter_date = driveFilter.get_source_file_date(window['start'])
    source_drive_file = resolve_drive_day_source_file(filter_date)
    driveFilter.filter_drive_data(
        str(source_drive_file),
        str(DRIVE_SOURCE_PATH / f"{DRIVE_FILTERED_FILE}_Plot.json"),
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
async def get_viz_drives(reload: bool = False, start_time: str | None = None, window_minutes: int | None = None):
    try:
        source_bounds = load_viz_drive_source_bounds()
        window = None
        selected_window_minutes = window_minutes or DRIVE_WINDOW_MINUTES
        if reload or start_time or window_minutes:
            window = refresh_viz_drives(start_time, selected_window_minutes)

        drive_payload = load_viz_drives()
        drive_payload['summary']['window_minutes'] = window['window_minutes'] if window else selected_window_minutes
        drive_payload['summary']['window_options'] = DRIVE_WINDOW_OPTIONS
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


@app.get('/api/viz_drive_heatmap')
async def get_viz_drive_heatmap(start_time: str | None = None, radius_meters: float | None = None, online_only: bool = False, date_text: str | None = None):
    try:
        source_bounds = load_viz_drive_source_bounds()
        selected_start = start_time or source_bounds.get('start')
        available_dates = load_viz_drive_heatmap_dates()
        if date_text:
            selected_date = date_text
        elif selected_start:
            selected_date = driveFilter.get_source_file_date(selected_start)
        elif available_dates:
            selected_date = available_dates[0]
        else:
            selected_date = None

        if not selected_date:
            raise ValueError('Drive source time range is unavailable')

        if available_dates and selected_date not in available_dates:
            raise ValueError(f'Drive heatmap data is unavailable for {selected_date}')

        selected_radius_meters = radius_meters or DRIVE_HEATMAP_RADIUS_METERS
        if abs(selected_radius_meters - DRIVE_HEATMAP_RADIUS_METERS) > 1e-9:
            raise ValueError(f'Only precomputed radius {DRIVE_HEATMAP_RADIUS_METERS:g} m is available')

        source_file = resolve_grid_passes_file(selected_date)
        heatmap_payload = load_viz_drive_heatmap(str(source_file), online_only)
        heatmap_payload['summary']['selected_time_start'] = selected_start
        heatmap_payload['summary']['selected_date'] = selected_date
        heatmap_payload['summary']['available_dates'] = available_dates
        heatmap_payload['summary']['radius_threshold_meters'] = selected_radius_meters
        heatmap_payload['summary']['online_only'] = online_only
        return JSONResponse(heatmap_payload)
    except FileNotFoundError:
        return JSONResponse({"error": "Drive heatmap grid pass JSON not found"}, status_code=404)
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)


@app.get('/api/viz_drive_heatmap_dataset')
async def get_viz_drive_heatmap_dataset(dataset: str, online_only: bool = False):
    try:
        return JSONResponse(load_named_drive_heatmap_dataset(dataset, online_only))
    except FileNotFoundError:
        return JSONResponse({"error": "Drive heatmap grid pass JSON not found"}, status_code=404)
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)


@app.get('/api/viz_drive_heatmap_point')
async def get_viz_drive_heatmap_point(lat: float, lng: float, online_only: bool = False, date_text: str | None = None):
    try:
        available_dates = load_viz_drive_heatmap_dates()
        selected_date = date_text or (available_dates[0] if available_dates else None)
        if not selected_date:
            raise ValueError('Drive heatmap data is unavailable')

        if available_dates and selected_date not in available_dates:
            raise ValueError(f'Drive heatmap data is unavailable for {selected_date}')

        source_file = resolve_grid_passes_file(selected_date)
        point_detail = load_viz_drive_heatmap_point_detail(str(source_file), round(lat, 6), round(lng, 6), online_only)
        return JSONResponse({
            'point': point_detail,
            'summary': {
                'selected_date': selected_date,
                'online_only': online_only,
                'source_file': source_file.name,
            },
        })
    except FileNotFoundError:
        return JSONResponse({"error": "Drive heatmap grid pass JSON not found"}, status_code=404)
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)


@app.get('/api/viz_drive_grid')
async def get_viz_drive_grid():
    try:
        return JSONResponse(load_viz_drive_grid())
    except FileNotFoundError:
        return JSONResponse({"error": "Drive grid JSON not found"}, status_code=404)
    except json.JSONDecodeError as exc:
        return JSONResponse({"error": f"Failed to parse drive grid JSON: {exc}"}, status_code=500)


@app.get('/api/viz_drive_images')
async def get_viz_drive_images(vehicle_id: str, time_text: str, max_offset_seconds: int = MAX_IMAGE_OFFSET, max_results: int = MAX_IMAGE_RESULTS):
    try:
        if max_offset_seconds < 0:
            raise ValueError('max_offset_seconds must be non-negative')
        if max_results <= 0:
            raise ValueError('max_results must be positive')

        normalized_vehicle_id = str(vehicle_id).strip()
        if not normalized_vehicle_id:
            raise ValueError('vehicle_id is required')

        target_time = datetime.fromisoformat(time_text.replace('Z', '+00:00')).replace(tzinfo=None)
        image_matches = []

        for image_entry in load_drive_image_index():
            if image_entry['vehicle_id'] != normalized_vehicle_id:
                continue

            delta_seconds = (image_entry['capture_time'] - target_time).total_seconds()
            if delta_seconds < 0 or delta_seconds > max_offset_seconds:
                continue

            image_matches.append({
                'vehicle_id': image_entry['vehicle_id'],
                'capture_time': image_entry['capture_time_iso'],
                'capture_time_text': image_entry['capture_time_text'],
                'relative_path': image_entry['relative_path'],
                'delta_seconds': delta_seconds,
                'url': f"/api/viz_drive_image?relative_path={image_entry['relative_path']}",
            })

        image_matches.sort(key=lambda image_match: (image_match['delta_seconds'], image_match['capture_time_text']))
        limited_matches = image_matches[:min(max_results, MAX_IMAGE_RESULTS)]

        return JSONResponse({
            'vehicle_id': normalized_vehicle_id,
            'time_text': time_text,
            'max_offset_seconds': max_offset_seconds,
            'images': limited_matches,
        })
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