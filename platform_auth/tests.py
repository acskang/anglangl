from http import HTTPStatus
from urllib.error import HTTPError

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import connection
from django.test import Client, TestCase
from django.test.utils import CaptureQueriesContext
from django.template import Context, Template
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
        self.assertIn(settings.THEPEACH_SSO_ACCESS_COOKIE_NAME, response.cookies)
        self.assertIn(settings.THEPEACH_SSO_REFRESH_COOKIE_NAME, response.cookies)

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
        self.assertContains(response, "계정이 없다면 회원가입 후 시작하세요.")
        self.assertNotContains(response, "ThePeach")

    def test_login_page_uses_modal_shell_without_external_branding(self):
        response = self.client.get(reverse("platform_auth:login"), {"next": reverse("videos:create-youtube")})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="authModalBackdrop"', html=False)
        self.assertContains(response, "다시 이어서 작업하기")
        self.assertNotContains(response, "ThePeach")

    def test_login_ajax_returns_json_payload(self):
        from unittest.mock import patch

        with patch("platform_auth.services.urlopen") as mock_urlopen:
            mock_urlopen.side_effect = [
                DummyResponse(
                    {
                        "success": True,
                        "data": {
                            "access": "access-token",
                            "refresh": "refresh-token",
                        },
                    }
                ),
                DummyResponse(
                    {
                        "success": True,
                        "data": {
                            "id": "tp-ajax",
                            "email": "ajax@example.com",
                            "display_name": "Ajax User",
                            "full_name": "Ajax User",
                            "first_name": "Ajax",
                            "last_name": "User",
                            "is_active": True,
                        },
                    }
                ),
            ]

            response = self.client.post(
                reverse("platform_auth:login"),
                {"email": "ajax@example.com", "password": "Password123!"},
                HTTP_X_REQUESTED_WITH="XMLHttpRequest",
                HTTP_ACCEPT="application/json",
            )

        self.assertEqual(response.status_code, 200)
        self.assertJSONEqual(
            response.content.decode("utf-8"),
            {"ok": True, "redirect_url": reverse("dashboard:home"), "message": "로그인되었습니다."},
        )
        self.assertIn(settings.THEPEACH_SSO_ACCESS_COOKIE_NAME, response.cookies)

    def test_logout_ajax_returns_json_payload(self):
        from unittest.mock import patch

        user = get_user_model().objects.create_user(username="json-user", email="json@example.com", password="pw123456")
        self.client.force_login(user)
        session = self.client.session
        session["thepeach_access_token"] = "access-token"
        session["thepeach_refresh_token"] = "refresh-token"
        session.save()

        with patch("platform_auth.services.urlopen") as mock_urlopen:
            mock_urlopen.return_value = DummyResponse({"success": True, "data": {"logged_out": True}})
            response = self.client.post(
                reverse("platform_auth:logout"),
                {"next": reverse("landing")},
                HTTP_X_REQUESTED_WITH="XMLHttpRequest",
                HTTP_ACCEPT="application/json",
            )

        self.assertEqual(response.status_code, 200)
        self.assertJSONEqual(
            response.content.decode("utf-8"),
            {"ok": True, "redirect_url": reverse("landing"), "message": "로그아웃되었습니다."},
        )

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
        self.assertEqual(response.cookies[settings.THEPEACH_SSO_ACCESS_COOKIE_NAME].value, "")
        self.assertEqual(response.cookies[settings.THEPEACH_SSO_REFRESH_COOKIE_NAME].value, "")

    def test_shared_cookie_authenticates_user_without_local_login(self):
        from unittest.mock import patch

        self.client.cookies[settings.THEPEACH_SSO_ACCESS_COOKIE_NAME] = "shared-access"
        self.client.cookies[settings.THEPEACH_SSO_REFRESH_COOKIE_NAME] = "shared-refresh"

        with patch("platform_auth.services.urlopen") as mock_urlopen:
            mock_urlopen.return_value = DummyResponse(
                {
                    "success": True,
                    "data": {
                        "id": "tp-shared",
                        "email": "shared@example.com",
                        "display_name": "Shared User",
                        "full_name": "Shared User",
                        "first_name": "Shared",
                        "last_name": "User",
                        "is_active": True,
                    },
                }
            )
            response = self.client.get(reverse("landing"))

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.wsgi_request.user.is_authenticated)
        self.assertEqual(response.wsgi_request.user.email, "shared@example.com")

    def test_shared_cookie_reuses_matching_session_without_rewriting_session_payload(self):
        from unittest.mock import patch

        user = get_user_model().objects.create_user(
            username="shared@example.com",
            email="shared@example.com",
            first_name="Shared",
            last_name="User",
            password="pw123456",
        )
        self.client.force_login(user)
        session = self.client.session
        session["thepeach_access_token"] = "shared-access"
        session["thepeach_refresh_token"] = "shared-refresh"
        session["thepeach_profile"] = {
            "id": "tp-shared",
            "email": "shared@example.com",
            "display_name": "Shared User",
            "full_name": "Shared User",
            "first_name": "Shared",
            "last_name": "User",
            "is_active": True,
        }
        session["thepeach_auth_source"] = "thepeach_sso"
        session.save()
        self.client.cookies[settings.THEPEACH_SSO_ACCESS_COOKIE_NAME] = "shared-access"
        self.client.cookies[settings.THEPEACH_SSO_REFRESH_COOKIE_NAME] = "shared-refresh"

        with patch("platform_auth.services.urlopen") as mock_urlopen, patch("platform_auth.middleware.store_thepeach_session") as mock_store_session, patch(
            "platform_auth.middleware.auth_login"
        ) as mock_auth_login:
            mock_urlopen.return_value = DummyResponse(
                {
                    "success": True,
                    "data": {
                        "id": "tp-shared",
                        "email": "shared@example.com",
                        "display_name": "Shared User",
                        "full_name": "Shared User",
                        "first_name": "Shared",
                        "last_name": "User",
                        "is_active": True,
                    },
                }
            )

            response = self.client.get(reverse("landing"))

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.wsgi_request.user.is_authenticated)
        mock_store_session.assert_not_called()
        mock_auth_login.assert_not_called()


