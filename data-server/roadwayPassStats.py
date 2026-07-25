import argparse
import json
import math
from pathlib import Path

import geoCalc


DEFAULT_BREAK_DISTANCE_METERS = 450.0
DEFAULT_EXTENDED_BREAK_DISTANCE_METERS = 700.0
DEFAULT_BEARING_TOLERANCE_DEGREES = 15.0
METERS_PER_MILE = 1609.344
DEFAULT_BINS = '0-2,3-5,6-8,9-11,12+'


def parse_bins(bin_text):
	bins = []
	for item in bin_text.split(','):
		item = item.strip()
		if not item:
			continue
		if item.endswith('+'):
			minimum = int(item[:-1])
			bins.append((item, minimum, None))
			continue
		parts = item.split('-', 1)
		if len(parts) != 2:
			raise ValueError(f'Invalid bin definition: {item}')
		minimum = int(parts[0])
		maximum = int(parts[1])
		if maximum < minimum:
			raise ValueError(f'Invalid bin definition: {item}')
		bins.append((item, minimum, maximum))
	if not bins:
		raise ValueError('At least one bin is required')
	return bins


def get_bearing_degrees(lat1, lng1, lat2, lng2):
	lat1_radians = math.radians(lat1)
	lat2_radians = math.radians(lat2)
	delta_lng_radians = math.radians(lng2 - lng1)
	y_value = math.sin(delta_lng_radians) * math.cos(lat2_radians)
	x_value = (
		math.cos(lat1_radians) * math.sin(lat2_radians)
		- math.sin(lat1_radians) * math.cos(lat2_radians) * math.cos(delta_lng_radians)
	)
	return (math.degrees(math.atan2(y_value, x_value)) + 360.0) % 360.0


def get_bearing_delta_degrees(left_bearing, right_bearing):
	difference = abs(left_bearing - right_bearing) % 360.0
	return difference if difference <= 180.0 else 360.0 - difference


def can_use_extended_connection(sorted_points, index, pair_bearing, tolerance_degrees):
	previous_point = sorted_points[index - 1] if index > 0 else None
	next_point = sorted_points[index + 2] if index + 2 < len(sorted_points) else None

	if previous_point and previous_point['source_index'] == sorted_points[index]['source_index'] - 1:
		previous_bearing = get_bearing_degrees(
			previous_point['lat'],
			previous_point['lng'],
			sorted_points[index]['lat'],
			sorted_points[index]['lng'],
		)
		if get_bearing_delta_degrees(previous_bearing, pair_bearing) <= tolerance_degrees:
			return True

	if next_point and next_point['source_index'] == sorted_points[index + 1]['source_index'] + 1:
		next_bearing = get_bearing_degrees(
			sorted_points[index + 1]['lat'],
			sorted_points[index + 1]['lng'],
			next_point['lat'],
			next_point['lng'],
		)
		if get_bearing_delta_degrees(next_bearing, pair_bearing) <= tolerance_degrees:
			return True

	return False


def classify_count(count, bins):
	for label, minimum, maximum in bins:
		if maximum is None and count >= minimum:
			return label
		if maximum is not None and minimum <= count <= maximum:
			return label
	raise ValueError(f'Count {count} did not match any bin')


def load_heatmap_points(grid_passes_file):
	with open(grid_passes_file, 'r', encoding='utf-8') as handle:
		payload = json.load(handle)

	points = []
	for point in payload.get('points', []):
		coordinates = point.get('coordinates', [])
		if len(coordinates) < 2:
			continue
		points.append({
			'lat': float(coordinates[1]),
			'lng': float(coordinates[0]),
			'count': len(point.get('passes', [])),
			'source_index': point.get('source_index'),
		})

	return points, payload.get('summary', {})


