from django.test import TestCase, Client
from django.urls import reverse
from rest_framework import status
from route_api.models import FuelStation
from route_api.services.fuel import plan_fuel_stops, project_stations_to_route
from route_api.services.routing import get_route


class FuelStopAlgorithmTestCase(TestCase):
    def setUp(self):
        # Create some mock fuel stations along a simulated route
        # Let's say the route goes from (0.0, 0.0) to (0.0, 15.0) which is approx 1000 miles.
        # We will place stations at regular intervals.
        # Note: 1 degree latitude = 69 miles. 1 degree longitude at equator = 69 miles.
        # For simplicity, we'll place stations and project them.
        
        # Station at mile 300 (approx 4.35 degrees east)
        self.station1 = FuelStation.objects.create(
            opis_id=1,
            name="Cheapest Stop 1",
            address="100 Interstate 80",
            city="StationOne",
            state="WY",
            latitude=0.01, # very close to the route
            longitude=4.35,
            price=2.50
        )
        
        # Expensive station at mile 300
        self.station1_expensive = FuelStation.objects.create(
            opis_id=2,
            name="Expensive Stop 1",
            address="102 Interstate 80",
            city="StationOne",
            state="WY",
            latitude=-0.01,
            longitude=4.35,
            price=4.00
        )

        # Station at mile 700 (approx 10.15 degrees east)
        self.station2 = FuelStation.objects.create(
            opis_id=3,
            name="Cheapest Stop 2",
            address="200 Interstate 80",
            city="StationTwo",
            state="NE",
            latitude=0.015,
            longitude=10.15,
            price=3.00
        )
        
        # Route points and cumulative distances
        # 0.0 to 15.0 degrees longitude. Total distance is approx 15 * 69.17 = 1037 miles.
        self.route_points = [(0.0, float(x) * 0.1) for x in range(151)]
        
        # Calculate cumulative distances manually for testing
        self.cumulative_distances = [0.0]
        total_dist = 0.0
        from route_api.services.fuel import haversine
        for i in range(1, len(self.route_points)):
            total_dist += haversine(
                self.route_points[i-1][0], self.route_points[i-1][1],
                self.route_points[i][0], self.route_points[i][1]
            )
            self.cumulative_distances.append(total_dist)

    def test_project_stations_to_route(self):
        projected = project_stations_to_route(self.route_points, self.cumulative_distances)
        # All three stations should be projected because they are close to the route (within 5 miles)
        self.assertEqual(len(projected), 3)
        
        # Verify they are ordered by mile_marker
        self.assertLess(projected[0]['mile_marker'], projected[2]['mile_marker'])

    def test_plan_fuel_stops_long_route(self):
        # Run fuel stop planner for the 1000+ mile route
        result = plan_fuel_stops(
            self.route_points, 
            self.cumulative_distances, 
            max_range_miles=500.0, 
            mpg=10.0
        )
        
        # We start with 500 range. We must refuel before mile 500.
        # The cheapest station in (0, 500] is station1 at price 2.50.
        # After refueling at station1 (~mile 300), we have 500 miles range (can reach up to 800).
        # We must refuel again before mile 800.
        # The cheapest station in (300, 800] is station2 at price 3.00 (~mile 700).
        # From mile 700, we have 500 miles range (can reach up to 1200), which gets us to the end (~1037 miles).
        
        self.assertEqual(len(result['fuel_stops']), 2)
        
        # Verify first stop is cheapest one
        self.assertEqual(result['fuel_stops'][0]['name'], "Cheapest Stop 1")
        self.assertEqual(result['fuel_stops'][0]['fuel_price'], 2.50)
        
        # Verify second stop
        self.assertEqual(result['fuel_stops'][1]['name'], "Cheapest Stop 2")
        self.assertEqual(result['fuel_stops'][1]['fuel_price'], 3.00)

        # Verify total miles, gallons and cost
        # total gallons = total_miles / 10.0
        self.assertAlmostEqual(result['total_gallons'], self.cumulative_distances[-1] / 10.0, places=1)


class RouteViewTestCase(TestCase):
    def setUp(self):
        self.client = Client()
        # Seed a station
        FuelStation.objects.create(
            opis_id=10,
            name="Test Stop",
            address="Interstate 70",
            city="Greenfield",
            state="IN",
            latitude=39.785,
            longitude=-85.769,
            price=3.00
        )

    def test_missing_params(self):
        url = reverse('route_optimizer')
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("error", response.data)

    def test_valid_route_request(self):
        # Get actual route points to seed stations exactly on them
        route_points, cumulative_distances = get_route('New York, NY', 'Los Angeles, CA')
        
        # Seed a station every 250 miles along the actual route
        last_seeded_mile = 0.0
        # Seed a starting station close to mile 200
        for idx, pt in enumerate(route_points):
            mile = cumulative_distances[idx]
            if mile - last_seeded_mile >= 250.0:
                FuelStation.objects.create(
                    opis_id=100 + idx,
                    name=f"Route Stop at Mile {round(mile, 1)}",
                    address="123 Route Hwy",
                    city="Highway City",
                    state="KS",
                    latitude=pt[0],
                    longitude=pt[1],
                    price=3.00
                )
                last_seeded_mile = mile

        url = reverse('route_optimizer')
        response = self.client.get(url, {
            'start': 'New York, NY',
            'finish': 'Los Angeles, CA'
        })
        if response.status_code != status.HTTP_200_OK:
            print("Response error data:", response.data)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("route_geometry", response.data)
        self.assertIn("total_miles", response.data)
        self.assertIn("total_gallons_consumed", response.data)
        self.assertIn("total_fuel_cost_usd", response.data)
        self.assertIn("fuel_stops", response.data)

    def test_short_route_request(self):
        url = reverse('route_optimizer')
        response = self.client.get(url, {
            'start': 'New York, NY',
            'finish': 'Newark, NJ'
        })
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data['fuel_stops']), 0)