class SyncLocalUserTests(TestCase):
    def test_sync_local_user_skips_update_when_profile_unchanged(self):
        from platform_auth.services import PlatformUser, sync_local_user

        user = get_user_model().objects.create_user(
            username="shared@example.com",
            email="shared@example.com",
            first_name="Shared",
            last_name="User",
            password=None,
        )
        profile = PlatformUser(
            id="tp-shared",
            email="shared@example.com",
            display_name="Shared User",
            full_name="Shared User",
            first_name="Shared",
            last_name="User",
            is_active=True,
        )

        with CaptureQueriesContext(connection) as queries:
            synced_user = sync_local_user(profile)

        self.assertEqual(synced_user.id, user.id)
        update_queries = [query["sql"] for query in queries.captured_queries if query["sql"].lstrip().upper().startswith("UPDATE ")]
        self.assertEqual(update_queries, [])


class UserDisplayTemplateFilterTests(TestCase):
    def test_uses_full_name_when_available(self):
        user = get_user_model().objects.create_user(
            username="named@example.com",
            email="named@example.com",
            first_name="Codex",
            last_name="User",
            password="pw123456",
        )

        rendered = Template("{% load user_display %}{{ user|user_display_label }}").render(Context({"user": user}))

        self.assertEqual(rendered, "Codex User")

    def test_uses_email_local_part_when_name_missing(self):
        user = get_user_model().objects.create_user(
            username="cskang@thesysm.com",
            email="cskang@thesysm.com",
            password="pw123456",
        )

        rendered = Template("{% load user_display %}{{ user|user_display_label }}").render(Context({"user": user}))

        self.assertEqual(rendered, "cskang")
