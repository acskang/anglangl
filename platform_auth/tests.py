from http import HTTPStatus
from urllib.error import HTTPError

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse


class DummyResponse:
    def __init__(self, payload):
        self.payload = payload

    def read(self):
        import json

        return json.dumps(self.payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class DummyHTTPError(HTTPError):
    def __init__(self, payload, status=HTTPStatus.UNAUTHORIZED):
        import io
        import json

        super().__init__(
            url="http://127.0.0.1/api/v1/auth/login/",
            code=status,
            msg="error",
            hdrs=None,
            fp=io.BytesIO(json.dumps(payload).encode("utf-8")),
        )


class ThePeachAuthViewsTests(TestCase):
    def setUp(self):
        self.client = Client()

    def test_login_creates_shadow_user_and_session(self):
        from unittest.mock import patch

        with patch("platform_auth.services.urlopen") as mock_urlopen:
            mock_urlopen.side_effect = [
                DummyResponse(
                    {
                        "success": True,
                        "data": {
                            "access": "access-token",
                            "refresh": "refresh-token",
                            "user": {"id": "tp-1", "email": "user@example.com", "display_name": "User"},
                        },
                    }
                ),
                DummyResponse(
                    {
                        "success": True,
                        "data": {
                            "id": "tp-1",
                            "email": "user@example.com",
                            "display_name": "User",
                            "full_name": "User Example",
                            "first_name": "User",
                            "last_name": "Example",
                            "is_active": True,
                        },
                    }
                ),
            ]

            response = self.client.post(
                reverse("platform_auth:login"),
                {"email": "user@example.com", "password": "Password123!"},
            )

        self.assertRedirects(response, reverse("dashboard:home"), fetch_redirect_response=False)
        user = get_user_model().objects.get(email="user@example.com")
        self.assertEqual(user.username, "user@example.com")
        self.assertEqual(self.client.session["thepeach_access_token"], "access-token")
        self.assertEqual(int(self.client.session["_auth_user_id"]), user.id)

    def test_signup_creates_thepeach_account_then_logs_in(self):
        from unittest.mock import patch

        with patch("platform_auth.services.urlopen") as mock_urlopen:
            mock_urlopen.side_effect = [
                DummyResponse(
                    {
                        "success": True,
                        "data": {
                            "id": "tp-2",
                            "email": "new@example.com",
                            "full_name": "New User",
                        },
                    }
                ),
                DummyResponse(
                    {
                        "success": True,
                        "data": {
                            "access": "signup-access",
                            "refresh": "signup-refresh",
                        },
                    }
                ),
                DummyResponse(
                    {
                        "success": True,
                        "data": {
                            "id": "tp-2",
                            "email": "new@example.com",
                            "display_name": "New User",
                            "full_name": "New User",
                            "first_name": "New",
                            "last_name": "User",
                            "is_active": True,
                        },
                    }
                ),
            ]

            response = self.client.post(
                reverse("platform_auth:signup"),
                {
                    "email": "new@example.com",
                    "full_name": "New User",
                    "smartphone_number": "+821012341234",
                    "password": "Password123!",
                    "password_confirm": "Password123!",
                },
            )

        self.assertRedirects(response, reverse("dashboard:home"), fetch_redirect_response=False)
        self.assertTrue(get_user_model().objects.filter(email="new@example.com").exists())

    def test_login_failure_shows_signup_recommendation(self):
        from unittest.mock import patch

        with patch("platform_auth.services.urlopen") as mock_urlopen:
            mock_urlopen.side_effect = DummyHTTPError(
                {"detail": "Invalid email or password."},
                status=HTTPStatus.UNAUTHORIZED,
            )

            response = self.client.post(
                reverse("platform_auth:login"),
                {"email": "missing@example.com", "password": "Password123!"},
                follow=True,
            )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "계정이 없다면 먼저 가입하세요.")

    def test_logout_clears_local_and_thepeach_session(self):
        from unittest.mock import patch

        user = get_user_model().objects.create_user(username="local-user", email="local@example.com", password="pw123456")
        self.client.force_login(user)
        session = self.client.session
        session["thepeach_access_token"] = "access-token"
        session["thepeach_refresh_token"] = "refresh-token"
        session.save()

        with patch("platform_auth.services.urlopen") as mock_urlopen:
            mock_urlopen.return_value = DummyResponse({"success": True, "data": {"logged_out": True}})
            response = self.client.post(reverse("platform_auth:logout"))

        self.assertRedirects(response, reverse("landing"))
        self.assertNotIn("thepeach_access_token", self.client.session)
        self.assertNotIn("_auth_user_id", self.client.session)
