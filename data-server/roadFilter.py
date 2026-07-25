# filter "functional classification" road files

# road entry .csv file
# OBJECTID,EventID,RouteID,F_System,Shape__Length,County_label,Caltrans_District

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path


DEFAULT_INPUT = Path("maps/gisCal/CRS_-_Functional_Classification.csv")
DEFAULT_OUTPUT = Path("maps/gisCal/CRS_d4_cc_arterial.csv")
DEFAULT_NHS_INPUT = Path("maps/gisCal/NHS.csv")
DEFAULT_NHS_OUTPUT_SET1 = Path("maps/gisCal/NHS_interstate_nisr.csv")
DEFAULT_NHS_OUTPUT_SET2 = Path("maps/gisCal/NHS_CC_PA.csv")
DEFAULT_NHS_GEOJSON_INPUT = Path("maps/gisCal/National_Highway_System.geojson")
DEFAULT_NHS_GEOJSON_OUTPUT_SET1 = Path("maps/gisCal/NHS_interstate_nisr.geojson")
DEFAULT_NHS_GEOJSON_OUTPUT_SET2 = Path("maps/gisCal/NHS_CC_PA.geojson")
DEFAULT_DISTRICT = "4"
DEFAULT_COUNTY = "CONTRA COSTA"
DEFAULT_MIN_LENGTH = 2000.0
DEFAULT_MIN_TOTAL_LENGTH = 10000.0
DEFAULT_NHS_CC_PA_LOC_BOX = {
	'lat_min': 37.722025,
	'lat_max': 38.052659,
	'lon_min': -122.401000,
	'lon_max': -121.732831,
}
NHS_CC_PA_SHS004_TYPES = {"O-NHS", "MSC"}


def parse_args() -> argparse.Namespace:
	parser = argparse.ArgumentParser(
		description="Filter CRS functional classification data or split NHS road entries.",
	)
	parser.add_argument(
		"--mode",
		choices=("crs", "nhs", "nhs-geojson"),
		default="crs",
		help="Processing mode. Default: crs",
	)
	parser.add_argument(
		"-i",
		"--input",
		type=Path,
		default=DEFAULT_INPUT,
		help=f"Input CSV file. Default: {DEFAULT_INPUT}",
	)
	parser.add_argument(
		"-o",
		"--output",
		type=Path,
		default=DEFAULT_OUTPUT,
		help=f"Output CSV file. Default: {DEFAULT_OUTPUT}",
	)
	parser.add_argument(
		"--nhs-input",
		type=Path,
		default=DEFAULT_NHS_INPUT,
		help=f"Input NHS CSV file. Default: {DEFAULT_NHS_INPUT}",
	)
	parser.add_argument(
		"--nhs-output-set1",
		type=Path,
		default=DEFAULT_NHS_OUTPUT_SET1,
		help=f"Output CSV for NHS_TYPE INTERSTATE or NISR. Default: {DEFAULT_NHS_OUTPUT_SET1}",
	)
	parser.add_argument(
		"--nhs-output-set2",
		type=Path,
		default=DEFAULT_NHS_OUTPUT_SET2,
		help=f"Output CSV for the CC PA NHS set. Default: {DEFAULT_NHS_OUTPUT_SET2}",
	)
	parser.add_argument(
		"--nhs-geojson-input",
		type=Path,
		default=DEFAULT_NHS_GEOJSON_INPUT,
		help=f"Input NHS GeoJSON file. Default: {DEFAULT_NHS_GEOJSON_INPUT}",
	)
	parser.add_argument(
		"--nhs-geojson-output-set1",
		type=Path,
		default=DEFAULT_NHS_GEOJSON_OUTPUT_SET1,
		help=f"Output GeoJSON for NHS_TYPE INTERSTATE or NISR. Default: {DEFAULT_NHS_GEOJSON_OUTPUT_SET1}",
	)
	parser.add_argument(
		"--nhs-geojson-output-set2",
		type=Path,
		default=DEFAULT_NHS_GEOJSON_OUTPUT_SET2,
		help=f"Output GeoJSON for the CC PA NHS set. Default: {DEFAULT_NHS_GEOJSON_OUTPUT_SET2}",
	)
	parser.add_argument(
		"-d",
		"--district",
		default=DEFAULT_DISTRICT,
		help=f"Caltrans district to keep. Default: {DEFAULT_DISTRICT}",
	)
	parser.add_argument(
		"-c",
		"--county",
		default=DEFAULT_COUNTY,
		help=f"County label to keep. Default: {DEFAULT_COUNTY}",
	)
	parser.add_argument(
		"-m",
		"--min-length",
		type=float,
		default=DEFAULT_MIN_LENGTH,
		help=f"Minimum Shape__Length in meters used to seed kept RouteID groups. Default: {DEFAULT_MIN_LENGTH}",
	)
	parser.add_argument(
		"-t",
		"--min-total-length",
		type=float,
		default=DEFAULT_MIN_TOTAL_LENGTH,
		help=f"Minimum cumulative Shape__Length in meters for a RouteID base to remain in the output. Default: {DEFAULT_MIN_TOTAL_LENGTH}",
	)
	return parser.parse_args()


