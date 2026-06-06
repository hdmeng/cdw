import csv
import json
from pathlib import Path
import mapParse as mpp

# combine multiple MAP payloads from the provided CSV file into a single JSON file

CSV_COLUMNS = [
	"Intersection ID",
	"Old ID",
	"Intersection Name",
	"MAP Payload",
	"Size\n(Bytes)",
]
CSV_FILE = "Updated MAP Payloads_ALL(Base Map_No Remote Intxns).csv"


def load_payload_rows(csv_path: Path) -> list[dict[str, object]]:
	rows = []

	with csv_path.open(newline="", encoding="utf-8") as csv_file:
		reader = csv.DictReader(csv_file)

		for row in reader:

			payload = row.get("MAP Payload") or None
			size_value = row.get("Size\n(Bytes)") or "0"

			if payload is not None:
				# Convert payload to JSON
				# print(f"ID: {row.get('Intersection ID')}")
				map_json_raw, _, _ = mpp.MAP_payload_to_json(bytes.fromhex(payload))

				# Eliminate duplicate lanes and convert back to payload
				payload_rev, dupl_lanes = mpp.MAP_json_to_payload(map_json_raw, elim_dupl_lanes=True)
			else:
				payload_rev = None
				
			rows.append(
				{
					"Intersection ID": row.get("Intersection ID"),
					"Old ID": row.get("Old ID"),
					"Intersection Name": row.get("Intersection Name"),
					"MAP Payload": payload,
					"Size (Bytes)": int(size_value),
					"Deduplicated MAP Payload": payload_rev.hex() if payload_rev else None,
					"Revised Size (Bytes)": len(payload_rev) if payload_rev else 0,
				}
			)

	return rows


def main() -> None:
	project_root = Path(__file__).resolve().parent.parent
	csv_path = project_root / "maps" / CSV_FILE
	output_path = project_root / "maps" / "json" / "ecr_payloads.json"
	csv_output_path = project_root / "maps" / "ecr_payloads.csv"

	rows = load_payload_rows(csv_path)

	with output_path.open("w", encoding="utf-8") as json_file:
		json.dump(rows, json_file, indent=2)

	# Generate a CSV file from the JSON output content.
	with output_path.open("r", encoding="utf-8") as json_file:
		json_rows = json.load(json_file)

	with csv_output_path.open("w", newline="", encoding="utf-8") as csv_file:
		fieldnames = list(json_rows[0].keys()) if json_rows else []
		writer = csv.DictWriter(csv_file, fieldnames=fieldnames)

		if fieldnames:
			writer.writeheader()
			writer.writerows(json_rows)

	print(f"JSON and CSV files successfully created: {output_path}, {csv_output_path}")


if __name__ == "__main__":
	main()

