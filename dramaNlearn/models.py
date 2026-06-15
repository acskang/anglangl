import json
from pathlib import Path
from uuid import uuid4

from django.db import models
from django.conf import settings


class Video(models.Model):
    STATUS_CHOICES = [
        ('pending',  '대기중'),
        ('queued',   '대기열'),
        ('fetching', '추출중'),
        ('ready',    '재생가능'),
        ('error',    '오류'),
        ('canceled', '취소됨'),
        ('expired',  '만료됨'),
    ]

    # 원본 정보
    title        = models.CharField(max_length=300, verbose_name='제목')
    source_url   = models.URLField(max_length=1000, verbose_name='send2video URL')
    owner        = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='videos',
        verbose_name='등록 사용자',
    )

    # 추출된 정보
    player_url   = models.URLField(max_length=1000, blank=True, verbose_name='플레이어 iframe URL')
    m3u8_url     = models.TextField(blank=True, verbose_name='m3u8 스트리밍 URL')
    thumbnail    = models.URLField(max_length=1000, blank=True, verbose_name='썸네일')
    duration     = models.FloatField(default=0, verbose_name='재생시간(초)')
    subtitle_tracks = models.TextField(blank=True, default='[]', verbose_name='자막 트랙 JSON')

    # 상태
    status       = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    error_msg    = models.TextField(blank=True, verbose_name='오류 메시지')

    # 통계
    view_count   = models.PositiveIntegerField(default=0, verbose_name='조회수')
    created_at   = models.DateTimeField(auto_now_add=True)
    updated_at   = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = '동영상'
        verbose_name_plural = '동영상 목록'
        ordering = ['-created_at']

    def __str__(self):
        return self.title

    def duration_str(self):
        if not self.duration:
            return ''
        m, s = divmod(int(self.duration), 60)
        h, m = divmod(m, 60)
        if h:
            return '%d:%02d:%02d' % (h, m, s)
        return '%d:%02d' % (m, s)

    def subtitle_tracks_list(self):
        if not self.subtitle_tracks:
            return []
        try:
            data = json.loads(self.subtitle_tracks)
        except (TypeError, ValueError):
            return []
        return data if isinstance(data, list) else []


def thumbnail_asset_upload_path(instance, filename):
    safe_name = Path(filename).name or "thumbnail"
    return f"thumbnails/asset-{instance.pk or 'new'}-{uuid4().hex}-{safe_name}"


class ThumbnailAsset(models.Model):
    name = models.CharField(max_length=120, verbose_name="이름")
    image = models.ImageField(upload_to=thumbnail_asset_upload_path, verbose_name="이미지")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="thumbnail_assets",
        verbose_name="등록 사용자",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "썸네일 자산"
        verbose_name_plural = "썸네일 자산"
        ordering = ["name", "-created_at"]

    def __str__(self):
        return self.name
