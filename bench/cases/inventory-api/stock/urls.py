from django.urls import path

from stock import views

urlpatterns = [path("items/", views.item_list)]
