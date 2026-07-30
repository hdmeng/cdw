"""Vizzion data APIs - street cameras, vehicle trajectories, drive images,
and the grid-pass drive heatmap. Moved verbatim out of bkdapp.py.

All of this feed's data lives under maps/vizz/ (drives, grid, grid passes) and
image-data/ (matched dashcam frames). The Bee Maps feed is the sibling module
beemaps_heatmap_api.py, which snaps frames onto NHS centerlines instead of
counting passes against Vizzion's own grid points.

Registered from bkdapp.py with:

    import vizz_api
    app.include_router(vizz_api.router)

Endpoint paths are unchanged, so the frontend needs no edits:
    /api/viz_cameras            /api/viz_drive_heatmap
    /api/viz_drives             /api/viz_drive_heatmap_dataset
    /api/viz_drive_image        /api/viz_drive_heatmap_point
    /api/viz_drive_images       /api/viz_drive_grid

Handlers are plain `def` rather than `async def`: they do blocking reads of
multi-MB JSON, which on the event loop is exactly what made the dashboard
unresponsive in July 2026. FastAPI runs sync handlers in its threadpool.
"""

from __future__ import annotations

import json
import re
import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from functools import lru_cache
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse, JSONResponse

# bkdapp.py already puts ./data-server on sys.path; repeat it defensively so this
# module also imports standalone (from a test or a REPL).
_DATA_SERVER = Path(__file__).resolve().parent.parent / 'data-server'
if str(_DATA_SERVER) not in sys.path:
    sys.path.append(str(_DATA_SERVER))

import driveFilter

router = APIRouter()

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

@router.get('/api/viz_drive_image')
def get_viz_drive_image(relative_path: str):
    resolved_image_path = (IMAGE_DATA_PATH / relative_path).resolve()
    image_root_path = IMAGE_DATA_PATH.resolve()

    if image_root_path not in resolved_image_path.parents:
        return JSONResponse({"error": "Invalid image path"}, status_code=400)

    if not resolved_image_path.exists() or not resolved_image_path.is_file():
        return JSONResponse({"error": "Image not found"}, status_code=404)

    return FileResponse(resolved_image_path)



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



@router.get('/api/viz_cameras')
def get_viz_cameras():
    try:
        return JSONResponse(load_viz_cameras())
    except FileNotFoundError:
        return JSONResponse({"error": "Camera XML not found"}, status_code=404)
    except ET.ParseError as exc:
        return JSONResponse({"error": f"Failed to parse camera XML: {exc}"}, status_code=500)


@router.get('/api/viz_drives')
def get_viz_drives(reload: bool = False, start_time: str | None = None, window_minutes: int | None = None):
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


@router.get('/api/viz_drive_heatmap')
def get_viz_drive_heatmap(start_time: str | None = None, radius_meters: float | None = None, online_only: bool = False, date_text: str | None = None):
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


@router.get('/api/viz_drive_heatmap_dataset')
def get_viz_drive_heatmap_dataset(dataset: str, online_only: bool = False):
    try:
        return JSONResponse(load_named_drive_heatmap_dataset(dataset, online_only))
    except FileNotFoundError:
        return JSONResponse({"error": "Drive heatmap grid pass JSON not found"}, status_code=404)
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)


@router.get('/api/viz_drive_heatmap_point')
def get_viz_drive_heatmap_point(lat: float, lng: float, online_only: bool = False, date_text: str | None = None):
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


@router.get('/api/viz_drive_grid')
def get_viz_drive_grid():
    try:
        return JSONResponse(load_viz_drive_grid())
    except FileNotFoundError:
        return JSONResponse({"error": "Drive grid JSON not found"}, status_code=404)
    except json.JSONDecodeError as exc:
        return JSONResponse({"error": f"Failed to parse drive grid JSON: {exc}"}, status_code=500)


@router.get('/api/viz_drive_images')
def get_viz_drive_images(vehicle_id: str, time_text: str, max_offset_seconds: int = MAX_IMAGE_OFFSET, max_results: int = MAX_IMAGE_RESULTS):
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
