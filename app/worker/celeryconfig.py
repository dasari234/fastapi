import os
from datetime import timedelta

# Broker and Result Backend
broker_url = os.getenv('CELERY_BROKER_URL', 'redis://localhost:6379/0')
result_backend = os.getenv('CELERY_RESULT_BACKEND', 'redis://localhost:6379/1')

# Task configuration
task_serializer = 'json'
result_serializer = 'json'
accept_content = ['json']
timezone = 'UTC'
enable_utc = True

# Task routes
task_routes = {
    'app.worker.tasks.send_notification': {'queue': 'notifications'},
    'app.worker.tasks.process_batch_notifications': {'queue': 'notifications'},
}

# Beat schedule
beat_schedule = {
    'process-pending-notifications-every-30-seconds': {
        'task': 'app.worker.tasks.process_batch_notifications',
        'schedule': timedelta(seconds=30),
    },
}

# Worker configuration
worker_prefetch_multiplier = 1
worker_max_tasks_per_child = 1000
task_acks_late = True
worker_send_task_events = True
task_ignore_result = False