from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("clips", "0003_alter_clip_thumbnail_file"),
    ]

    operations = [
        migrations.AddField(
            model_name="clip",
            name="subtitle",
            field=models.TextField(blank=True, null=True),
        ),
    ]
