from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("clips", "0004_clip_subtitle"),
    ]

    operations = [
        migrations.AddField(
            model_name="clip",
            name="subtitle_timing",
            field=models.TextField(blank=True, default="[]"),
        ),
    ]
