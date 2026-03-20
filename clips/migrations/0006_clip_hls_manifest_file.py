import clips.models
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("clips", "0005_clip_subtitle_timing"),
    ]

    operations = [
        migrations.AddField(
            model_name="clip",
            name="hls_manifest_file",
            field=models.FileField(blank=True, upload_to=clips.models._clip_hls_manifest_path),
        ),
    ]
