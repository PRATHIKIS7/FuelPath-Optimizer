from django.db import models

class FuelStation(models.Model):
    opis_id = models.IntegerField(unique=True, primary_key=True)
    name = models.CharField(max_length=255)
    address = models.CharField(max_length=255)
    city = models.CharField(max_length=100)
    state = models.CharField(max_length=50)
    latitude = models.FloatField(null=True, blank=True)
    longitude = models.FloatField(null=True, blank=True)
    price = models.FloatField()

    def __str__(self):
        return f"{self.name} - {self.city}, {self.state} (${self.price})"
