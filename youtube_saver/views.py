import requests
from pathlib import Path
from django.conf import settings
from django.shortcuts import render, redirect
from django.contrib import messages

from .chapter_utils import (
    ChapterDownloadError,
    ChapterExtractionError,
    ChapterMeta,
    download_chapter_section,
    fetch_chapters,
)
from .models import ChapterDownload, YouTubeVideo
from .forms import ChapterURLForm, YouTubeURLForm


def home(request):
    return render(request, 'home.html')


def fetch_youtube_metadata(url: str) -> dict:
    """Fetch video metadata from YouTube via the public oEmbed endpoint."""
    endpoint = "https://www.youtube.com/oembed"
    params = {"url": url, "format": "json"}
    resp = requests.get(endpoint, params=params, timeout=10)
    resp.raise_for_status()
    return resp.json()


def save_youtube_video(request):
    if request.method == 'POST':
        form = YouTubeURLForm(request.POST)
        if form.is_valid():
            url = form.cleaned_data['url']

            # 이미 저장된 URL이면 메타데이터 조회를 건너뛰고 메시지만 표시
            existing = YouTubeVideo.objects.filter(url=url).first()
            if existing:
                messages.info(request, '이미 있는 영상입니다.')
                return redirect('video_list')

            try:
                metadata = fetch_youtube_metadata(url)
                title = metadata.get("title")
                thumbnail_url = metadata.get("thumbnail_url")

                if not title or not thumbnail_url:
                    raise ValueError("필수 메타데이터가 없습니다.")

                video, created = YouTubeVideo.objects.get_or_create(
                    url=url,
                    defaults={
                        'title': title,
                        'thumbnail_url': thumbnail_url,
                    }
                )

                if created:
                    messages.success(request, '동영상이 성공적으로 저장되었습니다!')
                else:
                    messages.info(request, '이미 저장된 동영상입니다.')

            except requests.HTTPError as exc:
                messages.error(request, f'오류가 발생했습니다: HTTP {exc.response.status_code}')
            except requests.RequestException as exc:
                messages.error(request, f'오류가 발생했습니다: {exc}')
            except Exception as exc:  # noqa: BLE001
                messages.error(request, f'오류가 발생했습니다: {exc}')

            return redirect('video_list')
    else:
        form = YouTubeURLForm()

    return render(request, 'save_video.html', {'form': form})


def video_list(request):
    query = (request.GET.get("q") or "").strip()
    videos = YouTubeVideo.objects.all()
    if query:
        videos = videos.filter(title__icontains=query)
    return render(request, 'video_list.html', {'videos': videos, 'query': query})


