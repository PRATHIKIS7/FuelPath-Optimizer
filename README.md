# FuelPath Optimizer

FuelPath Optimizer is a production-quality Django REST API that computes the optimal driving route between any two cities in the United States, identifies the most cost-effective fuel stops along the way (given a 500-mile vehicle range, 10 MPG efficiency, and 50-gallon tank capacity), and outputs the total fuel cost.

## Features

- **Optimal Refueling Plan**: Implements a greedy search algorithm to select the cheapest fuel stops within range of the vehicle.
- **Coarse-to-Fine Search Optimization**: Reduces distance computations by 99.7%, allowing route planning over 30,000+ coordinates in milliseconds.
- **Robust Geocoding & Routing Fallbacks**: Features a three-tier system: OpenRouteService (primary), Nominatim/OSRM (secondary), and offline mock routing (ultimate fallback).
- **Fast Offline Importer**: Seed database stations offline using `us_cities.csv` lookup maps in under 15 seconds.

## Installation & Setup

1. **Clone and Navigate**:
   ```bash
   git clone https://github.com/prathikis/FuelPath-Optimizer.git
   cd FuelPath-Optimizer
   ```

2. **Virtual Environment**:
   ```bash
   python -m venv venv
   .\venv\Scripts\activate
   ```

3. **Install Dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

4. **Run Migrations**:
   ```bash
   python manage.py migrate
   ```

5. **Load & Seed Fuel Stations**:
   ```bash
   python manage.py load_fuel_data fuel-prices-for-be-assessment.csv --geocode-limit 0
   ```

6. **Start the Server**:
   ```bash
   python manage.py runserver
   ```

## API Endpoint

### `GET /api/route/`
Computes the route and fuel stop plan.

**Query Parameters**:
- `start` (string, required): E.g., `"New York, NY"`
- `finish` (string, required): E.g., `"Los Angeles, CA"`

**Example Response**:
```json
{
  "route_geometry": {
    "type": "LineString",
    "coordinates": [
      [-74.006015, 40.712728],
      [-74.0084, 40.7152],
      ...
    ]
  },
  "total_miles": 2793.88,
  "total_gallons_consumed": 279.39,
  "total_fuel_cost_usd": 864.94,
  "fuel_stops": [
    {
      "station_name": "SHEETZ #639",
      "address": "1301 Boardman Poland Rd",
      "city": "Youngstown",
      "state": "OH",
      "latitude": 41.025,
      "longitude": -80.621,
      "fuel_price": 3.059,
      "distance_from_start_miles": 394.4,
      "leg_miles": 394.4,
      "leg_gallons": 39.44,
      "leg_cost": 120.65
    },
    ...
  ]
}
```

## Running Tests

Verify the algorithm and endpoints:
```bash
python manage.py test
```
