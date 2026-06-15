from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("dramaNlearn", "0004_thumbnailasset"),
        ("videos", "0005_mastervideo_category_mastervideo_channel_name_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="mastervideo",
            name="remote_playback_url",
            field=models.URLField(blank=True, default="", max_length=1000),
        ),
        migrations.AddField(
            model_name="mastervideo",
            name="source_drama_video",
            field=models.OneToOneField(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="master_video_bridge",
                to="dramaNlearn.video",
            ),
        ),
    ]
