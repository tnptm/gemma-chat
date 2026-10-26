from django.contrib.auth import get_user_model
from django.shortcuts import get_object_or_404
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from .admin_serializers import UserManagementSerializer
from .permissions import IsAppAdmin

User = get_user_model()


class UserListView(APIView):
    permission_classes = [IsAppAdmin]
    throttle_scope = "admin"

    def get(self, request):
        users = User.objects.order_by("username")
        return Response(UserManagementSerializer(users, many=True).data)

    def post(self, request):
        serializer = UserManagementSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        return Response(UserManagementSerializer(user).data, status=201)


class UserDetailView(APIView):
    permission_classes = [IsAppAdmin]
    throttle_scope = "admin"

    def patch(self, request, pk):
        user = get_object_or_404(User, pk=pk)
        serializer = UserManagementSerializer(user, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        if user.pk == request.user.pk and serializer.validated_data.get("is_staff") is False:
            raise ValidationError({"is_admin": "You cannot remove your own administrator access."})
        return Response(UserManagementSerializer(serializer.save()).data)

    def delete(self, request, pk):
        user = get_object_or_404(User, pk=pk)
        if user.pk == request.user.pk:
            raise ValidationError({"detail": "You cannot delete your own account."})
        user.delete()
        return Response(status=204)
