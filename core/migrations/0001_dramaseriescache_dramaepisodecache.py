from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="DramaSeriesCache",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("tmdb", models.CharField(max_length=64, unique=True)),
                ("title", models.CharField(blank=True, max_length=255)),
            ],
            options={
                "ordering": ["title", "tmdb"],
            },
        ),
        migrations.CreateModel(
            name="DramaEpisodeCache",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("season_number", models.PositiveIntegerField()),
                ("episode_number", models.PositiveIntegerField()),
                ("label", models.CharField(blank=True, max_length=255)),
                ("embed_url", models.URLField(max_length=1000)),
                ("series", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="episodes", to="core.dramaseriescache")),
            ],
            options={
                "ordering": ["season_number", "episode_number"],
                "unique_together": {("series", "season_number", "episode_number")},
            },
        ),
    ]
