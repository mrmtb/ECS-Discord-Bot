# app/extensions.py

"""
Extensions Module

This module initializes and configures various application extensions,
including Celery and SQLAlchemy. It provides a function to initialize
Celery with Flask's application context and manages database connection
initialization and cleanup for Celery worker processes.
"""

import logging
from flask import current_app
from celery.signals import worker_process_init, worker_process_shutdown
from app.core import db, celery

logger = logging.getLogger(__name__)

def init_celery(app=None):
    """
    Initialize Celery with the Flask application context.

    Parameters:
        app (Flask): The Flask application instance.

    Returns:
        Celery: The configured Celery instance.
    """
    if app:
        celery.conf.update(app.config)

    class FlaskTask(celery.Task):
        abstract = True

        def __call__(self, *args, **kwargs):
            flask_app = app or current_app._get_current_object()
            with flask_app.app_context():
                session = flask_app.SessionLocal()
                self._session = session
                try:
                    result = self.run(*args, **kwargs)
                    session.commit()
                    return result
                except Exception as e:
                    session.rollback()
                    logger.error(f"Error in Celery task {self.name}: {str(e)}", exc_info=True)
                    raise
                finally:
                    session.close()
                    del self._session

        @property
        def session(self):
            if not hasattr(self, '_session'):
                raise RuntimeError("No database session available in this context")
            return self._session

    celery.Task = FlaskTask

    celery.conf.update(
        task_serializer='json',
        accept_content=['json'],
        result_serializer='json',
        timezone='UTC',
        enable_utc=True,
        broker_connection_retry_on_startup=True,
        worker_prefetch_multiplier=1,
        task_track_started=True,
        task_time_limit=30 * 60,
        task_soft_time_limit=15 * 60,
        worker_max_tasks_per_child=50,
        worker_max_memory_per_child=150000
    )

    return celery

@worker_process_init.connect
def init_worker_process(**kwargs):
    """
    Initialize the worker process by disposing old engine connections and
    re-creating the SQLAlchemy engine using the Flask application's configuration.
    Then re-attach the DatabaseManager instrumentation to the new engine.
    """
    if hasattr(db, 'engine'):
        db.engine.dispose()

    app = current_app._get_current_object()
    engine_options = app.config.get('SQLALCHEMY_ENGINE_OPTIONS', {})

    # Recreate a new engine
    db.engine = db.create_engine(db.engine.url, **engine_options)

    # Re-init instrumentation for the *new* engine
    with app.app_context():
        db_manager.init_app(app)

@worker_process_shutdown.connect
def cleanup_worker_process(**kwargs):
    """
    Cleanup database connections when the worker process shuts down.
    """
    if hasattr(db, 'engine'):
        db.engine.dispose()