from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from study.models import StudyMaterial


class DashboardViewTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="dash-user", password="pw123456")
        self.other_user = get_user_model().objects.create_user(username="dash-other", password="pw123456")
        self.client.force_login(self.user)

    def test_dashboard_requires_login(self):
        self.client.logout()

        response = self.client.get(reverse("dashboard:home"))

        self.assertEqual(response.status_code, 302)

    def test_dashboard_shows_study_material_count_and_recent_materials(self):
        own_material = StudyMaterial.objects.create(
            owner=self.user,
            title="My Study Material",
            material_type="shadowing_script",
            purpose="shadowing",
            difficulty="intermediate",
            visibility="private",
            source_type="manual",
            generated_content="draft",
        )
        imported_source = StudyMaterial.objects.create(
            owner=self.other_user,
            title="Other Public Source",
            material_type="expressions",
            purpose="speaking",
            difficulty="intermediate",
            visibility="public",
            source_type="manual",
            generated_content="public draft",
        )
        imported_material = StudyMaterial.objects.create(
            owner=self.user,
            title="Imported Study Material",
            material_type="expressions",
            purpose="speaking",
            difficulty="intermediate",
            visibility="private",
            source_type="manual",
            generated_content="copied draft",
            copied_from=imported_source,
        )

        response = self.client.get(reverse("dashboard:home"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Study Materials")
        self.assertContains(response, "2")
        self.assertContains(response, own_material.title)
        self.assertContains(response, imported_material.title)
        self.assertContains(response, "Recent Study Materials")
        self.assertContains(response, "가져온 자료")
        self.assertContains(response, reverse("study:list"))
