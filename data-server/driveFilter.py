# create a new json file to filter the drive data for a given location box
# example json content:
# {"type":"FeatureCollection","features":[
#   {"geometry":{"coordinates":[[-96.5256,30.23894],[-96.51688,30.24657]],"type":"MultiPoint"},
#    "properties":{"Heading":50,"Online":true,"Seconds":62,"Speed":50,"Time":"2026-06-23T16:50:23.000Z","VehicleId":590457},
#    "type":"Feature"},
#  ...]}

import argparse
import json
import math
import os
import re
from datetime import datetime, timedelta
import ijson
import geoCalc

DEFAULT_FILTER_LOC_BOX = {
	'lat_min': 37.288392,
	'lat_max': 38.048667,
	'lon_min': -122.572667,
	'lon_max': -121.763813,
}

DEFAULT_SOURCE_TIME_RANGE = {
	'start': '2026-06-23T17:00:00.000Z',
	'end': '2026-07-03T16:00:00.000Z',
}

DEFAULT_WINDOW_MINUTES = 30
DEFAULT_DAY_SPLIT_HOUR = 6
DEFAULT_GRID_PASS_RADIUS_METERS = 8.0
DEFAULT_GRID_FILE_NAME = 'BayArea_Grid.json'
DEFAULT_GRID_PASS_HEADING_DELTA_DEGREES = 60.0


def parse_drive_time(timestamp_text):
	return datetime.fromisoformat(timestamp_text.replace('Z', '+00:00'))


def format_drive_time(timestamp_value):
	return timestamp_value.isoformat(timespec='milliseconds').replace('+00:00', 'Z')


def get_source_file_date(timestamp_text, split_hour=DEFAULT_DAY_SPLIT_HOUR):
	timestamp_value = parse_drive_time(timestamp_text)
	if timestamp_value.hour < split_hour:
		timestamp_value -= timedelta(days=1)
	return timestamp_value.date().isoformat()


def infer_drive_file_date(file_name):
	date_match = re.search(r'(\d{4}-\d{2}-\d{2})', os.path.basename(file_name))
	if date_match:
		return date_match.group(1)
	return None


def get_grid_passes_file_name(date_text):
	return f'BayArea_{date_text}_Grid_Passes.json'


def build_split_day_time_range(date_text, split_hour=DEFAULT_DAY_SPLIT_HOUR):
	day_start = datetime.fromisoformat(f'{date_text}T{split_hour:02d}:00:00+00:00')
	day_end = day_start + timedelta(days=1) - timedelta(milliseconds=1)
	return {
		'start': format_drive_time(day_start),
		'end': format_drive_time(day_end),
	}


def iter_drive_features(input_file):
	with open(input_file, 'rb') as handle:
		if handle.read(3) != b'\xef\xbb\xbf':
			handle.seek(0)
			print('char encoding is not utf-8-sig, using utf-8')

		for feature in ijson.items(handle, 'features.item', use_float=True):
			yield feature


def get_segment_heading(start_lon, start_lat, end_lon, end_lat):
	delta_x, delta_y, _ = geoCalc.calc_lat_lon_offset(start_lon, start_lat, end_lon, end_lat)
	if delta_x == 0 and delta_y == 0:
		return None
	return (math.degrees(math.atan2(delta_x, delta_y)) + 360.0) % 360.0


def get_heading_delta_degrees(heading_a, heading_b):
	delta = abs(float(heading_a) - float(heading_b)) % 360.0
	return min(delta, 360.0 - delta)


def load_grid_points(grid_file):
	with open(grid_file, 'r', encoding='utf-8') as grid_handle:
		grid_payload = json.load(grid_handle)

	if isinstance(grid_payload, dict):
		raw_grid_points = grid_payload.get('points', [])
	else:
		raw_grid_points = grid_payload

	unique_grid_points = []
	seen_coordinates = set()
	for point in raw_grid_points:
		coordinates = point.get('coordinates', [])
		if len(coordinates) < 2:
			continue

		coord_key = (round(float(coordinates[0]), 6), round(float(coordinates[1]), 6))
		if coord_key in seen_coordinates:
			continue

		seen_coordinates.add(coord_key)
		grid_point = {
			'coordinates': [coord_key[0], coord_key[1]],
			'dir': round(float(point.get('dir', 0))),
			'passes': [],
		}
		unique_grid_points.append(grid_point)

	return unique_grid_points, len(raw_grid_points)


