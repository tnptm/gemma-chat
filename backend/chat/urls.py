from rest_framework.routers import SimpleRouter

from .views import ConversationViewSet

router = SimpleRouter(trailing_slash=False)
router.register("conversations", ConversationViewSet, basename="conversation")
urlpatterns = router.urls
