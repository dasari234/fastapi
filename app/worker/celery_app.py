import os

from celery import Celery

# Set the default settings module for the 'celery' program.
os.environ.setdefault('CELERY_CONFIG_MODULE', 'app.worker.celeryconfig')

# Create Celery app
celery_app = Celery('fastapi_app')

# Load configuration from module
celery_app.config_from_envvar('CELERY_CONFIG_MODULE')

# Auto-discover tasks
celery_app.autodiscover_tasks(['app.worker.tasks'])

# Logging configuration
if __name__ == '__main__':
    celery_app.start()