def build_grid_spatial_index(grid_points, radius_threshold_meters):
	center_lat = (DEFAULT_FILTER_LOC_BOX['lat_min'] + DEFAULT_FILTER_LOC_BOX['lat_max']) / 2.0
	lat_cell_size = radius_threshold_meters / 111111.0
	lon_cell_size = radius_threshold_meters / max(111111.0 * math.cos(math.radians(center_lat)), 1e-6)
	spatial_index = {}

	for point in grid_points:
		point_lon, point_lat = point['coordinates']
		cell_x = int(point_lon / lon_cell_size)
		cell_y = int(point_lat / lat_cell_size)
		spatial_index.setdefault((cell_x, cell_y), []).append(point)

	return {
		'points': grid_points,
		'spatial_index': spatial_index,
		'lat_cell_size': lat_cell_size,
		'lon_cell_size': lon_cell_size,
	}


def iter_matching_grid_points(grid_index, start_lon, start_lat, end_lon, end_lat, radius_threshold_meters, heading_degrees=None, heading_delta_limit_degrees=DEFAULT_GRID_PASS_HEADING_DELTA_DEGREES):
	min_lon = min(start_lon, end_lon)
	max_lon = max(start_lon, end_lon)
	min_lat = min(start_lat, end_lat)
	max_lat = max(start_lat, end_lat)
	lon_padding = grid_index['lon_cell_size']
	lat_padding = grid_index['lat_cell_size']
	min_cell_x = int((min_lon - lon_padding) / grid_index['lon_cell_size'])
	max_cell_x = int((max_lon + lon_padding) / grid_index['lon_cell_size'])
	min_cell_y = int((min_lat - lat_padding) / grid_index['lat_cell_size'])
	max_cell_y = int((max_lat + lat_padding) / grid_index['lat_cell_size'])
	segment_x2, segment_y2 = geoCalc.calc_lat_lon_offset(start_lon, start_lat, end_lon, end_lat)[:2]
	seen_coordinates = set()

	for cell_x in range(min_cell_x, max_cell_x + 1):
		for cell_y in range(min_cell_y, max_cell_y + 1):
			for point in grid_index['spatial_index'].get((cell_x, cell_y), []):
				coord_key = tuple(point['coordinates'])
				if coord_key in seen_coordinates:
					continue

				point_lon, point_lat = point['coordinates']
				target_x, target_y = geoCalc.calc_lat_lon_offset(start_lon, start_lat, point_lon, point_lat)[:2]
				distance_meters, distance_type = geoCalc.distance_to_segment(0.0, 0.0, segment_x2, segment_y2, target_x, target_y)
				if distance_meters > radius_threshold_meters or distance_type != 'middle':
					continue

				if heading_degrees is not None:
					grid_heading = point.get('dir')
					if grid_heading is None:
						continue
					heading_delta = get_heading_delta_degrees(heading_degrees, grid_heading)
					if heading_delta > heading_delta_limit_degrees:
						continue

				seen_coordinates.add(coord_key)
				yield point, distance_meters


