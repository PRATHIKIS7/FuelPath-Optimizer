import csv
import os
import time
import requests
from django.core.management.base import BaseCommand
from django.conf import settings
from route_api.models import FuelStation

class Command(BaseCommand):
    help = 'Load fuel stations from CSV file, deduplicate, and geocode coordinates'

    def add_arguments(self, parser):
        parser.add_argument('csv_file', type=str, help='Path to the fuel prices CSV file')
        parser.add_argument('--limit', type=int, default=None, help='Limit the number of stations imported')
        parser.add_argument('--geocode-limit', type=int, default=100, help='Limit the number of live API geocoding calls during import')

    def handle(self, *args, **options):
        csv_file_path = options['csv_file']
        limit = options['limit']
        geocode_limit = options['geocode_limit']

        self.stdout.write(self.style.WARNING(f"Reading CSV file from: {csv_file_path}..."))

        # Load US cities database for fast offline geocoding / fallback
        city_coords = {}
        cities_db_path = 'us_cities.csv'
        if os.path.exists(cities_db_path):
            self.stdout.write(self.style.WARNING("Loading offline US cities database..."))
            with open(cities_db_path, mode='r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    city_key = (row['CITY'].strip().lower(), row['STATE_CODE'].strip().upper())
                    try:
                        city_coords[city_key] = (float(row['LATITUDE']), float(row['LONGITUDE']))
                    except ValueError:
                        continue
            self.stdout.write(self.style.SUCCESS(f"Loaded {len(city_coords)} offline city coordinates."))
        else:
            self.stdout.write(self.style.ERROR("Offline US cities database (us_cities.csv) not found!"))

        # Step 1: Read and deduplicate CSV (keep lowest price for each OPIS Truckstop ID)
        stations_data = {}
        try:
            with open(csv_file_path, mode='r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    try:
                        opis_id = int(row['OPIS Truckstop ID'])
                        name = row['Truckstop Name'].strip()
                        address = row['Address'].strip()
                        city = row['City'].strip()
                        state = row['State'].strip()
                        price = float(row['Retail Price'])
                    except (ValueError, KeyError):
                        continue

                    # If already seen, keep the one with lowest price
                    if opis_id in stations_data:
                        if price < stations_data[opis_id]['price']:
                            stations_data[opis_id]['price'] = price
                    else:
                        stations_data[opis_id] = {
                            'name': name,
                            'address': address,
                            'city': city,
                            'state': state,
                            'price': price
                        }
        except FileNotFoundError:
            self.stdout.write(self.style.ERROR(f"File not found: {csv_file_path}"))
            return

        total_stations = len(stations_data)
        self.stdout.write(self.style.SUCCESS(f"Found {total_stations} unique stations after deduplication."))

        # Apply limit if specified
        station_items = list(stations_data.items())
        if limit:
            station_items = station_items[:limit]
            self.stdout.write(self.style.WARNING(f"Limiting import to first {limit} stations."))

        # Step 2: Load into Database and Geocode
        api_key = getattr(settings, 'ORS_API_KEY', '')
        geocoded_count = 0
        saved_count = 0

        self.stdout.write(self.style.WARNING("Starting database import and geocoding..."))

        # Simple state capital coordinates database for fallback
        state_fallbacks = {
            'AL': (32.3615, -86.2791), 'AK': (58.3019, -134.4197), 'AZ': (33.4484, -112.0740),
            'AR': (34.7465, -92.2896), 'CA': (38.5816, -121.4944), 'CO': (39.7392, -104.9903),
            'CT': (41.7637, -72.6851), 'DE': (39.1582, -75.5244), 'FL': (30.4383, -84.2807),
            'GA': (33.7490, -84.3880), 'HI': (21.3069, -157.8583), 'ID': (43.6150, -116.2023),
            'IL': (39.7817, -89.6501), 'IN': (39.7684, -86.1581), 'IA': (41.5868, -93.6250),
            'KS': (39.0473, -95.6752), 'KY': (38.2009, -84.8733), 'LA': (30.4515, -91.1871),
            'ME': (44.3106, -69.7795), 'MD': (38.9784, -76.4922), 'MA': (42.3601, -71.0589),
            'MI': (42.7325, -84.5555), 'MN': (44.9537, -93.0900), 'MS': (32.2988, -90.1848),
            'MO': (38.5767, -92.1735), 'MT': (46.5891, -112.0391), 'NE': (40.8258, -96.6852),
            'NV': (39.1638, -119.7674), 'NH': (43.2081, -71.5375), 'NJ': (40.2170, -74.7429),
            'NM': (35.6870, -105.9378), 'NY': (42.6526, -73.7562), 'NC': (35.7796, -78.6382),
            'ND': (46.8083, -100.7837), 'OH': (39.9612, -82.9988), 'OK': (35.4676, -97.5164),
            'OR': (44.9429, -123.0351), 'PA': (40.2732, -76.8867), 'RI': (41.8240, -71.4128),
            'SC': (34.0007, -81.0348), 'SD': (44.3673, -100.3364), 'TN': (36.1627, -86.7816),
            'TX': (30.2672, -97.7431), 'UT': (40.7608, -111.8910), 'VT': (44.2601, -72.5750),
            'VA': (37.5407, -77.4360), 'WA': (47.0379, -122.9007), 'WV': (38.3498, -81.6326),
            'WI': (43.0731, -89.4012), 'WY': (41.1400, -104.8203)
        }

        for opis_id, data in station_items:
            # Check if station already exists
            station, created = FuelStation.objects.get_or_create(
                opis_id=opis_id,
                defaults={
                    'name': data['name'],
                    'address': data['address'],
                    'city': data['city'],
                    'state': data['state'],
                    'price': data['price']
                }
            )

            # Update price if it has changed and station already existed
            if not created and station.price != data['price']:
                station.price = data['price']
                station.save(update_fields=['price'])

            # If the station doesn't have lat/lng, try to geocode it
            if station.latitude is None or station.longitude is None:
                lat, lng = None, None
                
                # Try live API geocoding first (limited to avoid quota exhaustion)
                if api_key and geocoded_count < geocode_limit:
                    lat, lng = self.geocode_ors(data['address'], data['city'], data['state'], api_key)
                    if lat and lng:
                        geocoded_count += 1
                        time.sleep(0.5)
                
                # Fallback to Nominatim if ORS failed or key missing
                if (not lat or not lng) and geocoded_count < geocode_limit:
                    lat, lng = self.geocode_nominatim(data['address'], data['city'], data['state'])
                    if lat and lng:
                        geocoded_count += 1
                        time.sleep(1.0)

                # Fallback to offline city database
                if not lat or not lng:
                    city_key = (data['city'].strip().lower(), data['state'].strip().upper())
                    if city_key in city_coords:
                        lat, lng = city_coords[city_key]
                        # Add a tiny random offset so stations aren't exactly on top of each other
                        import random
                        lat += random.uniform(-0.005, 0.005)
                        lng += random.uniform(-0.005, 0.005)

                # Ultimate fallback to state center if geocoding failed/limited
                if not lat or not lng:
                    state_code = data['state'].strip().upper()
                    if state_code in state_fallbacks:
                        import random
                        lat_offset = random.uniform(-0.1, 0.1)
                        lng_offset = random.uniform(-0.1, 0.1)
                        lat = state_fallbacks[state_code][0] + lat_offset
                        lng = state_fallbacks[state_code][1] + lng_offset
                    else:
                        # US center fallback
                        lat = 39.8283
                        lng = -98.5795

                station.latitude = lat
                station.longitude = lng
                station.save(update_fields=['latitude', 'longitude'])

            saved_count += 1
            if saved_count % 100 == 0:
                self.stdout.write(f"Processed {saved_count}/{len(station_items)} stations...")

        self.stdout.write(self.style.SUCCESS(
            f"Successfully loaded {saved_count} stations. Geocoded {geocoded_count} stations via APIs."
        ))

    def geocode_ors(self, address, city, state, api_key):
        query = f"{address}, {city}, {state}, USA"
        url = "https://api.openrouteservice.org/geocode/search"
        params = {
            'api_key': api_key,
            'text': query,
            'size': 1
        }
        try:
            response = requests.get(url, params=params, timeout=5)
            if response.status_code == 200:
                data = response.json()
                features = data.get('features', [])
                if features:
                    coords = features[0]['geometry']['coordinates']
                    # GeoJSON is [lng, lat]
                    return coords[1], coords[0]
        except Exception:
            pass
        return None, None

    def geocode_nominatim(self, address, city, state):
        query = f"{address}, {city}, {state}, USA"
        url = "https://nominatim.openstreetmap.org/search"
        headers = {
            'User-Agent': 'SpotterFuelCostOptimizer/1.0 (contact@spotter.com)'
        }
        params = {
            'q': query,
            'format': 'json',
            'limit': 1
        }
        try:
            response = requests.get(url, headers=headers, params=params, timeout=5)
            if response.status_code == 200:
                data = response.json()
                if data:
                    return float(data[0]['lat']), float(data[0]['lon'])
        except Exception:
            pass
        return None, None
