# geometric calculation functions
# 

import math

# Define a function to calculate the meter offset between two lat/lon points
def calc_lat_lon_offset(lon0, lat0, lon1, lat1):
    # Calculate the offset in meters between two points given by their lat/lon coordinates
    # Reference: https://en.wikipedia.org/wiki/Geographic_coordinate_system
    # One degree of latitude is approximately 111,111 meters
    # One degree of longitude is approximately 111,111 * cos(latitude) meters
    delta_y = (lat1 - lat0) * 111111.0
    delta_x = (lon1 - lon0) * 111111.0 * math.cos(math.radians(lat0))
    delta_r = (delta_x**2 + delta_y**2)**0.5    
    return delta_x, delta_y, delta_r

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

# Define a function to calculate the distance from a point to a line segment
def distance_to_segment(x1, y1, x2, y2, x0, y0):
    # Calculate the distance from the point (x0, y0) to the line segment defined by (x1, y1) and (x2, y2)
    dx = x2 - x1
    dy = y2 - y1
    if dx == 0 and dy == 0:
        # The segment is a point
        dist2seg_type = 'point'
        dist2seg = ((x1 - x0)**2 + (y1 - y0)**2)**0.5
        return dist2seg, dist2seg_type
    
    # Calculate the parameter t for the closest point on the segment to (x0, y0)
    t = ((x0 - x1) * dx + (y0 - y1) * dy) / (dx**2 + dy**2) 
    if t < 0:
        # The closest point is the start of the segment
        dist2seg_type = 'start'
        dist2seg = ((x1 - x0)**2 + (y1 - y0)**2)**0.5
    elif t > 1:
        # The closest point is the end of the segment
        dist2seg_type = 'end'
        dist2seg = ((x2 - x0)**2 + (y2 - y0)**2)**0.5
    else:
        # The closest point is along the segment
        dist2seg_type = 'middle'
        x_closest = x1 + t * dx
        y_closest = y1 + t * dy
        dist2seg = ((x_closest - x0)**2 + (y_closest - y0)**2)**0.5

    return dist2seg, dist2seg_type 

# get the distance in meters between two lat/lon points using the Haversine formula
def get_distance_meters(lat1, lon1, lat2, lon2):
	radius_meters = 6371000
	lat1_rad = math.radians(lat1)
	lat2_rad = math.radians(lat2)
	delta_lat = math.radians(lat2 - lat1)
	delta_lon = math.radians(lon2 - lon1)
	a_value = (
		math.sin(delta_lat / 2) ** 2
		+ math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(delta_lon / 2) ** 2
	)
	c_value = 2 * math.atan2(math.sqrt(a_value), math.sqrt(1 - a_value))
	return radius_meters * c_value