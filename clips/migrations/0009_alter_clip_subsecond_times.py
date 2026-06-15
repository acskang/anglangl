from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("clips", "0008_clip_custom_thumbnail_file"),
    ]

    operations = [
        migrations.AlterField(
            model_name="clip",
            name="duration_seconds",
            field=models.FloatField(default=0.0),
        ),
        migrations.AlterField(
            model_name="clip",
            name="end_time_seconds",
            field=models.FloatField(default=0.0),
        ),
        migrations.AlterField(
            model_name="clip",
            name="start_time_seconds",
            field=models.FloatField(default=0.0),
        ),
    ]
