from django.urls import path
from . import views

urlpatterns = [
    path('', views.home, name='home'),
    path('save/', views.save_youtube_video, name='save_video'),
    path('library/', views.video_list, name='video_list'),
    path('list/', views.video_list),
    path('chapters/', views.chapter_downloader, name='chapter_downloader'),
    path('play-chapters/', views.play_chapters, name='play_chapters'),
]
