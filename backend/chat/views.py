from django.conf import settings
from django.http import StreamingHttpResponse
from rest_framework import viewsets
from rest_framework.decorators import action

from . import ollama
from .models import Conversation, Message
from .serializers import ChatInputSerializer, ConversationDetailSerializer, ConversationSerializer


class ConversationViewSet(viewsets.ModelViewSet):
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]
    throttle_scope = None  # overridden per action (see chat)

    def get_queryset(self):
        # Every query is scoped to the logged-in user
        return Conversation.objects.filter(user=self.request.user)

    def get_serializer_class(self):
        return ConversationDetailSerializer if self.action == "retrieve" else ConversationSerializer

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)

    @action(detail=True, methods=["post"], throttle_scope="chat")
    def chat(self, request, pk=None):
        conv = self.get_object()
        ser = ChatInputSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        content = ser.validated_data["content"].strip()

        Message.objects.create(conversation=conv, role=Message.Role.USER, content=content)
        if conv.title == "New chat":
            conv.title = content[:60]
        conv.save()  # bumps updated_at

        recent = conv.messages.order_by("-created_at", "-id")[: settings.CHAT_HISTORY_LIMIT]
        payload = [{"role": "system", "content": settings.CHAT_SYSTEM_PROMPT}]
        payload += [{"role": m.role, "content": m.content} for m in reversed(list(recent))]

        def stream():
            parts = []
            try:
                for piece in ollama.stream_chat(payload):
                    parts.append(piece)
                    yield piece
            except ollama.OllamaError as exc:
                yield f"\n\n[Error: {exc}]"
            finally:  # also runs if the client hits "stop"
                text = "".join(parts).strip()
                if text:
                    Message.objects.create(conversation=conv, role=Message.Role.ASSISTANT, content=text)
                    conv.save()

        resp = StreamingHttpResponse(stream(), content_type="text/plain; charset=utf-8")
        resp["Cache-Control"] = "no-cache"
        resp["X-Accel-Buffering"] = "no"
        return resp
