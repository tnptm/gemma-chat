import re
from pathlib import Path

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator, RegexValidator
from django.db import models

host_validator = RegexValidator(
    r"^(127\.0\.0\.1|localhost|\[::1\]):\d{2,5}$",
    "Host must be a loopback address with port, e.g. 127.0.0.1:11434.",
)
model_validator = RegexValidator(r"^[A-Za-z0-9._\-:/]{1,100}$", "Invalid model name.")
keep_alive_validator = RegexValidator(r"^(-1|\d+[smh]?)$", "Use e.g. 5m, 30s, 1h, 0 or -1.")


def validate_models_dir(value):
    if value and ("\0" in value or not Path(value).is_absolute()):
        raise ValidationError("Use an absolute path.")


class OllamaConfig(models.Model):
    """Single-row table (pk=1) with the settings the dashboard controls."""

    host = models.CharField(max_length=64, default="127.0.0.1:11434", validators=[host_validator])
    active_model = models.CharField(max_length=100, blank=True, validators=[model_validator])
    context_length = models.PositiveIntegerField(default=8192, validators=[MinValueValidator(512), MaxValueValidator(262144)])
    models_dir = models.CharField(max_length=500, blank=True, validators=[validate_models_dir])
    keep_alive = models.CharField(max_length=16, default="5m", validators=[keep_alive_validator])
    num_parallel = models.PositiveSmallIntegerField(default=1, validators=[MinValueValidator(1), MaxValueValidator(8)])
    max_loaded_models = models.PositiveSmallIntegerField(default=1, validators=[MinValueValidator(1), MaxValueValidator(4)])
    flash_attention = models.BooleanField(default=False)
    updated_at = models.DateTimeField(auto_now=True)

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)

    @classmethod
    def load(cls):
        obj, _ = cls.objects.get_or_create(pk=1, defaults={"active_model": settings.OLLAMA_MODEL})
        return obj

    def keep_alive_value(self):
        return int(self.keep_alive) if re.fullmatch(r"-?\d+", self.keep_alive) else self.keep_alive

    def env(self):
        """Environment variables for `ollama serve` (fixed allowlist, validated values)."""
        env = {
            "OLLAMA_HOST": self.host,
            "OLLAMA_CONTEXT_LENGTH": str(self.context_length),
            "OLLAMA_KEEP_ALIVE": self.keep_alive,
            "OLLAMA_NUM_PARALLEL": str(self.num_parallel),
            "OLLAMA_MAX_LOADED_MODELS": str(self.max_loaded_models),
            "OLLAMA_FLASH_ATTENTION": "1" if self.flash_attention else "0",
        }
        if self.models_dir:
            env["OLLAMA_MODELS"] = self.models_dir
        return env
