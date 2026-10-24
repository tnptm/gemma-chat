from django.urls import include, path

urlpatterns = [
    path("api/auth/", include("accounts.urls")),
    path("api/admin/ollama/", include("control.urls")),
    path("api/", include("chat.urls")),
]