def calculate_mileage_by_interval(
	points,
	bins,
	break_distance_meters=DEFAULT_BREAK_DISTANCE_METERS,
	extended_break_distance_meters=DEFAULT_EXTENDED_BREAK_DISTANCE_METERS,
	bearing_tolerance_degrees=DEFAULT_BEARING_TOLERANCE_DEGREES,
):
	sorted_points = sorted(
		(point for point in points if isinstance(point.get('source_index'), int)),
		key=lambda point: point['source_index'],
	)
	stats = {
		label: {
			'miles': 0.0,
			'segment_count': 0,
		}
		for label, _, _ in bins
	}

	skipped_non_adjacent = 0
	skipped_breaks = 0
	connected_segment_count = 0
	total_connected_meters = 0.0

	for index in range(len(sorted_points) - 1):
		start_point = sorted_points[index]
		end_point = sorted_points[index + 1]
		if end_point['source_index'] != start_point['source_index'] + 1:
			skipped_non_adjacent += 1
			continue

		pair_distance_meters = geoCalc.get_distance_meters(
			start_point['lat'],
			start_point['lng'],
			end_point['lat'],
			end_point['lng'],
		)
		pair_bearing = get_bearing_degrees(
			start_point['lat'],
			start_point['lng'],
			end_point['lat'],
			end_point['lng'],
		)
		is_nearby = pair_distance_meters <= break_distance_meters
		is_extended_nearby = pair_distance_meters <= extended_break_distance_meters and can_use_extended_connection(
			sorted_points,
			index,
			pair_bearing,
			bearing_tolerance_degrees,
		)

		if not is_nearby and not is_extended_nearby:
			skipped_breaks += 1
			continue

		segment_count = max(start_point['count'], end_point['count'])
		bucket_label = classify_count(segment_count, bins)
		stats[bucket_label]['miles'] += pair_distance_meters / METERS_PER_MILE
		stats[bucket_label]['segment_count'] += 1
		connected_segment_count += 1
		total_connected_meters += pair_distance_meters

	return {
		'bins': stats,
		'summary': {
			'point_count': len(sorted_points),
			'connected_segment_count': connected_segment_count,
			'total_connected_miles': total_connected_meters / METERS_PER_MILE,
			'skipped_non_adjacent_pairs': skipped_non_adjacent,
			'skipped_distance_break_pairs': skipped_breaks,
			'break_distance_meters': break_distance_meters,
			'extended_break_distance_meters': extended_break_distance_meters,
			'bearing_tolerance_degrees': bearing_tolerance_degrees,
		},
	}


def main():
	argument_parser = argparse.ArgumentParser(description='Calculate roadway miles by drive-pass interval from a grid-pass file.')
	argument_parser.add_argument('grid_passes_file', help='Path to a *_Grid_Passes_*.json file')
	argument_parser.add_argument('--bins', default=DEFAULT_BINS, help=f'Comma-separated bins. Default: {DEFAULT_BINS}')
	argument_parser.add_argument('--json', action='store_true', help='Print machine-readable JSON output')
	args = argument_parser.parse_args()

	bins = parse_bins(args.bins)
	grid_passes_path = Path(args.grid_passes_file)
	points, input_summary = load_heatmap_points(grid_passes_path)
	stats = calculate_mileage_by_interval(points, bins)
	stats['summary']['source_file'] = grid_passes_path.name
	stats['summary']['grid_file'] = input_summary.get('grid_file')
	stats['summary']['selected_date'] = input_summary.get('selected_date')

	if args.json:
		print(json.dumps(stats, indent=2))
		return

	print(f"Source file: {stats['summary']['source_file']}")
	if stats['summary'].get('grid_file'):
		print(f"Grid file: {stats['summary']['grid_file']}")
	print(f"Connected segment miles: {stats['summary']['total_connected_miles']:.2f}")
	print(f"Connected segments: {stats['summary']['connected_segment_count']}")
	print(f"Skipped non-adjacent pairs: {stats['summary']['skipped_non_adjacent_pairs']}")
	print(f"Skipped distance-break pairs: {stats['summary']['skipped_distance_break_pairs']}")
	print('Miles by drive-pass interval:')
	for label, _, _ in bins:
		bucket = stats['bins'][label]
		print(f"  {label}: {bucket['miles']:.2f} miles across {bucket['segment_count']} connected links")


if __name__ == '__main__':
	main()