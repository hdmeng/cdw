import mapParse as mpp
import argparse
import json

if __name__ == "__main__":
    maps_hex = mpp.read_mapsHex_from_file('maps/D4-ECR_2025.payload')
    for intxn_name in maps_hex.keys():
        intxn_json = mpp.MessageFrame_payload_to_json(maps_hex[intxn_name])
        intxn_center = mpp.get_intersection_center(intxn_json)
        print(intxn_name, intxn_center)
        # save intxn_json to file
        with open(f'maps/json/{intxn_name}_map.json', 'w') as f:
            # write as string
        #    f.write(str(intxn_json))
            f.write(json.dumps(intxn_json, ensure_ascii=False, indent=2))