def route_base(route_id: str) -> str:
	return route_id[:-2] if len(route_id) > 2 else route_id


def is_nhs_cc_pa_route(route_id: str, nhs_type: str) -> bool:
	if route_id.startswith("SHS_004"):
		return nhs_type in NHS_CC_PA_SHS004_TYPES

	if route_id.startswith("SHS_024"):
		return True

	return (
		(nhs_type == "M21PA" and route_id.startswith("CC"))
	)


def load_csv_object_ids(csv_path: Path) -> set[str]:
	with csv_path.open(newline="", encoding="utf-8-sig") as infile:
		reader = csv.DictReader(infile)
		if not reader.fieldnames:
			raise ValueError(f"Missing CSV header in {csv_path}")

		if "OBJECTID" not in reader.fieldnames:
			raise ValueError(f"Missing required CSV column: OBJECTID in {csv_path}")

		return {
			row["OBJECTID"].strip()
			for row in reader
			if row.get("OBJECTID", "").strip()
		}


def point_in_bounds(point: list[float], bounds: dict[str, float]) -> bool:
	if len(point) < 2:
		return False

	lon = float(point[0])
	lat = float(point[1])
	return (
		bounds['lon_min'] <= lon <= bounds['lon_max']
		and bounds['lat_min'] <= lat <= bounds['lat_max']
	)


def clip_multilinestring_to_bounds(coordinates: list, bounds: dict[str, float]) -> list[list[list[float]]]:
	clipped_lines = []
	for line in coordinates:
		current_run = []
		for point in line:
			if point_in_bounds(point, bounds):
				current_run.append(point)
			elif len(current_run) >= 2:
				clipped_lines.append(current_run)
				current_run = []
			else:
				current_run = []

		if len(current_run) >= 2:
			clipped_lines.append(current_run)

	return clipped_lines


def feature_within_bounds(feature: dict, bounds: dict[str, float]) -> dict | None:
	geometry = feature.get("geometry") or {}
	if geometry.get("type") != "MultiLineString":
		return feature

	clipped_coordinates = clip_multilinestring_to_bounds(geometry.get("coordinates", []), bounds)
	if not clipped_coordinates:
		return None

	clipped_geometry = dict(geometry)
	clipped_geometry["coordinates"] = clipped_coordinates
	clipped_feature = dict(feature)
	clipped_feature["geometry"] = clipped_geometry
	return clipped_feature


def filter_roads(
	input_path: Path,
	output_path: Path,
	district: str,
	county: str,
	min_length: float,
	min_total_length: float,
) -> int:
	county = county.strip().upper()
	district = district.strip()

	with input_path.open(newline="", encoding="utf-8-sig") as infile:
		reader = csv.DictReader(infile)

		if not reader.fieldnames:
			raise ValueError(f"Missing CSV header in {input_path}")

		required_fields = {
			"Caltrans_District",
			"County_label",
			"RouteID",
			"Shape__Length",
		}
		missing_fields = required_fields.difference(reader.fieldnames)
		if missing_fields:
			missing = ", ".join(sorted(missing_fields))
			raise ValueError(f"Missing required CSV columns: {missing}")

		filtered_rows = []
		eligible_route_bases = set()
		total_length_by_base = {}
		for row in reader:
			if (
				row["Caltrans_District"].strip() != district
				or row["County_label"].strip().upper() != county
			):
				continue

			filtered_rows.append(row)

			try:
				shape_length = float(row["Shape__Length"].strip())
			except ValueError as exc:
				raise ValueError(
					f"Invalid Shape__Length {row['Shape__Length']!r} for RouteID {row['RouteID']!r}"
				) from exc

			if shape_length >= min_length:
				eligible_route_bases.add(route_base(row["RouteID"].strip()))

			base = route_base(row["RouteID"].strip())
			total_length_by_base[base] = total_length_by_base.get(base, 0.0) + shape_length

		output_path.parent.mkdir(parents=True, exist_ok=True)
		with output_path.open("w", newline="", encoding="utf-8") as outfile:
			writer = csv.DictWriter(outfile, fieldnames=reader.fieldnames)
			writer.writeheader()

			matched_rows = 0
			for row in filtered_rows:
				base = route_base(row["RouteID"].strip())
				shape_length = float(row["Shape__Length"].strip())
				if (
					total_length_by_base.get(base, 0.0) >= min_total_length
					and (shape_length >= min_length or base in eligible_route_bases)
				):
					writer.writerow(row)
					matched_rows += 1

	return matched_rows


