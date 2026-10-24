from rest_framework import serializers

from .models import OllamaConfig, model_validator


class ConfigSerializer(serializers.ModelSerializer):
    class Meta:
        model = OllamaConfig
        fields = ["host", "active_model", "context_length", "models_dir", "keep_alive",
                  "num_parallel", "max_loaded_models", "flash_attention"]


class ModelNameSerializer(serializers.Serializer):
    model = serializers.CharField(max_length=100, validators=[model_validator])
