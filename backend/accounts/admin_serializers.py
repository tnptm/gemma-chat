from django.contrib.auth import get_user_model, password_validation
from rest_framework import serializers

User = get_user_model()


class UserManagementSerializer(serializers.ModelSerializer):
    password = serializers.CharField(
        write_only=True, required=False, allow_blank=False, min_length=12
    )
    is_admin = serializers.BooleanField(source="is_staff", default=False)

    class Meta:
        model = User
        fields = ["id", "username", "email", "password", "is_admin", "date_joined"]
        read_only_fields = ["id", "date_joined"]

    def validate_password(self, value):
        password_validation.validate_password(value, user=self.instance)
        return value

    def validate(self, attrs):
        if self.instance is None and not attrs.get("password"):
            raise serializers.ValidationError({"password": "This field is required."})
        return attrs

    def create(self, validated_data):
        password = validated_data.pop("password")
        user = User(**validated_data)
        user.set_password(password)
        user.save()
        return user

    def update(self, instance, validated_data):
        password = validated_data.pop("password", None)
        for field, value in validated_data.items():
            setattr(instance, field, value)
        if password:
            instance.set_password(password)
        instance.save()
        return instance
