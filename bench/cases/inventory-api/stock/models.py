from django.db import models


class Item(models.Model):
    sku = models.CharField(max_length=40, unique=True)
    quantity = models.IntegerField()
    updated = models.DateTimeField(auto_now=True)