def build_drive_grid(input_file, min_spacing_meters=20.0, heading_bin_degrees=15.0, max_points=None):
	grid_points = []
	spatial_index = {}
	lat_cell_size = min_spacing_meters / 111111.0

	for feature in iter_drive_features(input_file):
		coordinates = feature.get('geometry', {}).get('coordinates', [])
		if len(coordinates) < 2:
			continue

		start_lon, start_lat = coordinates[0]
		end_lon, end_lat = coordinates[-1]
		heading_dir = get_segment_heading(start_lon, start_lat, end_lon, end_lat)
		if heading_dir is None:
			continue

		candidate_points = [coordinates[0], coordinates[-1]]

		for point_lon, point_lat in candidate_points:
			lon_cell_size = min_spacing_meters / max(111111.0 * math.cos(math.radians(point_lat)), 1e-6)
			cell_x = int(point_lon / lon_cell_size)
			cell_y = int(point_lat / lat_cell_size)
			matched_point = None
			for neighbor_x in range(cell_x - 1, cell_x + 2):
				for neighbor_y in range(cell_y - 1, cell_y + 2):
					for existing_point in spatial_index.get((neighbor_x, neighbor_y), []):
						distance_meters = geoCalc.get_distance_meters(existing_point['coordinates'][1], existing_point['coordinates'][0], point_lat, point_lon)
						if distance_meters < min_spacing_meters:
							matched_point = existing_point
							break
					if matched_point is not None:
						break
				if matched_point is not None:
					break

			if matched_point is not None:
				continue

			grid_point = {
				'coordinates': [round(point_lon, 6), round(point_lat, 6)],
				'dir': round(float(heading_dir)),
			}
			grid_points.append(grid_point)
			spatial_index.setdefault((cell_x, cell_y), []).append(grid_point)

			if max_points is not None and len(grid_points) >= max_points:
				break

		if max_points is not None and len(grid_points) >= max_points:
			break

	return grid_points


def build_drive_grid_passes(input_file, grid_file, radius_threshold_meters=DEFAULT_GRID_PASS_RADIUS_METERS):
	grid_points, raw_point_count = load_grid_points(grid_file)
	grid_index = build_grid_spatial_index(grid_points, radius_threshold_meters)
	total_pass_count = 0

	for feature in iter_drive_features(input_file):
		properties = feature.get('properties', {})
		feature_time = properties.get('Time')
		vehicle_id = properties.get('VehicleId')
		online = bool(properties.get('Online'))
		coordinates = feature.get('geometry', {}).get('coordinates', [])
		if feature_time is None or len(coordinates) < 2:
			continue

		start_lon, start_lat = coordinates[0]
		end_lon, end_lat = coordinates[-1]
		segment_heading = get_segment_heading(start_lon, start_lat, end_lon, end_lat)
		if segment_heading is None:
			continue

		for point, distance_meters in iter_matching_grid_points(
			grid_index,
			start_lon,
			start_lat,
			end_lon,
			end_lat,
			radius_threshold_meters,
			heading_degrees=segment_heading,
		):
			point['passes'].append({
				'time': feature_time,
				'vehicle_id': vehicle_id,
				'online': online,
				'distance_meters': round(distance_meters, 1),
				'heading': round(segment_heading),
			})
			total_pass_count += 1

	active_point_count = sum(1 for point in grid_points if point['passes'])
	return {
		'points': grid_points,
		'summary': {
			'grid_point_count': len(grid_points),
			'raw_grid_point_count': raw_point_count,
			'active_point_count': active_point_count,
			'total_pass_count': total_pass_count,
			'radius_threshold_meters': radius_threshold_meters,
			'heading_delta_limit_degrees': DEFAULT_GRID_PASS_HEADING_DELTA_DEGREES,
			'source_file': os.path.basename(input_file),
			'grid_file': os.path.basename(grid_file),
		},
	}


