from time import sleep
# import asn1tools # type: ignore
import json
# import os
import math
# import argparse  # Import the argparse module
import pickle

# Load the compiled ASN.1 specification from a file
with open('pkl/j2735_spec.pkl', 'rb') as f:
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
    veh_pos['lat'] = bsm_core.get('lat') / 10000000.0   # to degree
    veh_pos['long'] = bsm_core.get('long') / 10000000.0  # to degree
    veh_pos['speed'] = bsm_core.get('speed') * 0.02*3600/1609.34  # to mph
    veh_pos['heading'] = bsm_core.get('heading') * 0.0125  # to degree

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

# Define a function to convert the Message Frame payload to JSON
def MessageFrame_payload_to_json(payload):
    # Decode the Message Frame payload using the ASN.1 specification
    decoded = j2735_spec.decode('MessageFrame', payload)
    value_decoded = decoded.get('value')

    # Decode the nested value field if it's still encoded
    if isinstance(value_decoded, bytes):
        MapData_json = j2735_spec.decode('MapData', value_decoded)
    else: 
        MapData_json = value_decoded

    # Extract the msgIssueRevision and layerType
    msg_issue_revision = MapData_json.get('msgIssueRevision', None)
    layer_type = MapData_json.get('layerType', None)

    # Extract the intersections
    intxns = MapData_json.get('intersections', [])
    if not intxns:
        return None
    intxnData = intxns[0]

    return intxnData

# Define a function to get the intersection center
def get_intersection_center(intxn):
    
    ref_id = intxn.get('id', {}).get('id', None)
    # get the reference point
    ref_point = intxn.get('refPoint', {})
    ref_lat = ref_point.get('lat', None)
    ref_long = ref_point.get('long', None)

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
        ax.plot(veh_pos['X'], veh_pos['Y'], 'rx', label='veh location')

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
                
    return maps_hex

if __name__ == "__main__":
    maps_hex = read_mapsHex_from_file('conf/payload/LA-Hollywood-55-hgt.payload')
    for intxn_name in maps_hex.keys():
        intxn_json = MessageFrame_payload_to_json(maps_hex[intxn_name])
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
