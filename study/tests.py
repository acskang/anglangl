import shutil
import tempfile

from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.test import TestCase, override_settings
from django.urls import reverse

from clips.models import Clip, ClipSourceType
from dramaNlearn.models import Video as DramaVideo
from study.models import StudyMaterial, StudyMaterialGeneration
from videos.models import MasterVideo, MasterVideoSourceType


STUDY_MEDIA_ROOT = tempfile.mkdtemp()


@override_settings(MEDIA_ROOT=STUDY_MEDIA_ROOT)
class StudyMaterialFlowTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(STUDY_MEDIA_ROOT, ignore_errors=True)

    def setUp(self):
        self.owner = get_user_model().objects.create_user(username="study-owner", password="pw123456")
        self.other_user = get_user_model().objects.create_user(username="study-other", password="pw123456")
        self.client.force_login(self.owner)

        self.master_video = MasterVideo.objects.create(
            owner=self.owner,
            source_type=MasterVideoSourceType.YOUTUBE,
            youtube_video_id="studyabc1234",
            youtube_url="https://youtube.com/watch?v=studyabc1234",
            title="Study Master Video",
        )
        self.master_video.subtitle_file.save(
            "lesson.srt",
            ContentFile(b"1\n00:00:00,000 --> 00:00:02,000\nHello there\n\n2\n00:00:02,500 --> 00:00:04,000\nGeneral Kenobi\n"),
            save=True,
        )
        self.clip = Clip.objects.create(
            owner=self.owner,
            source_type=ClipSourceType.EXTRACTED,
            master_video=self.master_video,
            title="Study Clip",
            subtitle="Clip subtitle line one\nClip subtitle line two",
            start_time_seconds=0,
            end_time_seconds=8,
            duration_seconds=8,
            file_status="ready",
        )
        self.drama_video = DramaVideo.objects.create(
            title="Drama Source",
            source_url="https://send2video.com/watch/drama-source",
            owner=self.owner,
            status="ready",
        )

    def test_create_view_prefills_master_video_subtitle_content(self):
        response = self.client.get(
            reverse("study:create") + f"?source_type=master_video&master_video_id={self.master_video.id}&material_type=shadowing_script"
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Hello there")
        self.assertContains(response, "master video subtitle file")
        self.assertContains(response, "## 추천 반복 구간")
        self.assertContains(response, "## 후편집 메모")

    def test_expressions_template_uses_source_sentences_as_candidates(self):
        response = self.client.get(
            reverse("study:create") + f"?source_type=clip&clip_id={self.clip.id}&material_type=expressions"
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Clip subtitle line one")
        self.assertContains(response, "## 장면 맥락 메모")

    def test_library_supports_title_sort(self):
        StudyMaterial.objects.create(
            owner=self.owner,
            title="Zulu Note",
            material_type="learning_note",
            purpose="vocabulary",
            difficulty="mixed",
            visibility="private",
            source_type="manual",
            generated_content="zulu",
        )
        StudyMaterial.objects.create(
            owner=self.owner,
            title="Alpha Note",
            material_type="learning_note",
            purpose="vocabulary",
            difficulty="mixed",
            visibility="private",
            source_type="manual",
            generated_content="alpha",
        )

        response = self.client.get(reverse("study:list") + "?sort=title")

        self.assertEqual(response.status_code, 200)
        materials = list(response.context["materials"])
        self.assertEqual(materials[0].title, "Alpha Note")
        self.assertEqual(materials[1].title, "Zulu Note")
        self.assertContains(response, "정렬")
        self.assertContains(response, "메타데이터 기반")

    def test_library_shows_quality_and_visibility_cues(self):
        material = StudyMaterial.objects.create(
            owner=self.owner,
            title="Quality Material",
            material_type="shadowing_script",
            purpose="shadowing",
            difficulty="intermediate",
            visibility="public",
            source_type="clip",
            generated_content="draft",
            generation_history=[{"source_text_kind": "clip_subtitle"}],
        )

        response = self.client.get(reverse("study:list"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, material.title)
        self.assertContains(response, "자막/대사 기반")
        self.assertContains(response, "탐색 화면에 노출됨")
        self.assertContains(response, "공개 후 다른 사용자가 복제 가능")

    def test_create_post_saves_material_and_generation_history(self):
        response = self.client.post(
            reverse("study:create") + f"?source_type=clip&clip_id={self.clip.id}",
            data={
                "title": "Clip Study Material",
                "material_type": "shadowing_script",
                "purpose": "shadowing",
                "difficulty": "intermediate",
                "visibility": "private",
                "generated_content": "Clip subtitle line one",
                "editable_notes": "note",
            },
        )

        self.assertEqual(response.status_code, 302)
        material = StudyMaterial.objects.get(owner=self.owner, title="Clip Study Material")
        self.assertEqual(material.source_type, "clip")
        self.assertEqual(material.source_clip, self.clip)
        self.assertEqual(material.generation_history[-1]["source_text_kind"], "clip_subtitle")
        self.assertEqual(material.generations.count(), 1)
        generation = material.generations.first()
        self.assertEqual(generation.prompt_intent, "initial_draft")

    def test_update_creates_manual_edit_generation(self):
        material = StudyMaterial.objects.create(
            owner=self.owner,
            title="Editable Material",
            material_type="shadowing_script",
            purpose="shadowing",
            difficulty="intermediate",
            visibility="private",
            source_type="manual",
            generated_content="before",
        )

        response = self.client.post(
            reverse("study:edit", args=[material.id]),
            data={
                "title": "Editable Material",
                "material_type": "shadowing_script",
                "purpose": "shadowing",
                "difficulty": "intermediate",
                "visibility": "private",
                "generated_content": "after",
                "editable_notes": "edited",
            },
        )

        self.assertEqual(response.status_code, 302)
        material.refresh_from_db()
        self.assertEqual(material.generated_content, "after")
        self.assertEqual(material.generations.count(), 1)
        self.assertEqual(material.generations.first().prompt_intent, "manual_edit")

    def test_visibility_toggle_flips_private_to_public(self):
        material = StudyMaterial.objects.create(
            owner=self.owner,
            title="Visibility Material",
            material_type="shadowing_script",
            purpose="shadowing",
            difficulty="intermediate",
            visibility="private",
            source_type="manual",
            generated_content="draft",
        )

        response = self.client.post(reverse("study:visibility-toggle", args=[material.id]))

        self.assertEqual(response.status_code, 302)
        material.refresh_from_db()
        self.assertEqual(material.visibility, "public")
        self.assertTrue(
            StudyMaterialGeneration.objects.filter(material=material, prompt_intent="visibility_toggle").exists()
        )

    def test_library_ownership_filter_shows_imported_only(self):
        original = StudyMaterial.objects.create(
            owner=self.other_user,
            title="Original Public Material",
            material_type="shadowing_script",
            purpose="shadowing",
            difficulty="intermediate",
            visibility="public",
            source_type="manual",
            generated_content="public draft",
        )
        own_material = StudyMaterial.objects.create(
            owner=self.owner,
            title="Owner Material",
            material_type="learning_note",
            purpose="vocabulary",
            difficulty="mixed",
            visibility="private",
            source_type="manual",
            generated_content="owner draft",
        )
        imported = StudyMaterial.objects.create(
            owner=self.owner,
            title="Imported Material",
            material_type="shadowing_script",
            purpose="shadowing",
            difficulty="intermediate",
            visibility="private",
            source_type="manual",
            generated_content="imported draft",
            copied_from=original,
        )

        response = self.client.get(reverse("study:list") + "?ownership=imported")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, imported.title)
        self.assertNotContains(response, own_material.title)

    def test_explore_excludes_my_own_public_materials(self):
        my_public = StudyMaterial.objects.create(
            owner=self.owner,
            title="My Public Material",
            material_type="shadowing_script",
            purpose="shadowing",
            difficulty="intermediate",
            visibility="public",
            source_type="manual",
            generated_content="mine",
        )
        other_public = StudyMaterial.objects.create(
            owner=self.other_user,
            title="Other Public Material",
            material_type="expressions",
            purpose="speaking",
            difficulty="intermediate",
            visibility="public",
            source_type="manual",
            generated_content="other",
        )

        response = self.client.get(reverse("study:explore"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, other_public.title)
        self.assertNotContains(response, my_public.title)

    def test_public_detail_is_available_for_other_users_public_material(self):
        public_material = StudyMaterial.objects.create(
            owner=self.other_user,
            title="Other Public Detail",
            material_type="shadowing_script",
            purpose="shadowing",
            difficulty="intermediate",
            visibility="public",
            source_type="manual",
            generated_content="other detail",
        )

        response = self.client.get(reverse("study:public-detail", args=[public_material.id]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, public_material.title)
        self.assertContains(response, "내 라이브러리로 복제")
        self.assertContains(response, "복제 후 내 라이브러리에서 제목, 노트, 생성 내용을 다시 편집할 수 있습니다.")
        self.assertContains(response, "탐색 화면에 노출됨")

    def test_clone_copies_public_material_into_private_library(self):
        source_material = StudyMaterial.objects.create(
            owner=self.other_user,
            title="Cloneable Public Material",
            material_type="shadowing_script",
            purpose="shadowing",
            difficulty="intermediate",
            visibility="public",
            source_type="drama_video",
            source_title=self.drama_video.title,
            source_drama_video=self.drama_video,
            generated_content="clone me",
            editable_notes="note me",
        )

        response = self.client.post(reverse("study:clone", args=[source_material.id]))

        self.assertEqual(response.status_code, 302)
        cloned = StudyMaterial.objects.filter(owner=self.owner).latest("id")
        self.assertEqual(cloned.copied_from, source_material)
        self.assertEqual(cloned.visibility, "private")
        self.assertEqual(cloned.generated_content, source_material.generated_content)
        self.assertEqual(cloned.source_drama_video, self.drama_video)
        self.assertTrue(cloned.is_imported)
        self.assertEqual(cloned.ownership_label, "가져온 자료")
        self.assertTrue(
            StudyMaterialGeneration.objects.filter(material=cloned, prompt_intent="clone_import").exists()
        )

    def test_clone_rejects_private_material_from_other_user(self):
        private_material = StudyMaterial.objects.create(
            owner=self.other_user,
            title="Private Material",
            material_type="shadowing_script",
            purpose="shadowing",
            difficulty="intermediate",
            visibility="private",
            source_type="manual",
            generated_content="secret",
        )

        response = self.client.post(reverse("study:clone", args=[private_material.id]))

        self.assertEqual(response.status_code, 404)

    def test_non_owner_cannot_open_private_library_detail(self):
        private_material = StudyMaterial.objects.create(
            owner=self.owner,
            title="Owner Private Detail",
            material_type="shadowing_script",
            purpose="shadowing",
            difficulty="intermediate",
            visibility="private",
            source_type="manual",
            generated_content="private",
        )
        self.client.force_login(self.other_user)

        response = self.client.get(reverse("study:detail", args=[private_material.id]))

        self.assertEqual(response.status_code, 404)

    def test_material_can_flow_from_library_to_public_clone_and_reedit(self):
        create_response = self.client.post(
            reverse("study:create") + f"?source_type=clip&clip_id={self.clip.id}",
            data={
                "title": "Reusable Clip Material",
                "material_type": "shadowing_script",
                "purpose": "shadowing",
                "difficulty": "intermediate",
                "visibility": "private",
                "generated_content": "Clip subtitle line one",
                "editable_notes": "owner draft",
            },
        )

        self.assertEqual(create_response.status_code, 302)
        original = StudyMaterial.objects.get(owner=self.owner, title="Reusable Clip Material")
        self.assertEqual(original.visibility, "private")

        toggle_response = self.client.post(reverse("study:visibility-toggle", args=[original.id]))

        self.assertEqual(toggle_response.status_code, 302)
        original.refresh_from_db()
        self.assertEqual(original.visibility, "public")

        self.client.force_login(self.other_user)

        explore_response = self.client.get(reverse("study:explore"))
        self.assertEqual(explore_response.status_code, 200)
        self.assertContains(explore_response, original.title)

        public_detail_response = self.client.get(reverse("study:public-detail", args=[original.id]))
        self.assertEqual(public_detail_response.status_code, 200)
        self.assertContains(public_detail_response, "내 라이브러리로 복제")

        clone_response = self.client.post(reverse("study:clone", args=[original.id]))
        self.assertEqual(clone_response.status_code, 302)

        cloned = StudyMaterial.objects.get(owner=self.other_user, copied_from=original)
        self.assertEqual(cloned.visibility, "private")
        self.assertTrue(cloned.is_imported)

        imported_list_response = self.client.get(reverse("study:list") + "?ownership=imported")
        self.assertEqual(imported_list_response.status_code, 200)
        self.assertContains(imported_list_response, cloned.title)
        self.assertContains(imported_list_response, "가져온 자료")

        edit_response = self.client.post(
            reverse("study:edit", args=[cloned.id]),
            data={
                "title": cloned.title,
                "material_type": cloned.material_type,
                "purpose": cloned.purpose,
                "difficulty": cloned.difficulty,
                "visibility": cloned.visibility,
                "generated_content": "Edited imported draft",
                "editable_notes": "imported and updated",
            },
            follow=True,
        )

        self.assertEqual(edit_response.status_code, 200)
        cloned.refresh_from_db()
        self.assertEqual(cloned.generated_content, "Edited imported draft")
        self.assertContains(edit_response, "Edited imported draft")
        self.assertTrue(
            StudyMaterialGeneration.objects.filter(material=cloned, prompt_intent="manual_edit").exists()
        )

    def test_create_form_shows_template_guidance_for_learning_note(self):
        response = self.client.get(
            reverse("study:create") + f"?source_type=clip&clip_id={self.clip.id}&material_type=learning_note"
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "단어/문장 노트는 핵심 문장과 반복할 단어 후보를 먼저 제안하는 구조로 시작합니다.")
