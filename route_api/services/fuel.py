import math
from route_api.models import FuelStation

def haversine(lat1, lon1, lat2, lon2):
    """
    Calculate the great circle distance between two points 
    on the earth (specified in decimal degrees) in miles.
    """
    # Earth radius in miles
    R = 3958.8
    
    d_lat = math.radians(lat2 - lat1)
    d_lon = math.radians(lon2 - lon1)
    
    a = (math.sin(d_lat / 2) ** 2 +
         math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(d_lon / 2) ** 2)
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    
    return R * c

def project_stations_to_route(route_points, cumulative_distances, max_off_route_miles=5.0):
    """
    Finds all stations within bounding box of the route, projects them onto the route
    by finding the nearest route point, and returns a list of stations with their route mile markers.
    Uses a coarse-to-fine search algorithm to support routes with tens of thousands of points efficiently.
    """
    if not route_points:
        return []

    # Get bounding box of the route (with 0.1 degree buffer, ~7 miles)
    lats = [pt[0] for pt in route_points]
    lngs = [pt[1] for pt in route_points]
    
    min_lat, max_lat = min(lats) - 0.1, max(lats) + 0.1
    min_lng, max_lng = min(lngs) - 0.1, max(lngs) + 0.1

    # Filter stations in DB within bounding box
    stations_in_bbox = FuelStation.objects.filter(
        latitude__range=(min_lat, max_lat),
        longitude__range=(min_lng, max_lng)
    )

    projected_stations = []
    
    # Determine downsample factor for coarse search
    # Target about 500 points for coarse search
    num_points = len(route_points)
    target_coarse_points = 500
    downsample_factor = max(1, num_points // target_coarse_points)
    
    coarse_indices = list(range(0, num_points, downsample_factor))
    # Ensure the last point is included
    if not coarse_indices or coarse_indices[-1] != num_points - 1:
        coarse_indices.append(num_points - 1)

    # Pre-fetch coarse points
    coarse_points = [(route_points[idx], idx) for idx in coarse_indices]

    for station in stations_in_bbox:
        # Step 1: Find the closest point in the coarse set
        min_coarse_dist = float('inf')
        best_coarse_idx = -1
        
        for pt, original_idx in coarse_points:
            dist = haversine(station.latitude, station.longitude, pt[0], pt[1])
            if dist < min_coarse_dist:
                min_coarse_dist = dist
                best_coarse_idx = original_idx
                
        # Step 2: Search in the local neighborhood of the best coarse point
        # Define search window around the best coarse index
        start_search = max(0, best_coarse_idx - downsample_factor)
        end_search = min(num_points, best_coarse_idx + downsample_factor + 1)
        
        min_dist = float('inf')
        closest_idx = -1
        
        for idx in range(start_search, end_search):
            pt = route_points[idx]
            dist = haversine(station.latitude, station.longitude, pt[0], pt[1])
            if dist < min_dist:
                min_dist = dist
                closest_idx = idx
                
        # If the closest point is within the threshold, project the station
        if min_dist <= max_off_route_miles:
            projected_stations.append({
                'station': station,
                'mile_marker': cumulative_distances[closest_idx],
                'off_route_distance': min_dist
            })
            
    # Sort projected stations by their position along the route
    projected_stations.sort(key=lambda x: x['mile_marker'])
    return projected_stations

def plan_fuel_stops(route_points, cumulative_distances, max_range_miles=500.0, mpg=10.0):
    """
    Applies the greedy fuel stop selection algorithm.
    - Start at mile 0 with a full tank (500-mile range).
    - Find cheapest station in the next 500 miles.
    - Stop there, refill, and repeat.
    """
    total_miles = cumulative_distances[-1] if cumulative_distances else 0.0
    total_gallons = total_miles / mpg
    
    # Project all stations onto the route
    projected = project_stations_to_route(route_points, cumulative_distances)
    
    stops = []
    current_mile = 0.0
    
    # If the total route is less than the max range, we can reach without stops.
    if total_miles <= max_range_miles:
        # We don't need any stops, but we still need to calculate the fuel cost.
        # Find the cheapest station along the entire route to calculate the cost.
        if projected:
            cheapest = min(projected, key=lambda x: x['station'].price)
            price = cheapest['station'].price
        else:
            price = 3.50 # Default fallback price if no stations are found along route
        
        total_cost = total_gallons * price
        return {
            'fuel_stops': [],
            'total_miles': round(total_miles, 2),
            'total_gallons': round(total_gallons, 2),
            'total_fuel_cost': round(total_cost, 2)
        }

    total_cost = 0.0
    
    # Loop until the remaining distance to the destination is within max range
    while current_mile + max_range_miles < total_miles:
        # Find all stations within the search window: (current_mile, current_mile + max_range_miles]
        candidates = [
            p for p in projected 
            if current_mile < p['mile_marker'] <= current_mile + max_range_miles
        ]
        
        if not candidates:
            # If no stations are in range, look for any station that is ahead and closest to our limit
            # so we can at least make progress, or fail gracefully.
            # Here we raise a ValueError to indicate it's impossible to complete the route.
            raise ValueError(
                f"No fuel stations found within the {max_range_miles}-mile range from mile marker {round(current_mile, 1)}."
            )
            
        # Select the station with the lowest price
        best_candidate = min(candidates, key=lambda x: x['station'].price)
        best_station = best_candidate['station']
        stop_mile = best_candidate['mile_marker']
        
        # Calculate fuel consumed for this leg
        leg_miles = stop_mile - current_mile
        leg_gallons = leg_miles / mpg
        leg_cost = leg_gallons * best_station.price
        
        stops.append({
            'name': best_station.name,
            'address': best_station.address,
            'city': best_station.city,
            'state': best_station.state,
            'latitude': best_station.latitude,
            'longitude': best_station.longitude,
            'fuel_price': best_station.price,
            'distance_from_start': round(stop_mile, 2),
            'leg_miles': round(leg_miles, 2),
            'leg_gallons': round(leg_gallons, 2),
            'leg_cost': round(leg_cost, 2)
        })
        
        total_cost += leg_cost
        current_mile = stop_mile

    # Final leg: from the last stop to the destination
    final_leg_miles = total_miles - current_mile
    final_leg_gallons = final_leg_miles / mpg
    
    # The price of the fuel for the final leg is the price at the last stop
    if stops:
        last_price = stops[-1]['fuel_price']
    else:
        # If no stops were made (should not happen since L > 500, but just in case)
        if projected:
            last_price = min(projected, key=lambda x: x['station'].price)['station'].price
        else:
            last_price = 3.50
            
    final_leg_cost = final_leg_gallons * last_price
    total_cost += final_leg_cost
    
    return {
        'fuel_stops': stops,
        'total_miles': round(total_miles, 2),
        'total_gallons': round(total_gallons, 2),
        'total_fuel_cost': round(total_cost, 2)
    }
