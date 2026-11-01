import re

from django.conf import settings
from django.http import StreamingHttpResponse
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView

from control.models import OllamaConfig

from . import ollama
from .models import Conversation, Message
from .serializers import ChatInputSerializer, ConversationDetailSerializer, ConversationSerializer


def markdown_text(value):
    """Plain text that can't open links, emphasis or HTML in the rendered Markdown."""
    return re.sub(r"([\\`*_\[\]<>#|~])", r"\\\1", " ".join(value.split()))


def format_sources(sources):
    lines = [f"- [{markdown_text(title)[:120]}](<{url}>)" for title, url in sources
             if url.startswith(("http://", "https://")) and not re.search(r"[\s<>]", url)]
    return "\n\n**Sources**\n" + "\n".join(lines) if lines else ""


class ChatModelView(APIView):
    """The model chat currently uses (selected in the admin dashboard), for the chat UI."""

    def get(self, request):
        return Response({"model": OllamaConfig.load().active_model or None})


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
        cfg = OllamaConfig.load()  # model, host and context length come from the dashboard
        if not cfg.active_model:
            return Response({"detail": "No chat model is selected. An admin can choose one in the Ollama dashboard."},
                            status=409)

        Message.objects.create(conversation=conv, role=Message.Role.USER, content=content)
        if conv.title == "New chat":
            conv.title = content[:60]
        conv.save()  # bumps updated_at

        recent = conv.messages.order_by("-created_at", "-id")[: settings.CHAT_HISTORY_LIMIT]
        payload = [{"role": "system", "content": ollama.system_prompt()}]
        payload += [{"role": m.role, "content": m.content} for m in reversed(list(recent))]

        def stream():
            parts = []  # what gets saved: the answer and its sources, not the progress lines
            try:
                for kind, value in ollama.stream_chat(payload, cfg):
                    if kind == "text":
                        parts.append(value)
                        yield value
                    elif kind == "search":
                        yield f"_Searching the web: {markdown_text(value)}…_\n\n"
                    elif kind == "sources":
                        block = format_sources(value)
                        parts.append(block)
                        yield block
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
