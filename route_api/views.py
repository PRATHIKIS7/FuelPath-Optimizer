from django.shortcuts import render
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from route_api.services.routing import get_route
from route_api.services.fuel import plan_fuel_stops


def home(request):
    return render(request, 'route_api/index.html')


class RouteView(APIView):
    authentication_classes = []
    permission_classes = []
    """
    API endpoint that accepts start and end locations,
    computes the optimal driving route, and plans the most cost-effective fuel stops.
    """
    def get(self, request, *args, **kwargs):
        start = request.query_params.get('start') or request.GET.get('start')
        finish = request.query_params.get('finish') or request.GET.get('finish')
        
        if not start or not finish:
            return Response(
                {
                    "error": "Both 'start' and 'finish' query parameters are required.",
                    "received_start": start,
                    "received_finish": finish,
                    "query_string": request.META.get('QUERY_STRING', '')
                },
                status=status.HTTP_400_BAD_REQUEST
            )
            
        try:
            # 1. Fetch route points and cumulative distances
            route_points, cumulative_distances = get_route(start, finish)
            
            if not route_points:
                return Response(
                    {"error": "Unable to calculate route between the specified locations."},
                    status=status.HTTP_422_UNPROCESSABLE_ENTITY
                )
                
            # 2. Plan optimal fuel stops
            result = plan_fuel_stops(route_points, cumulative_distances)
            
            # Format route coordinates for GeoJSON (longitude, latitude)
            # route_points is in (latitude, longitude) format, so we map to [lng, lat]
            geometry_coordinates = [[pt[1], pt[0]] for pt in route_points]
            
            # 3. Build response payload
            response_data = {
                "route_geometry": {
                    "type": "LineString",
                    "coordinates": geometry_coordinates
                },
                "total_miles": result['total_miles'],
                "total_gallons_consumed": result['total_gallons'],
                "total_fuel_cost_usd": result['total_fuel_cost'],
                "fuel_stops": [
                    {
                        "station_name": stop['name'],
                        "address": stop['address'],
                        "city": stop['city'],
                        "state": stop['state'],
                        "latitude": stop['latitude'],
                        "longitude": stop['longitude'],
                        "fuel_price": stop['fuel_price'],
                        "distance_from_start_miles": stop['distance_from_start'],
                        "leg_miles": stop['leg_miles'],
                        "leg_gallons": stop['leg_gallons'],
                        "leg_cost": stop['leg_cost']
                    }
                    for stop in result['fuel_stops']
                ],
                "warnings": result.get('warnings', [])
            }
            
            return Response(response_data, status=status.HTTP_200_OK)
            
        except ValueError as ex:
            return Response(
                {"error": str(ex)},
                status=status.HTTP_400_BAD_REQUEST
            )
        except Exception as ex:
            return Response(
                {"error": f"An unexpected error occurred: {str(ex)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
