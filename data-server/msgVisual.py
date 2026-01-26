import mapParse as mpp
import argparse
import json

if __name__ == "__main__":
    # maps_hex = mpp.read_mapsHex_from_file('maps/D4-ECR_2025.payload')
    maps_hex = mpp.read_mapsHex_from_file('maps/json/ECR-Calderon.payload')
    
    for intxn_name in maps_hex.keys():
        mapData_json_raw, mapData_json, _ = mpp.MAP_payload_to_json(maps_hex[intxn_name])
        
        intxns = mapData_json.get("intersections", [])
        intxnData = intxns[0]
        intxn_center = mpp.get_intersection_center(intxnData)
        print(intxn_name, intxn_center)
        # save intxn_json to file
        with open(f'maps/json/{intxn_name}_map_raw.json', 'w') as f:
            # write as string
            f.write(str(mapData_json_raw))
        with open(f'maps/json/{intxn_name}_map.json', 'w') as f:
            f.write(json.dumps(mapData_json, ensure_ascii=False, indent=2))
        
        # eliminate duplicate lanes and convert back to payload
        mapData_rev = mpp.MAP_json_to_payload(mapData_json_raw, elim_dupl_lanes=True)
        # print Bytes length
        print(f'Original payload length: {len(maps_hex[intxn_name])}, Revised payload length: {len(mapData_rev)}')
        with open(f'maps/json/{intxn_name}_rev.payload', 'w') as f:
            f.write(mapData_rev.hex().upper())
        # decode back to JSON for verification
        _, mapData_rev_json, _ = mpp.MAP_payload_to_json(mapData_rev)
        with open(f'maps/json/{intxn_name}_map_rev.json', 'w') as f:
            f.write(json.dumps(mapData_rev_json, ensure_ascii=False, indent=2))