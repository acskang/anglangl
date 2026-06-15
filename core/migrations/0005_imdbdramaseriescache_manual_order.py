from django.db import migrations, models


def seed_manual_order(apps, schema_editor):
    ImdbDramaSeriesCache = apps.get_model("core", "ImdbDramaSeriesCache")
    rows = list(
        ImdbDramaSeriesCache.objects.order_by("-updated_at", "title", "imdb_id")
    )
    for index, row in enumerate(rows, start=1):
        row.manual_order = index
    if rows:
        ImdbDramaSeriesCache.objects.bulk_update(rows, ["manual_order"])


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0004_imdbdramaseriescache_last_played_at"),
    ]

    operations = [
        migrations.AddField(
            model_name="imdbdramaseriescache",
            name="manual_order",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.RunPython(seed_manual_order, migrations.RunPython.noop),
    ]