def build_drive_heatmap_from_grid_passes(grid_passes_payload, online_only=False, include_vehicle_ids=False):
	grid_points = grid_passes_payload.get('points', [])
	grid_summary = grid_passes_payload.get('summary', {})
	heatmap_points = []
	active_coordinate_keys = set()
	max_count = 0
	total_pass_count = 0

	for point in grid_points:
		matching_passes = []
		for pass_event in point.get('passes', []):
			if online_only and not pass_event.get('online'):
				continue
			matching_passes.append(pass_event)

		count = len(matching_passes)
		if count <= 0:
			continue

		vehicle_ids = []
		seen_vehicle_ids = set()
		for pass_event in matching_passes:
			vehicle_id = pass_event.get('vehicle_id')
			if vehicle_id is None:
				continue
			if vehicle_id in seen_vehicle_ids:
				continue
			seen_vehicle_ids.add(vehicle_id)
			vehicle_ids.append(vehicle_id)

		vehicle_ids.sort(key=lambda vehicle_id: str(vehicle_id))

		time_values = [pass_event.get('time') for pass_event in matching_passes if pass_event.get('time')]
		point_lon, point_lat = point.get('coordinates', [None, None])
		coordinate_key = (point_lon, point_lat)
		active_coordinate_keys.add(coordinate_key)
		heatmap_points.append({
			'lat': point_lat,
			'lng': point_lon,
			'count': count,
			'vehicle_count': len(vehicle_ids),
			'first_time': min(time_values) if time_values else None,
			'last_time': max(time_values) if time_values else None,
			'dir': point.get('dir'),
		})
		if include_vehicle_ids:
			heatmap_points[-1]['vehicle_ids'] = vehicle_ids
		max_count = max(max_count, count)
		total_pass_count += count

	for point in grid_points:
		point_lon, point_lat = point.get('coordinates', [None, None])
		if point_lon is None or point_lat is None:
			continue

		if (point_lon, point_lat) in active_coordinate_keys:
			continue

		heatmap_points.append({
			'lat': point_lat,
			'lng': point_lon,
			'count': 0,
			'vehicle_count': 0,
			'first_time': None,
			'last_time': None,
			'dir': point.get('dir'),
		})
		if include_vehicle_ids:
			heatmap_points[-1]['vehicle_ids'] = []

	return {
		'points': heatmap_points,
		'summary': {
			'grid_point_count': grid_summary.get('grid_point_count', len(grid_points)),
			'active_point_count': len(heatmap_points),
			'max_count': max_count,
			'total_pass_count': total_pass_count,
			'radius_threshold_meters': grid_summary.get('radius_threshold_meters', DEFAULT_GRID_PASS_RADIUS_METERS),
			'online_only': online_only,
			'source_file': grid_summary.get('source_file'),
			'grid_file': grid_summary.get('grid_file'),
		},
	}


def build_drive_heatmap_point_detail(grid_passes_payload, target_lat, target_lng, online_only=False):
	target_lat = round(float(target_lat), 6)
	target_lng = round(float(target_lng), 6)

	for point in grid_passes_payload.get('points', []):
		point_lon, point_lat = point.get('coordinates', [None, None])
		if point_lon is None or point_lat is None:
			continue

		if round(float(point_lat), 6) != target_lat or round(float(point_lon), 6) != target_lng:
			continue

		matching_passes = []
		for pass_event in point.get('passes', []):
			if online_only and not pass_event.get('online'):
				continue
			matching_passes.append(pass_event)

		vehicle_ids = sorted({
			pass_event.get('vehicle_id')
			for pass_event in matching_passes
			if pass_event.get('vehicle_id') is not None
		}, key=lambda vehicle_id: str(vehicle_id))
		time_values = [pass_event.get('time') for pass_event in matching_passes if pass_event.get('time')]
		return {
			'lat': point_lat,
			'lng': point_lon,
			'count': len(matching_passes),
			'vehicle_count': len(vehicle_ids),
			'vehicle_ids': vehicle_ids,
			'first_time': min(time_values) if time_values else None,
			'last_time': max(time_values) if time_values else None,
			'dir': point.get('dir'),
		}

	return None


