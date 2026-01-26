from time import sleep
# import asn1tools # type: ignore
import json
# import os
import math
# import argparse  # Import the argparse module
import pickle

# Load the compiled ASN.1 specification from a file
with open('J2735Common/pkl/j2735_spec_2024.pkl', 'rb') as f:
    j2735_spec = pickle.load(f)

# function to parse the BSM message
def parse_bsm(payload, withMsgFrame=False):

    if withMsgFrame:
        # Decode the Message Frame payload using the ASN.1 specification
        decoded = j2735_spec.decode('MessageFrame', payload)
        bsm_value = decoded.get('value')
    else:
        bsm_value = payload    
    
    # Decode the BSM message using the ASN.1 specification
    decoded_bsm = j2735_spec.decode('BasicSafetyMessage', bsm_value)
    bsm_core = decoded_bsm.get('coreData')

    veh_pos = {}
    veh_pos['id'] = bsm_core.get('id') 
    veh_pos['msgCnt'] = bsm_core.get('msgCnt')
    veh_pos['secMark'] = bsm_core.get('secMark') / 1000.0  # to second
    veh_pos['lat'] = bsm_core.get('lat') / 10000000.0   # to degree
    veh_pos['long'] = bsm_core.get('long') / 10000000.0  # to degree
    veh_pos['speed'] = bsm_core.get('speed') * 0.02*3600/1609.34  # to mph
    veh_pos['heading'] = bsm_core.get('heading') * 0.0125  # to degree

    # format speed to one decimal place
    veh_pos['speed'] = float(f"{veh_pos['speed']:.1f}")
    veh_pos['heading'] = float(f"{veh_pos['heading']:.1f}")

    return veh_pos

# # function to parse the BSM message
# def parse_bsm(bsm_msg):
#     # Decode the BSM message using the ASN.1 specification
#     decoded_bsm = j2735_spec.decode('BasicSafetyMessage', bsm_msg)

#     veh_id = 12345 
#     veh_lat = decoded_bsm.get('coreData').get('lat') / 10000000.0   # to degree
#     veh_long = decoded_bsm.get('coreData').get('long') / 10000000.0  # to degree
#     veh_speed = decoded_bsm.get('coreData').get('speed') 
#     veh_heading = decoded_bsm.get('coreData').get('heading')

#     return veh_id, veh_lat, veh_long, veh_speed, veh_heading

