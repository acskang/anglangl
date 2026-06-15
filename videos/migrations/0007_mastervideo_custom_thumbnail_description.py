from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("videos", "0006_mastervideo_remote_playback_url_and_bridge"),
    ]

    operations = [
        migrations.AddField(
            model_name="mastervideo",
            name="custom_thumbnail_description",
            field=models.TextField(blank=True, default=""),
        ),
    ]