def build_drive_pass_heatmap(input_file, radius_threshold_meters, reference_vehicle_id=None, min_point_spacing_meters=12.0, online_only=False):
	reference_points = []
	selected_vehicle_id = reference_vehicle_id

	for feature in iter_drive_features(input_file):
		properties = feature.get('properties', {})
		if online_only and not properties.get('Online'):
			continue
		vehicle_id = properties.get('VehicleId')
		coordinates = feature.get('geometry', {}).get('coordinates', [])
		if len(coordinates) < 2:
			continue

		if selected_vehicle_id is None:
			selected_vehicle_id = vehicle_id

		if vehicle_id != selected_vehicle_id:
			continue

		candidate_points = [coordinates[0], coordinates[-1]]
		for point_lon, point_lat in candidate_points:
			if reference_points:
				last_point = reference_points[-1]
				spacing = geoCalc.get_distance_meters(last_point['lat'], last_point['lng'], point_lat, point_lon)
				if spacing < min_point_spacing_meters:
					continue

			reference_points.append({
				'lat': point_lat,
				'lng': point_lon,
			})

		if len(reference_points) >= 400:
			break

	if not reference_points:
		return {
			'points': [],
			'summary': {
				'reference_vehicle_id': selected_vehicle_id,
				'reference_point_count': 0,
				'max_count': 0,
			},
		}

	counts = [0] * len(reference_points)
	for feature in iter_drive_features(input_file):
		properties = feature.get('properties', {})
		if online_only and not properties.get('Online'):
			continue
		coordinates = feature.get('geometry', {}).get('coordinates', [])
		if len(coordinates) < 2:
			continue

		start_lon, start_lat = coordinates[0]
		end_lon, end_lat = coordinates[-1]
		segment_x2, segment_y2 = geoCalc.calc_lat_lon_offset(start_lon, start_lat, end_lon, end_lat)[:2]

		for index, reference_point in enumerate(reference_points):
			target_x, target_y = geoCalc.calc_lat_lon_offset(start_lon, start_lat, reference_point['lng'], reference_point['lat'])[:2]
			distance_meters, distance_type = geoCalc.distance_to_segment(0.0, 0.0, segment_x2, segment_y2, target_x, target_y)
			if distance_meters <= radius_threshold_meters and distance_type == 'middle':
				counts[index] += 1

	max_count = max(counts) if counts else 0
	heatmap_points = []
	for reference_point, count in zip(reference_points, counts):
		if count <= 0:
			continue

		heatmap_points.append({
			'lat': reference_point['lat'],
			'lng': reference_point['lng'],
			'count': count,
		})

	return {
		'points': heatmap_points,
		'summary': {
			'reference_vehicle_id': selected_vehicle_id,
			'reference_point_count': len(reference_points),
			'active_point_count': len(heatmap_points),
			'max_count': max_count,
			'radius_threshold_meters': radius_threshold_meters,
			'online_only': online_only,
		},
	}


def find_vehicle_pass_timepoints(input_file, target_coord, radius_threshold_meters, time_range=None):
	target_lat = target_coord['lat']
	target_lon = target_coord['lon']
	matching_timepoints = []

	for index, feature in enumerate(iter_drive_features(input_file)):
		properties = feature.get('properties', {})
		feature_time = properties.get('Time')
		if time_range and feature_time:
			if feature_time > time_range['end']:
				print(f"Feature {index}: Time {feature_time} is after the end of the time range. Stopping search.")
				break
			if feature_time < time_range['start']:
				continue

		coordinates = feature.get('geometry', {}).get('coordinates', [])
		if len(coordinates) < 2:
			continue

		start_lon, start_lat = coordinates[0]
		end_lon, end_lat = coordinates[1]
		segment_x2, segment_y2 = geoCalc.calc_lat_lon_offset(start_lon, start_lat, end_lon, end_lat)[:2]
		target_x, target_y = geoCalc.calc_lat_lon_offset(start_lon, start_lat, target_lon, target_lat)[:2]
		dist_m, dist_type = geoCalc.distance_to_segment(0.0, 0.0, segment_x2, segment_y2, target_x, target_y)
		if dist_m <= radius_threshold_meters and dist_type == 'middle':
			matching_timepoints.append({
				'time': feature_time,
				'vehicle_id': properties.get('VehicleId'),
				'online': properties.get('Online'),
				'distance_meters': round(dist_m, 1),
				'speed': properties.get('Speed'),
				'heading': properties.get('Heading'),
			})

	return matching_timepoints


