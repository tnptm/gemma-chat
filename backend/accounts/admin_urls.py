from django.urls import path

from . import admin_views

urlpatterns = [
    path("", admin_views.UserListView.as_view()),
    path("<int:pk>", admin_views.UserDetailView.as_view()),
]
