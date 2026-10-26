from rest_framework.response import Response
from rest_framework.views import APIView

from . import services
from .models import OllamaConfig
from .serializers import ConfigSerializer, ModelNameSerializer
from accounts.permissions import IsAppAdmin


class AdminView(APIView):
    permission_classes = [IsAppAdmin]
    throttle_scope = "admin"

    def full_status(self, cfg):
        return {**services.status(cfg), "config": ConfigSerializer(cfg).data}

    def run(self, fn, *args):
        cfg = OllamaConfig.load()
        try:
            fn(cfg, *args)
        except services.ServiceError as exc:
            return Response({"detail": str(exc)}, status=409)
        return Response(self.full_status(cfg))


class StatusView(AdminView):
    def get(self, request):
        return Response(self.full_status(OllamaConfig.load()))


class ConfigView(AdminView):
    def get(self, request):
        return Response(ConfigSerializer(OllamaConfig.load()).data)

    def patch(self, request):
        ser = ConfigSerializer(OllamaConfig.load(), data=request.data, partial=True)
        ser.is_valid(raise_exception=True)
        ser.save()
        return Response(ser.data)


class StartView(AdminView):
    def post(self, request):
        return self.run(services.start)


class StopView(AdminView):
    def post(self, request):
        return self.run(services.stop)


class RestartView(AdminView):
    def post(self, request):
        return self.run(services.restart)


class LoadView(AdminView):
    def post(self, request):
        ser = ModelNameSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        return self.run(services.set_loaded, ser.validated_data["model"], True)


class UnloadView(AdminView):
    def post(self, request):
        ser = ModelNameSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        return self.run(services.set_loaded, ser.validated_data["model"], False)


class LogsView(AdminView):
    def get(self, request):
        try:
            return Response({"lines": services.log_tail()})
        except services.ServiceError as exc:
            return Response({"detail": str(exc)}, status=409)
