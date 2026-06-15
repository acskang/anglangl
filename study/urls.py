from django.urls import path

from .views import (
    StudyMaterialCloneView,
    StudyMaterialCreateView,
    StudyMaterialDetailView,
    StudyMaterialExploreListView,
    StudyMaterialListView,
    StudyMaterialPublicDetailView,
    StudyMaterialUpdateView,
    StudyMaterialVisibilityToggleView,
)

app_name = "study"

urlpatterns = [
    path("", StudyMaterialListView.as_view(), name="list"),
    path("explore/", StudyMaterialExploreListView.as_view(), name="explore"),
    path("create/", StudyMaterialCreateView.as_view(), name="create"),
    path("<int:pk>/", StudyMaterialDetailView.as_view(), name="detail"),
    path("<int:pk>/edit/", StudyMaterialUpdateView.as_view(), name="edit"),
    path("<int:pk>/clone/", StudyMaterialCloneView.as_view(), name="clone"),
    path("<int:pk>/visibility-toggle/", StudyMaterialVisibilityToggleView.as_view(), name="visibility-toggle"),
    path("public/<int:pk>/", StudyMaterialPublicDetailView.as_view(), name="public-detail"),
]