def make_serializable(obj):
    if isinstance(obj, dict):
        return {k: make_serializable(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [make_serializable(v) for v in obj]
    if isinstance(obj, tuple):
        # handle (bytes, n) or generic tuple
        if len(obj) == 2 and isinstance(obj[0], (bytes, bytearray)) and isinstance(obj[1], int):
            # get obj[1] bits from obj[0] bytes as int
            
            b = bytes(obj[0])
            # return {
                #"type": "bitfield",
                #"hex": b.hex(),
                #"bits": obj[1],
                #"int": int.from_bytes(b, "big"),
                # "b64": base64.b64encode(b).decode()
            # }
            return int.from_bytes(b, "big")%(1<<obj[1])
        #elif len(obj) == 2 and isinstance(obj[0], str) and isinstance(obj[1], list):
        elif len(obj) == 2 and isinstance(obj[0], str):
            return {obj[0]: make_serializable(obj[1])}

        return [make_serializable(v) for v in obj]
    if isinstance(obj, (bytes, bytearray)):
        b = bytes(obj)
        return {"type": "bytes", "hex": b.hex(), "int": int.from_bytes(b, "big")}
    return obj

# Define a function to convert the MessageFrame MAP payload to JSON
def MAP_payload_to_json(payload):
    # Decode the Message Frame payload using the ASN.1 specification
    decoded = j2735_spec.decode("MessageFrame", payload)
    value_decoded = decoded.get("value")

    # Decode the nested value field if it's still encoded
    if isinstance(value_decoded, bytes):
        mapData_json_raw = j2735_spec.decode("MapData", value_decoded)
    else: 
        mapData_json_raw = value_decoded

    # Convert to a JSON-serializable format
    mapData_json = make_serializable(mapData_json_raw)

    # Extract the msgIssueRevision and layerType
    msg_issue_revision = mapData_json.get("msgIssueRevision", None)
    layer_type = mapData_json.get("layerType", None)   

    # Extract the intersections
    intxns = mapData_json_raw.get("intersections", [])
    if not intxns:
        return None
    intxn_json = intxns[0]

    return mapData_json_raw, mapData_json, intxn_json

# convert MAP JSON to hex payload
def MAP_json_to_payload(mapData_json_raw, elim_dupl_lanes=True):
    
    if elim_dupl_lanes:
        # eliminate duplicate lanes based on laneID
        lane_ids = set()
        unique_intersections = []
        for intxn in mapData_json_raw.get("intersections", []):
            unique_lanes = []
            for lane in intxn.get("laneSet", []):
                lane_id = lane.get("laneID")
                if lane_id not in lane_ids:
                    lane_ids.add(lane_id)
                    unique_lanes.append(lane)
            intxn["laneSet"] = unique_lanes
            unique_intersections.append(intxn)
        mapData_json_raw["intersections"] = unique_intersections

    # Encode the MapData structure using the ASN.1 specification
    mapdata_payload = j2735_spec.encode("MapData", mapData_json_raw)

    # Construct the MessageFrame structure
    messageFrame_struct = {
        "messageId": 18,  # Message ID for MAP
        "value": mapdata_payload
    }

    # Encode the MessageFrame structure using the ASN.1 specification
    messageFrame_payload = j2735_spec.encode("MessageFrame", messageFrame_struct)

    return messageFrame_payload

# Define a function to get the intersection center
def get_intersection_center(intxn):
    
    ref_id = intxn.get("id", {}).get("id", None)
    # get the reference point
    ref_point = intxn.get("refPoint", {})
    ref_lat = ref_point.get("lat", None)
    ref_long = ref_point.get("long", None)

    if ref_lat is not None and ref_long is not None:
        # Convert from 1/10 microdegrees to degrees
        ref_lat = ref_lat / 10000000.0
        ref_long = ref_long / 10000000.0

    #return {'id': ref_id, 'lat': ref_lat, 'lng': ref_long}
    return {"lat": ref_lat, "lng": ref_long}    # "lng" is for Google Map

# Define a function to calculate the meter offset between two lat/lon points
def calc_lat_lon_offset(lon0, lat0, lon1, lat1):
    # Calculate the offset in meters between two points given by their lat/lon coordinates
    # Reference: https://en.wikipedia.org/wiki/Geographic_coordinate_system
    # One degree of latitude is approximately 111,111 meters
    # One degree of longitude is approximately 111,111 * cos(latitude) meters
    delta_lat = (lat1 - lat0) * 111111.0
    delta_lon = (lon1 - lon0) * 111111.0 * math.cos(math.radians(lat0))
    return delta_lon, delta_lat

def calc_lat_lon_offset2(lon1, lat1, lon2, lat2):
    # Calculate the offset in meters between two lat/lon points
    R = 6371000  # Radius of the Earth in meters
    d_lat = math.radians(lat2 - lat1)
    d_lon = math.radians(lon2 - lon1)
    a = (math.sin(d_lat / 2) ** 2 +
         math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(d_lon / 2) ** 2)
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    distance = R * c
    x_offset = distance * math.cos(d_lon)
    y_offset = distance * math.sin(d_lat)
    return x_offset, y_offset

#def calc_lon_lat_by_deltaXY(lon, lat, delta_x, delta_y):


# Define a function to get all lanes
# coordinate_mode: 'XY' or 'LL'
def get_all_lanes(intxn, format='TUPLE', verbose=False):
    # Extract the geometry points
    lanes = intxn.get('laneSet', [])
    all_lane_points = {} # for TUPLE format
    all_lane_pts = []   # for JSON format
    for lane in lanes:
        # sample lane entry:
        # {        
        #   laneID 5,
        #   ingressApproach 3,
        #   laneAttributes {
        #       directionalUse {ingressPath},
        #       sharedWith {},
        #       laneType vehicle : {}
        #    },
        #    nodeList nodes: { ... }
        # }
        lane_id = lane.get('laneID', str)
        # print(lane_id) # for debug
        lane_dir = lane.get('laneAttributes', {}).get('directionalUse', {})
        # Convert lane_dir to an integer
        lane_dir_int = int.from_bytes(lane_dir[0], byteorder='big')

        nodes_tuple = lane.get('nodeList', {})
        if isinstance(nodes_tuple, tuple):
            node_type, node_list = nodes_tuple

        # for each lane, start from the reference point
        x_prev = 0.0
        y_prev = 0.0
        
        intxn_center = get_intersection_center(intxn)
        lon_prev = intxn_center['lng']
        lat_prev = intxn_center['lat']

        single_lane = []
        single_lane_LL = [] # for only LL and in JSON format
        # Extract the lane points
        for node in node_list:
            delta = node.get('delta', {})
            if isinstance(delta, tuple):
                delta_type, delta_values = delta
                if delta_type.startswith('node-XY'):
                    # delta XY in cm 
                    del_x_meter = delta_values.get('x', 0) / 100.0
                    del_y_meter = delta_values.get('y', 0) / 100.0
                    
                    # calculate x/y for current point
                    x_curr = x_prev + del_x_meter
                    y_curr = y_prev + del_y_meter
                    delta_curr = ((x_curr - x_prev)**2 + (y_curr - y_prev)**2)**0.5
                    x_prev = x_curr
                    y_prev = y_curr

                    # calculate lat/lon for current point
                    lat_curr = lat_prev + del_y_meter / 111111.0 
                    lon_curr = lon_prev + del_x_meter / (111111.0 * math.cos(math.radians(lat_prev)))
                    lat_prev = lat_curr
                    lon_prev = lon_curr

                    single_lane.append((lat_curr, lon_curr, x_curr, y_curr, delta_curr))
                    single_lane_LL.append({"lat": lat_curr, "lng": lon_curr})
                elif delta_type.startswith('node-LatLon'):
                    # delta LatLon in degree
                    x_curr = 0.0
                    y_curr = 0.0
                    delta_curr = 0.0
                    lat_curr = delta_values.get('lat', 0) / 10000000.0
                    lon_curr = delta_values.get('lon', 0) / 10000000.0
                    single_lane.append((lat_curr, lon_curr, x_curr, y_curr, delta_curr))
                    single_lane_LL.append({"lat": lat_curr, "lng": lon_curr})
                else:
                    print(f"Unexpected delta type: {delta_type}")  # Debug print for unexpected types
            else:
                point = delta.get('node-LLmD-64b', {})
                lat_offset = point.get('lat', 0) / 10000000.0
                lon_offset = point.get('lon', 0) / 10000000.0
                #single_lane.append((intxn_ref['lon'] + long_offset, intxn_ref['lat'] + lat_offset))

        if verbose:
            print(single_lane)
        # Append the lane points to the list of all lanes
        all_lane_points[lane_id, lane_dir_int] = single_lane  # use lane_id as index
        all_lane_pts.append({"id": lane_id, "dir": lane_dir_int, "points": single_lane_LL})

    if format == 'TUPLE':
        return all_lane_points
    elif format == 'JSON':
        return all_lane_pts

# Define a function to draw the intersection geometry
def draw_intersection(intxnData, intxn_name, veh_pos, draw_XY=True, draw_LL=False):

    # Get the reference points
    intxn_ref = get_intersection_center(intxnData)
    # Get all lanes
    all_lane_points = get_all_lanes(intxnData)
    
    # Plot the intersection geometry
    fig, ax = plt.subplots()
    ax.set_title('Intersection '+ intxn_name + ' Geometry')
    if draw_LL:
        ax.set_xlabel('Longitude')
        ax.set_ylabel('Latitude')
        ax.plot(intxn_ref['lng'], intxn_ref['lat'], 'ro', label='Intersection Center')
    elif    draw_XY:
        ax.set_xlabel('X (m)')
        ax.set_ylabel('Y (m)')
        ax.plot(0.0, 0.0, 'ro', label='Intersection Center')

    # for lane_points in all_lane_points:
    for lane_id, lane_dir in all_lane_points.keys():
        lane_points = all_lane_points[lane_id, lane_dir]
        if lane_points:
            lane_points = list(zip(*lane_points))  # Transpose the list of tuples
            
            if lane_dir >> 6 == 1:      # egressPath: 64
                ax.plot(lane_points[0], lane_points[1], 'go-') #, label=lane_id)
            elif lane_dir >> 6 == 2:    # ingressPath: 128 
                ax.plot(lane_points[0], lane_points[1], 'bo-') #, label=lane_id)
            else:                       # bidirectional: 192
                ax.plot(lane_points[0], lane_points[1], 'ko-')

    if draw_LL:
        ax.plot(veh_pos['lon'], veh_pos['lat'], 'rx')
    elif draw_XY:
        ax.plot(veh_pos['iX'], veh_pos['iY'], 'rx', label='veh location')

    ax.legend()
    plt.show()




# Define a function to read a hex string from a payload file
def read_hex_from_file(file_path):
    with open(file_path, 'r') as file:
        hex_string = file.read().strip()
    return bytes.fromhex(hex_string)

# Define a function to read hex strings from multiple payload file
# file format: 
# row #n: payload 8-023 723 hex_string
# format 2: 1001 ecr-medical-foundation hex_string
def read_mapsHex_from_file(file_path):
    with open(file_path, 'r') as file:
        lines = file.readlines()
        maps_hex = {}
        for line in lines:
            words = line.split()
            if len(words) == 4:     # 4 words in a row
                intxn_name = words[1]
                string_len = words[2]
                hex_string = words[3]
                maps_hex[intxn_name] = bytes.fromhex(hex_string)
                # maps_hex.append({intxn_name, bytes.fromhex(hex_string)})
            elif len(words) == 3:
                intxn_name = words[1]
                hex_string = words[2]
                maps_hex[intxn_name] = bytes.fromhex(hex_string)
            elif len(words) == 1:
                intxn_name = file_path.split('/')[-1].split('.')[0]
                hex_string = words[0]
                maps_hex[intxn_name] = bytes.fromhex(hex_string)
            else:
                continue
                
    return maps_hex

# the detector file format:
# DetNo	Dir	Type	Lat		Long		IntxnName     TPSCtrlNo   IntxnID
# 1	W/B	Advance	34.09537	-118.32234	GowerSt&FountainAv      53  3-192
def get_detector_pos(detector_file, intxn_id='all'):
    detectors = []
    with open(detector_file, 'r') as f:
        lines = f.readlines()
        for line in lines[1:]:  # Skip header line
            parts = line.strip().split('\t')
            #if len(parts) > 8:
            #    continue

            det = {
                'detNo': parts[0],
                'dir': parts[1],
                'lanes': [int(lane) for lane in parts[2].strip().split('-')],
                'type': parts[3],
                'lat': float(parts[4]), 
                'long': float(parts[5]),
                'intxnName': parts[6],
                'TPSCtrlNo': parts[7] if len(parts) > 7 else None,
                'intxnID': parts[8] if len(parts) > 8 else None,
                'dist2intxn': float(parts[9]) if len(parts) > 9 else None,
                'dist2stop': float(parts[10]) if len(parts) > 10 else None
            }

            # 
            if intxn_id == 'all' or det['intxnID'] == intxn_id:
                detectors.append(det)

    return detectors


if __name__ == "__main__":
    maps_hex = read_mapsHex_from_file('conf/payload/LA-Hollywood-55-hgt.payload')
    for intxn_name in maps_hex.keys():
        intxn_json, _ = MAP_payload_to_json(maps_hex[intxn_name])
        intxn_center = get_intersection_center(intxn_json)
        print(intxn_name, intxn_center)
        
# # A sample main function, to be deleted
# def main():
#     parser = argparse.ArgumentParser(description='Process MAP payload and draw intersection geometry.')
#     parser.add_argument('intxn_name', type=str, help='Path to the hex file containing the MAP payload')
#     parser.add_argument('-v', '--verbose', action='store_true', help='Enable verbose output')
#     parser.add_argument('-p', '--plot', action='store_true', help='Enable figure plotting')
#     args = parser.parse_args()
#     # Example MAP payload (replace with actual payload)
#     # payload ecr-ventura
#     # map_payload = bytes.fromhex(ecr-ventura-payload)
    
#     if len(args.intxn_name) < 3:
#         intxn_name = '8-023' 
#     else:
#         intxn_name = args.intxn_name

#     file_name = 'conf/payload/LA-Hollywood-' + intxn_name + '.payload'
#     map_payload = read_hex_from_file(file_name)
#     # map_payload = read_hex_from_file('conf/payload/ecr.1008.payload')
#      # Convert Message Frame payload to JSON
#     intxn_json = MessageFrame_payload_to_json(map_payload)
#     intxn_center = get_intersection_center(intxn_json)
#     print(f"Site ID: {intxn_center['id']}")
#     print(f"Center: {intxn_center['lat']}, {intxn_center['lon']}")
        
#     veh_pos = {}
#     veh_pos['lat'], veh_pos['lon'] = (34.105458, -118.291189) 
#     # (34.105425, -118.291168) , close to the oposite direction lane
#     veh_pos['X'], veh_pos['Y'] = calc_lat_lon_offset(intxn_center['lon'], intxn_center['lat'], veh_pos['lon'], veh_pos['lat'])
    
#     all_lane_points = get_all_lanes(intxn_json, args.verbose)

#     if is_in_detection_zone(intxn_center, 125, veh_pos):
#         # Calculate the distance to the intersection
#         min_dist, min_lane_id, min_point_num = lateral_offset_to_lane(all_lane_points, veh_pos)
#         if args.verbose:
#             print(f"closest lane: {min_lane_id}, distance: {min_dist:.2f} m, point#: {min_point_num}")

#         # Calculate the distance to the stop line
#         stop_dist, stop_type = distant_to_stop_line(all_lane_points, min_lane_id, min_point_num, veh_pos)
#         if args.verbose:
#             print(f"Distance to stop line: {stop_dist:.2f} m, type: {stop_type}")
#     else:
#         if args.verbose:
#             print("Vehicle is not in the effective zone")


# if __name__ == "__main__":
#     main()  
