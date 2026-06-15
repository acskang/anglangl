from __future__ import annotations

from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from clips.services.clipmaster_import import import_clipmaster_data


class Command(BaseCommand):
    help = "Import clipmaster SQLite/media data into anglangl owner-scoped models."

    def add_arguments(self, parser):
        parser.add_argument("--owner", required=True, help="Target anglangl owner username, email, or user id.")
        parser.add_argument(
            "--source-root",
            default="/home/cskang/ganzskang/clipmaster",
            help="Clipmaster project root. Used to derive default source DB and media paths.",
        )
        parser.add_argument("--source-db", help="Path to the clipmaster SQLite database.")
        parser.add_argument("--source-media-root", help="Path to the clipmaster media root.")
        parser.add_argument("--dry-run", action="store_true", help="Read and summarize the source without importing.")

    def handle(self, *args, **options):
        source_root = Path(options["source_root"]).expanduser()
        source_db = Path(options["source_db"]).expanduser() if options["source_db"] else source_root / "db.sqlite3"
        source_media_root = (
            Path(options["source_media_root"]).expanduser()
            if options["source_media_root"]
            else source_root / "media"
        )

        try:
            summary = import_clipmaster_data(
                owner_identifier=str(options["owner"]),
                source_db=source_db,
                source_media_root=source_media_root,
                dry_run=options["dry_run"],
            )
        except Exception as exc:
            raise CommandError(str(exc)) from exc

        self.stdout.write(f"Owner: {options['owner']}")
        self.stdout.write(f"Source DB: {summary.source_db}")
        self.stdout.write(f"Source media root: {summary.source_media_root}")
        self.stdout.write(
            "Source counts: "
            f"videos={summary.source_counts['videos']}, "
            f"clips={summary.source_counts['clips']}, "
            f"clip_images={summary.source_counts['clip_images']}, "
            f"album_images={summary.source_counts['album_images']}"
        )

        if summary.empty_source:
            self.stdout.write(self.style.WARNING("No clipmaster source tables/data were found."))
        elif summary.dry_run:
            self.stdout.write(self.style.SUCCESS("Dry run completed."))
        else:
            self.stdout.write(
                "Imported/updated: "
                f"videos={summary.created_counts['videos']}/{summary.updated_counts['videos']}, "
                f"clips={summary.created_counts['clips']}/{summary.updated_counts['clips']}, "
                f"clip_images={summary.created_counts['clip_images']}/{summary.updated_counts['clip_images']}, "
                f"album_images={summary.created_counts['album_images']}/{summary.updated_counts['album_images']}, "
                f"video_thumbnails={summary.created_counts['video_thumbnails']}/{summary.updated_counts['video_thumbnails']}"
            )
        if summary.skipped_counts:
            self.stdout.write(
                "Skipped: " + ", ".join(f"{key}={value}" for key, value in sorted(summary.skipped_counts.items()))
            )
        if summary.missing_files:
            self.stdout.write(self.style.WARNING(f"Missing source files: {len(summary.missing_files)}"))
            for path in summary.missing_files[:10]:
                self.stdout.write(f"- {path}")
        for warning in summary.warnings:
            self.stdout.write(self.style.WARNING(warning))
