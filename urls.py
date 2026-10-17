from django.urls import path

from . import views

app_name = "events"

urlpatterns = [
    path("", views.home, name="home"),
    path("events/", views.event_list, name="list"),
    path("events/create/", views.event_create, name="create"),
    path("events/<slug:slug>/", views.event_detail, name="detail"),
    path("events/<slug:slug>/edit/", views.event_edit, name="edit"),
    path("events/<slug:slug>/publish/", views.event_publish, name="publish"),
    path("events/<slug:slug>/cancel/", views.event_cancel, name="cancel"),
]
