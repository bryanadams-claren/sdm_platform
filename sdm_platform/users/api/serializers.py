from rest_framework import serializers

from sdm_platform.users.models import User


class UserSerializer(serializers.ModelSerializer[User]):
    class Meta:  # pyright: ignore[reportIncompatibleVariableOverride]
        model = User
        fields = ["name", "url"]

        extra_kwargs = {
            "url": {"view_name": "api:user-detail", "lookup_field": "pk"},
        }
