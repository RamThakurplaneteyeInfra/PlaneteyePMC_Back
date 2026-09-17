"""Shared JWT test helpers for API test cases."""

from django.contrib.auth import get_user_model

User = get_user_model()


def authenticate_client(client, username="test_api_user", password="testpass123"):
    """Create a user if needed, log in via /api/token/, set Bearer header."""
    User.objects.get_or_create(
        username=username,
        defaults={"is_active": True},
    )
    user = User.objects.get(username=username)
    user.set_password(password)
    user.is_active = True
    user.save()

    response = client.post(
        "/api/token/",
        {"username": username, "password": password},
        format="json",
    )
    if response.status_code != 200:
        raise RuntimeError(f"Test login failed: {response.status_code} {response.data}")

    client.credentials(HTTP_AUTHORIZATION=f"Bearer {response.data['access']}")
    return user
