from django.urls import path
from route_api.views import RouteView, home

urlpatterns = [
    path('', home, name='home'),
    path('route/', RouteView.as_view(), name='route_optimizer'),
]
