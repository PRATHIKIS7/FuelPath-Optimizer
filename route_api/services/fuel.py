import math
from route_api.models import FuelStation

def haversine(lat1, lon1, lat2, lon2):
    """
    Calculate the great circle distance between two points 
    on the earth (specified in decimal degrees) in miles.
    """
    R = 3958.8
    d_lat = math.radians(lat2 - lat1)
    d_lon = math.radians(lon2 - lon1)
    a = (math.sin(d_lat / 2) ** 2 +
         math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(d_lon / 2) ** 2)
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c


def _route_bounding_box(route_points, buffer_degrees=0.25):
    lats = [pt[0] for pt in route_points]
    lngs = [pt[1] for pt in route_points]
    return (
        min(lats) - buffer_degrees,
        max(lats) + buffer_degrees,
        min(lngs) - buffer_degrees,
        max(lngs) + buffer_degrees,
    )


def _build_coarse_points(route_points, target_coarse_points=500):
    num_points = len(route_points)
    downsample_factor = max(1, num_points // target_coarse_points)
    indices = list(range(0, num_points, downsample_factor))
    if not indices or indices[-1] != num_points - 1:
        indices.append(num_points - 1)
    return [(route_points[idx], idx) for idx in indices]


def _closest_route_point_for_station(station, route_points, coarse_points):
    min_coarse_dist = float('inf')
    best_coarse_idx = 0
    for pt, original_idx in coarse_points:
        dist = haversine(station.latitude, station.longitude, pt[0], pt[1])
        if dist < min_coarse_dist:
            min_coarse_dist = dist
            best_coarse_idx = original_idx

    num_points = len(route_points)
    downsample_factor = max(1, num_points // len(coarse_points))
    start_search = max(0, best_coarse_idx - downsample_factor)
    end_search = min(num_points, best_coarse_idx + downsample_factor + 1)

    min_dist = float('inf')
    closest_idx = best_coarse_idx
    for idx in range(start_search, end_search):
        pt = route_points[idx]
        dist = haversine(station.latitude, station.longitude, pt[0], pt[1])
        if dist < min_dist:
            min_dist = dist
            closest_idx = idx

    return closest_idx, min_dist


def project_stations_to_route(route_points, cumulative_distances, max_off_route_miles=5.0, max_search_radius_miles=30.0):
    """
    Finds stations near the route and projects them onto the closest route point.
    Uses a coarse-to-fine search and optionally widens the corridor for rural paths.
    """
    if not route_points:
        return []

    min_lat, max_lat, min_lng, max_lng = _route_bounding_box(route_points, buffer_degrees=max_off_route_miles / 69.0)
    stations_in_bbox = FuelStation.objects.filter(
        latitude__range=(min_lat, max_lat),
        longitude__range=(min_lng, max_lng)
    ).exclude(latitude__isnull=True, longitude__isnull=True)

    projected_stations = []
    coarse_points = _build_coarse_points(route_points)

    for station in stations_in_bbox:
        closest_idx, min_dist = _closest_route_point_for_station(station, route_points, coarse_points)
        if min_dist <= max_off_route_miles:
            projected_stations.append({
                'station': station,
                'mile_marker': cumulative_distances[closest_idx],
                'off_route_distance': min_dist
            })

    projected_stations.sort(key=lambda x: x['mile_marker'])

    if not projected_stations and max_off_route_miles < max_search_radius_miles:
        return project_stations_to_route(
            route_points,
            cumulative_distances,
            max_off_route_miles=max_search_radius_miles,
            max_search_radius_miles=max_search_radius_miles
        )

    return projected_stations


def _estimate_fallback_price(projected):
    if projected:
        return min(projected, key=lambda x: x['station'].price)['station'].price

    fallback_station = FuelStation.objects.exclude(
        latitude__isnull=True,
        longitude__isnull=True
    ).order_by('price').first()
    return fallback_station.price if fallback_station else 3.50


def plan_fuel_stops(route_points, cumulative_distances, max_range_miles=500.0, mpg=10.0):
    """
    Applies the greedy fuel stop selection algorithm.
    - Start at mile 0 with a full tank (500-mile range).
    - Find the cheapest station in the next 500 miles.
    - Stop there, refill, and repeat.
    """
    total_miles = cumulative_distances[-1] if cumulative_distances else 0.0
    total_gallons = total_miles / mpg
    warnings = []

    projected = project_stations_to_route(route_points, cumulative_distances)
    if not projected:
        warnings.append(
            'No stations found within 5 miles of the route. Expanding search to 30 miles.'
        )
        projected = project_stations_to_route(route_points, cumulative_distances, max_off_route_miles=30.0)

    if total_miles <= max_range_miles:
        price = _estimate_fallback_price(projected)
        total_cost = total_gallons * price
        return {
            'fuel_stops': [],
            'total_miles': round(total_miles, 2),
            'total_gallons': round(total_gallons, 2),
            'total_fuel_cost': round(total_cost, 2),
            'warnings': warnings
        }

    if not projected:
        price = _estimate_fallback_price(projected)
        warnings.append(
            'Unable to locate fuel stations near the route. Fuel cost is estimated using a fallback price.'
        )
        total_cost = total_gallons * price
        return {
            'fuel_stops': [],
            'total_miles': round(total_miles, 2),
            'total_gallons': round(total_gallons, 2),
            'total_fuel_cost': round(total_cost, 2),
            'warnings': warnings
        }

    stops = []
    current_mile = 0.0
    total_cost = 0.0

    while current_mile + max_range_miles < total_miles:
        candidates = [
            p for p in projected
            if current_mile < p['mile_marker'] <= current_mile + max_range_miles
        ]

        if not candidates:
            candidates = [
                p for p in projected
                if p['mile_marker'] > current_mile
            ]
            if candidates:
                warnings.append(
                    'No station was found within the ideal 500-mile range; selecting the next available station ahead.'
                )
                candidates.sort(key=lambda p: p['mile_marker'])
                candidates = candidates[:10]

        if not candidates:
            warnings.append(
                'Unable to continue planning fuel stops for this route; using estimated fuel cost instead.'
            )
            price = _estimate_fallback_price(projected)
            total_cost = total_gallons * price
            return {
                'fuel_stops': stops,
                'total_miles': round(total_miles, 2),
                'total_gallons': round(total_gallons, 2),
                'total_fuel_cost': round(total_cost, 2),
                'warnings': warnings
            }

        best_candidate = min(candidates, key=lambda x: x['station'].price)
        best_station = best_candidate['station']
        stop_mile = best_candidate['mile_marker']

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

    final_leg_miles = total_miles - current_mile
    final_leg_gallons = final_leg_miles / mpg

    if stops:
        last_price = stops[-1]['fuel_price']
    else:
        last_price = _estimate_fallback_price(projected)

    final_leg_cost = final_leg_gallons * last_price
    total_cost += final_leg_cost

    return {
        'fuel_stops': stops,
        'total_miles': round(total_miles, 2),
        'total_gallons': round(total_gallons, 2),
        'total_fuel_cost': round(total_cost, 2),
        'warnings': warnings
    }
