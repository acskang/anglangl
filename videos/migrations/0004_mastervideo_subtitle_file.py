from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("videos", "0003_mastervideo_hls_manifest_file"),
    ]

    operations = [
        migrations.AddField(
            model_name="mastervideo",
            name="subtitle_file",
            field=models.FileField(blank=True, upload_to="videos/subtitles/"),
        ),
    ]
