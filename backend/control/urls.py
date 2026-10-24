from django.urls import path

from . import views

urlpatterns = [
    path("status", views.StatusView.as_view()),
    path("config", views.ConfigView.as_view()),
    path("start", views.StartView.as_view()),
    path("stop", views.StopView.as_view()),
    path("restart", views.RestartView.as_view()),
    path("models/load", views.LoadView.as_view()),
    path("models/unload", views.UnloadView.as_view()),
    path("logs", views.LogsView.as_view()),
]