def split_nhs_routes(
	input_path: Path,
	output_set1: Path,
	output_set2: Path,
) -> tuple[int, int]:
	with input_path.open(newline="", encoding="utf-8-sig") as infile:
		reader = csv.DictReader(infile)

		if not reader.fieldnames:
			raise ValueError(f"Missing CSV header in {input_path}")

		required_fields = {"RouteID", "NHS_TYPE"}
		missing_fields = required_fields.difference(reader.fieldnames)
		if missing_fields:
			missing = ", ".join(sorted(missing_fields))
			raise ValueError(f"Missing required CSV columns: {missing}")

		output_set1.parent.mkdir(parents=True, exist_ok=True)
		output_set2.parent.mkdir(parents=True, exist_ok=True)

		with (
			output_set1.open("w", newline="", encoding="utf-8") as set1_file,
			output_set2.open("w", newline="", encoding="utf-8") as set2_file,
		):
			set1_writer = csv.DictWriter(set1_file, fieldnames=reader.fieldnames)
			set2_writer = csv.DictWriter(set2_file, fieldnames=reader.fieldnames)
			set1_writer.writeheader()
			set2_writer.writeheader()

			set1_count = 0
			set2_count = 0
			for row in reader:
				route_id = row["RouteID"].strip()
				nhs_type = row["NHS_TYPE"].strip().upper()

				if nhs_type in {"INTERSTATE", "NISR"}:
					set1_writer.writerow(row)
					set1_count += 1

				if is_nhs_cc_pa_route(route_id, nhs_type):
					set2_writer.writerow(row)
					set2_count += 1

	return set1_count, set2_count


def split_nhs_geojson(
	input_path: Path,
	csv_set1: Path,
	csv_set2: Path,
	output_set1: Path,
	output_set2: Path,
) -> tuple[int, int]:
	with input_path.open(encoding="utf-8-sig") as infile:
		data = json.load(infile)

	features = data.get("features")
	if not isinstance(features, list):
		raise ValueError(f"Missing GeoJSON features array in {input_path}")

	set1_object_ids = load_csv_object_ids(csv_set1)
	set2_object_ids = load_csv_object_ids(csv_set2)

	set1_features = []
	set2_features = []
	for feature in features:
		properties = feature.get("properties") or {}
		object_id = str(properties.get("OBJECTID", "")).strip()

		if object_id in set1_object_ids:
			set1_features.append(feature)

		if object_id in set2_object_ids:
			clipped_feature = feature_within_bounds(feature, DEFAULT_NHS_CC_PA_LOC_BOX)
			if clipped_feature is not None:
				set2_features.append(clipped_feature)

	output_set1.parent.mkdir(parents=True, exist_ok=True)
	output_set2.parent.mkdir(parents=True, exist_ok=True)

	set1_data = dict(data)
	set1_data["features"] = set1_features
	with output_set1.open("w", encoding="utf-8") as outfile:
		json.dump(set1_data, outfile)

	set2_data = dict(data)
	set2_data["features"] = set2_features
	with output_set2.open("w", encoding="utf-8") as outfile:
		json.dump(set2_data, outfile)

	return len(set1_features), len(set2_features)


def main() -> None:
	args = parse_args()
	if args.mode == "nhs":
		set1_count, set2_count = split_nhs_routes(
			args.nhs_input,
			args.nhs_output_set1,
			args.nhs_output_set2,
		)
		print(
			f"Wrote {set1_count} rows to {args.nhs_output_set1} and {set2_count} rows "
			f"to {args.nhs_output_set2} from {args.nhs_input}"
		)
		return

	if args.mode == "nhs-geojson":
		set1_count, set2_count = split_nhs_geojson(
			args.nhs_geojson_input,
			args.nhs_output_set1,
			args.nhs_output_set2,
			args.nhs_geojson_output_set1,
			args.nhs_geojson_output_set2,
		)
		print(
			f"Wrote {set1_count} features to {args.nhs_geojson_output_set1} and {set2_count} features "
			f"to {args.nhs_geojson_output_set2} from {args.nhs_geojson_input}"
		)
		return

	matched_rows = filter_roads(
		args.input,
		args.output,
		args.district,
		args.county,
		args.min_length,
		args.min_total_length,
	)
	print(
		f"Wrote {matched_rows} rows to {args.output} "
		f"for Caltrans_District={args.district}, County_label={args.county!r}, "
		f"min_length={args.min_length}, min_total_length={args.min_total_length}"
	)


if __name__ == "__main__":
	main()