def chapter_downloader(request):
    form = ChapterURLForm(request.POST or None)
    chapters: list[ChapterMeta] = []
    video_title = ""
    url_value = ""
    download_results = {"success": [], "failed": []}
    skipped_count = 0
    selected_indices: set[int] = set()
    existing_success_indices: set[int] = set()
    delete_single: int | None = None

    if request.method == 'POST' and form.is_valid():
        url_value = form.cleaned_data['url']
        try:
            chapters, info = fetch_chapters(url_value)
            video_title = info.get("title") or ""
        except ChapterExtractionError as exc:
            messages.error(request, str(exc))
        else:
            existing_success_indices = set(
                ChapterDownload.objects.filter(
                    video_url=url_value,
                    status=ChapterDownload.STATUS_SUCCESS,
                ).values_list("chapter_index", flat=True)
            )
            if not chapters:
                messages.warning(request, '챕터가 없는 영상입니다.')
            else:
                existing_success_indices = set(
                    ChapterDownload.objects.filter(
                        video_url=url_value,
                        status=ChapterDownload.STATUS_SUCCESS,
                    ).values_list("chapter_index", flat=True)
                )

            delete_single_raw = request.POST.get("delete_single")
            if delete_single_raw:
                try:
                    delete_single = int(delete_single_raw)
                except ValueError:
                    delete_single = None

            action = request.POST.get('action')
            selected = {int(val) for val in request.POST.getlist('chapters') if val.isdigit()}
            if delete_single is not None:
                selected = {delete_single}
                action = 'delete'

            selected_indices = selected.copy() or existing_success_indices

            if action == 'delete':
                if not selected:
                    messages.warning(request, '삭제할 챕터를 선택하세요.')
                else:
                    deleted = 0
                    for idx in selected:
                        qs = ChapterDownload.objects.filter(
                            video_url=url_value,
                            chapter_index=idx,
                            status=ChapterDownload.STATUS_SUCCESS,
                        )
                        for rec in qs:
                            if rec.output_path:
                                file_path = Path(settings.MEDIA_ROOT) / rec.output_path
                                try:
                                    resolved = file_path.resolve()
                                    if settings.MEDIA_ROOT.resolve() in resolved.parents or resolved == settings.MEDIA_ROOT.resolve():
                                        if file_path.exists():
                                            file_path.unlink()
                                except OSError:
                                    pass
                            rec.delete()
                            deleted += 1
                    if deleted:
                        messages.success(request, f"{deleted}개 챕터를 삭제했습니다.")
                    else:
                        messages.info(request, "삭제할 파일을 찾지 못했습니다.")

                    # refresh existing indices after deletion
                    existing_success_indices = set(
                        ChapterDownload.objects.filter(
                            video_url=url_value,
                            status=ChapterDownload.STATUS_SUCCESS,
                        ).values_list("chapter_index", flat=True)
                    )

            elif action == 'download':
                if not selected:
                    messages.warning(request, '다운로드할 챕터를 선택하세요.')
                else:
                    outdir = Path(settings.MEDIA_ROOT) / 'chapters'
                    success_count = 0
                    fail_count = 0

                    for ch in chapters:
                        if ch.idx not in selected:
                            continue
                        # 이미 성공적으로 저장된 동일 챕터가 있으면 건너뛴다.
                        existing = ChapterDownload.objects.filter(
                            video_url=url_value,
                            chapter_index=ch.idx,
                            status=ChapterDownload.STATUS_SUCCESS,
                        ).first()
                        if existing:
                            skipped_count += 1
                            download_results["success"].append(
                                {
                                    "index": ch.idx,
                                    "title": f"{ch.title} (이미 저장됨)",
                                    "path": existing.output_path,
                                    "skipped": True,
                                }
                            )
                            continue
                        download_record = ChapterDownload.objects.create(
                            video_url=url_value,
                            video_title=video_title,
                            chapter_index=ch.idx,
                            chapter_title=ch.title,
                            start_time=ch.start,
                            end_time=ch.end,
                            status=ChapterDownload.STATUS_PENDING,
                        )
                        try:
                            output_path = download_chapter_section(url_value, ch, outdir)
                            relative_path = ""
                            if output_path:
                                try:
                                    relative_path = str(output_path.relative_to(settings.MEDIA_ROOT))
                                except ValueError:
                                    relative_path = str(output_path)

                            download_record.output_path = relative_path
                            download_record.status = ChapterDownload.STATUS_SUCCESS
                            download_record.save(update_fields=["output_path", "status"])
                            download_results["success"].append(
                                {
                                    "index": ch.idx,
                                    "title": ch.title,
                                    "path": relative_path,
                                    "skipped": False,
                                }
                            )
                            success_count += 1
                        except (ChapterDownloadError, ChapterExtractionError, OSError) as exc:
                            download_record.status = ChapterDownload.STATUS_FAILED
                            download_record.error_message = str(exc)
                            download_record.save(update_fields=["status", "error_message"])
                            download_results["failed"].append(
                                {
                                    "index": ch.idx,
                                    "title": ch.title,
                                    "error": str(exc),
                                }
                            )
                            fail_count += 1

                    if success_count:
                        messages.success(
                            request, f"{success_count}개 챕터를 media/chapters에 저장했습니다."
                        )
                    if fail_count:
                        messages.error(
                            request, f"{fail_count}개 챕터 다운로드에 실패했습니다. 관리자에게 로그를 확인하세요."
                        )
                    if skipped_count:
                        messages.info(
                            request, f"{skipped_count}개 챕터는 이미 저장되어 건너뛰었습니다."
                        )

    context = {
        'form': form,
        'chapters': chapters,
        'video_title': video_title,
        'url_value': url_value,
        'media_root': settings.MEDIA_ROOT,
        'download_results': download_results,
        'selected_indices': selected_indices,
        'media_url': settings.MEDIA_URL,
        'existing_success_indices': existing_success_indices,
    }
    return render(request, 'chapter_downloader.html', context)


def play_chapters(request):
    downloads = (
        ChapterDownload.objects.filter(
            status=ChapterDownload.STATUS_SUCCESS,
        )
        .exclude(output_path="")
        .order_by("-created_at")
    )
    return render(
        request,
        "play_chapters.html",
        {
            "downloads": downloads,
            "media_url": settings.MEDIA_URL,
        },
    )
