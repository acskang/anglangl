from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0003_imdbdramaepisodecache_resolved_at_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="imdbdramaseriescache",
            name="last_played_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
