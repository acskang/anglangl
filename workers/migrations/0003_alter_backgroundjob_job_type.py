from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("workers", "0002_alter_backgroundjob_job_type"),
    ]

    operations = [
        migrations.AlterField(
            model_name="backgroundjob",
            name="job_type",
            field=models.CharField(
                choices=[
                    ("youtube_download", "YouTube Download"),
                    ("master_video_upload_process", "Master Video Upload Process"),
                    ("clip_extraction", "Clip Extraction"),
                    ("clip_batch_upload", "Clip Batch Upload"),
                    ("clip_file_postprocess", "Clip File Postprocess"),
                ],
                max_length=100,
            ),
        ),
    ]
