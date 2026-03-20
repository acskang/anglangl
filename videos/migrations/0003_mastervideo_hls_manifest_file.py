from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("videos", "0002_remove_mastervideo_uniq_mastervideo_owner_videoid_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="mastervideo",
            name="hls_manifest_file",
            field=models.FileField(blank=True, upload_to="videos/hls/"),
        ),
    ]