def filter_drive_data(input_file, output_file, loc_box, time_range, max_features=None):
	filtered_features = []
	filtered_count = 0
	for index, feature in enumerate(iter_drive_features(input_file)):
		# Check if the feature's time is within the specified time range
		feature_time = feature['properties']['Time']
		if feature_time > time_range['end']:
			print(f"Feature {index}: Time {feature_time} is after the end of the time range. Stopping filtering.")
			break
		elif feature_time < time_range['start']:		
			continue
		coordinates = feature['geometry']['coordinates']
		#print(f"Feature {index}: Coordinates: {coordinates}")
		# Check if the coordinates are within the specified bounding box
		if all(loc_box['lon_min'] <= lon <= loc_box['lon_max'] and loc_box['lat_min'] <= lat <= loc_box['lat_max'] for lon, lat in coordinates):
			filtered_features.append(feature)
			filtered_count += 1
		if max_features is not None and filtered_count >= max_features:
			print(f"Reached max_features limit: {max_features}. Stopping filtering.")
			break

	filtered_data = {
		"type": "FeatureCollection",
		"features": filtered_features
	}

	try:
		with open(output_file, 'w', encoding='utf-8') as f:
			json.dump(filtered_data, f, indent=4)
	except Exception as e:
		print(f"Error writing to {output_file}: {e}")
		raise	

if __name__ == "__main__":
	argument_parser = argparse.ArgumentParser(description='Filter drive data based on location and time range.')
	argument_parser.add_argument('-f', '--input_file', type=str, help='Path to the input JSON file containing drive data.')
	argument_parser.add_argument('-d', '--date', type=str, help='Filter data for a specific date (YYYY-MM-DD).')
	argument_parser.add_argument('-t', '--time', type=str, help='Filter data for a specific time range (start,end) in ISO format.')
	argument_parser.add_argument('-g', '--grid', action='store_true', help='Get representative locations to form a map grid json file.')
	argument_parser.add_argument('-p', '--grid_passes', action='store_true', help='Build a per-day grid pass json file from BayArea_Grid.json.')
	args = argument_parser.parse_args()

	# Example usage
	location_box = DEFAULT_FILTER_LOC_BOX
	if args.date:
		# Build a single-day range using the configured split point.
		time_range = build_split_day_time_range(args.date)
	elif args.time:
		# Update time_range based on the provided time range
		start, end = args.time.split(',')
		time_range = {
			'start': start,
			'end': end
		}
	else:
		time_range = DEFAULT_SOURCE_TIME_RANGE

	work_dir = '/home/cdw/maps/xml'
	base_date = '2026-06-24' if args.date is None else args.date
	drive_file = f'BayArea_{base_date}_Get_Drives_All.json'
	filter_loc_mark = 'BayArea'
	filter_dateq_mark = args.date or infer_drive_file_date(drive_file)

	if args.grid:
		grid_points = build_drive_grid(f'{work_dir}/{drive_file}')
		grid_output_file = f'{work_dir}/{filter_loc_mark}_{filter_dateq_mark}_Grid.json'
		with open(grid_output_file, 'w', encoding='utf-8') as grid_handle:
			json.dump(grid_points, grid_handle, indent=4)
		print(f'Wrote {len(grid_points)} grid points to {grid_output_file}')
		raise SystemExit(0)

	if args.grid_passes:
		if not filter_dateq_mark:
			raise ValueError('A date is required to build grid pass files')

		grid_passes_payload = build_drive_grid_passes(
			f'{work_dir}/{drive_file}',
			f'{work_dir}/{DEFAULT_GRID_FILE_NAME}',
			radius_threshold_meters=DEFAULT_GRID_PASS_RADIUS_METERS,
		)
		grid_passes_output_file = f'{work_dir}/{get_grid_passes_file_name(filter_dateq_mark)}'
		with open(grid_passes_output_file, 'w', encoding='utf-8') as grid_passes_handle:
			json.dump(grid_passes_payload, grid_passes_handle, indent=4)
		print(
			f"Wrote {grid_passes_payload['summary']['active_point_count']} active grid points and "
			f"{grid_passes_payload['summary']['total_pass_count']} pass events to {grid_passes_output_file}"
		)
		raise SystemExit(0)

	data_file = args.input_file if args.input_file else 'Get_Drives_All.json'
	filter_loc_mark = 'BayArea'
	filter_dateq_mark = args.date or infer_drive_file_date(data_file)
	max_features = 2000
	filter_drive_data(f'{work_dir}/{data_file}', f'{work_dir}/{filter_loc_mark}_{filter_dateq_mark}_{data_file}', location_box, time_range, max_features=None)