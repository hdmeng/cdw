# create a new json file to filter the drive data for a given location box
# example json content:
# {"type":"FeatureCollection","features":[
#   {"geometry":{"coordinates":[[-96.5256,30.23894],[-96.51688,30.24657]],"type":"MultiPoint"},
#    "properties":{"Heading":50,"Online":true,"Seconds":62,"Speed":50,"Time":"2026-06-23T16:50:23.000Z","VehicleId":590457},
#    "type":"Feature"},
#  ...]}

import argparse
import json
import ijson


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


def filter_drive_data(input_file, output_file, loc_box, time_range, max_features=None):
	with open(input_file, 'rb') as f:
		# the json file start with 
		# {"type":"FeatureCollection","features":[
		if f.read(3) != b'\xef\xbb\xbf':
			f.seek(0)
			print('char encoding is not utf-8-sig, using utf-8')
		feature_iter = ijson.items(f, 'features.item', use_float=True)

		filtered_features = []
		filtered_count = 0
		for index, feature in enumerate(feature_iter):
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
	args = argument_parser.parse_args()

	# Example usage
	location_box = DEFAULT_FILTER_LOC_BOX
	if args.date:
		# Update time_range based on the provided date
		time_range = {
			'start': f'{args.date}T00:00:00.000Z',
			'end': f'{args.date}T23:59:59.999Z'
		}
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
	data_file = args.input_file if args.input_file else 'Get_Drives_All.json'
	filter_loc_mark = 'BayArea'
	filter_dateq_mark = args.date

	max_features = 2000
	filter_drive_data(f'{work_dir}/{data_file}', f'{work_dir}/{filter_loc_mark}_{filter_dateq_mark}_{data_file}', location_box, time_range, max_features=None)