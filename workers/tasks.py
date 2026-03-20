from celery import shared_task


@shared_task(bind=True)
def placeholder_background_task(self):
    return {"status": "ok"}
