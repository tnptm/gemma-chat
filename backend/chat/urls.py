from django.urls import path
from rest_framework.routers import SimpleRouter

from .views import ChatModelView, ConversationViewSet

router = SimpleRouter(trailing_slash=False)
router.register("conversations", ConversationViewSet, basename="conversation")
urlpatterns = [path("chat/model", ChatModelView.as_view())] + router.urls
