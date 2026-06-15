from pathlib import Path

from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand
from django.db.models import Q

from clips.models import Clip
from dramaNlearn.models import ThumbnailAsset
from videos.models import MasterVideo


class Command(BaseCommand):
    help = "Move legacy thumbnail files into media/thumbnails using the current upload paths."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show which thumbnail files would move without changing any files.",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        summary = {
            "checked": 0,
            "relocated": 0,
            "already_ok": 0,
            "missing": 0,
        }

        self._relocate_queryset(
            MasterVideo.objects.filter(Q(saved_thumbnail_file__gt="") | Q(custom_thumbnail_file__gt="")),
            ("saved_thumbnail_file", "custom_thumbnail_file"),
            dry_run=dry_run,
            summary=summary,
        )
        self._relocate_queryset(
            Clip.objects.filter(Q(thumbnail_file__gt="") | Q(custom_thumbnail_file__gt="")),
            ("thumbnail_file", "custom_thumbnail_file"),
            dry_run=dry_run,
            summary=summary,
        )
        self._relocate_queryset(
            ThumbnailAsset.objects.exclude(image=""),
            ("image",),
            dry_run=dry_run,
            summary=summary,
        )

        mode = "DRY RUN" if dry_run else "APPLIED"
        self.stdout.write(
            self.style.SUCCESS(
                f"[{mode}] checked={summary['checked']} relocated={summary['relocated']} "
                f"already_ok={summary['already_ok']} missing={summary['missing']}"
            )
        )

    def _relocate_queryset(self, queryset, field_names, *, dry_run: bool, summary: dict[str, int]) -> None:
        for instance in queryset.iterator():
            for field_name in field_names:
                field_file = getattr(instance, field_name)
                old_name = getattr(field_file, "name", "") or ""
                if not old_name:
                    continue

                summary["checked"] += 1
                if old_name.startswith("thumbnails/"):
                    summary["already_ok"] += 1
                    continue

                storage = field_file.storage
                if not storage.exists(old_name):
                    summary["missing"] += 1
                    self.stderr.write(
                        self.style.WARNING(
                            f"Missing source file for {instance.__class__.__name__}#{instance.pk} {field_name}: {old_name}"
                        )
                    )
                    continue

                base_name = Path(old_name).name or "thumbnail"
                target_name = field_file.field.generate_filename(instance, base_name)
                if dry_run:
                    self.stdout.write(
                        f"Would move {instance.__class__.__name__}#{instance.pk} {field_name}: {old_name} -> {target_name}"
                    )
                    summary["relocated"] += 1
                    continue

                with storage.open(old_name, "rb") as source_handle:
                    content = ContentFile(source_handle.read(), name=base_name)
                    field_file.save(base_name, content, save=False)

                update_fields = [field_name]
                if hasattr(instance, "updated_at"):
                    update_fields.append("updated_at")
                instance.save(update_fields=update_fields)

                new_name = getattr(getattr(instance, field_name), "name", "") or ""
                if new_name and new_name != old_name and storage.exists(old_name):
                    storage.delete(old_name)

                self.stdout.write(
                    f"Moved {instance.__class__.__name__}#{instance.pk} {field_name}: {old_name} -> {new_name}"
                )
                summary["relocated"] += 1
