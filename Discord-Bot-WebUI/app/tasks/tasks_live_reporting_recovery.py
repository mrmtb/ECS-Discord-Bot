"""
Live Reporting Recovery Task (Enhanced with Database Tracking)

This module ensures that matches that should have tasks running don't fall through the cracks.
Uses database-backed task tracking to catch missed operations even when Redis expires.

Key improvements over V1:
- Database is source of truth (survives Redis TTL expiration)
- Catches tasks scheduled >2 days in advance
- Comprehensive logging for debugging
- Cleans up stale/expired tasks
"""

import logging
from datetime import datetime, timedelta
from typing import Dict, Any

from celery import current_app as celery
from sqlalchemy.exc import SQLAlchemyError

from app.decorators import celery_task
from app.utils.task_session_manager import task_session
from app.models import MLSMatch, ScheduledTask, TaskType, TaskState, MatchStatus
from app.models.live_reporting_session import LiveReportingSession

# How late a scheduled task must be before the recovery net treats it as missed.
# The net runs every 5 minutes and the tasks it audits are scheduled on the same
# round times, so without this it races the real scheduler and wins by
# milliseconds -- firing duplicates and reporting a failure that never happened.
RECOVERY_GRACE = timedelta(seconds=90)

logger = logging.getLogger(__name__)


@celery_task(
    name='app.tasks.tasks_live_reporting_recovery.recover_missing_tasks',
    queue='celery',
    max_retries=1,
    soft_time_limit=120,  # 2 minutes
    time_limit=180,       # 3 minutes
    retry_backoff=True,
    retry_backoff_max=120,
    retry_jitter=True,
    autoretry_for=(Exception,),
    default_retry_delay=60
)
def recover_missing_tasks(self, session) -> Dict[str, Any]:
    """
    Enhanced recovery task using database-backed task tracking.

    Recovers:
    1. Thread creations that were scheduled but never executed
    2. Live reporting sessions that should have started but didn't
    3. Cleans up expired tasks

    Returns:
        Dictionary with recovery statistics
    """
    try:
        from datetime import timezone
        from app.tasks.match_scheduler import (
            create_mls_match_thread_task,
            start_mls_live_reporting_task
        )
        from app.utils.safe_redis import get_safe_redis

        # Prevent duplicate execution using Redis lock
        redis_client = get_safe_redis()
        lock_key = "task_lock:recover_missing_tasks"
        lock_acquired = False

        if redis_client and redis_client.is_available:
            lock_acquired = redis_client.set(lock_key, self.request.id, nx=True, ex=240)
            if not lock_acquired:
                logger.info("Another recovery instance is running, skipping")
                return {
                    'success': True,
                    'message': 'Skipped - another instance running',
                    'recovered': 0
                }

        try:
            now = datetime.now(timezone.utc)
            recovered_threads = 0
            recovered_reporting = 0
            expired_tasks = 0

            logger.debug("=" * 70)
            logger.debug(f"🔍 Starting task recovery at {now.isoformat()}")
            logger.debug("=" * 70)

            # ===================================================================
            # STEP 1: Recover thread creation tasks that are overdue
            # ===================================================================
            logger.debug("\n📋 Step 1: Checking for missing thread creations...")

            # RECOVERY_GRACE, not `now`. This task runs on crontab(*/5) and the
            # tasks it audits are themselves scheduled on round times, so both
            # fire in the SAME second -- and a task scheduled for 16:25:00.000
            # looked "overdue" at 16:25:00.211. Every recovery in the logs was a
            # photo finish of this kind (overdue by 41ms, 74ms, 80ms, 102ms),
            # each one dispatching a DUPLICATE of a task the scheduler was
            # already running, under a WARNING claiming "something upstream
            # failed to schedule these". Nothing had failed. A safety net must
            # only act on work that is meaningfully late.
            pending_thread_tasks = ScheduledTask.get_pending_tasks(
                session,
                task_type=TaskType.THREAD_CREATION,
                now=now - RECOVERY_GRACE
            )

            logger.debug(f"Found {len(pending_thread_tasks)} overdue thread creation tasks")

            for task in pending_thread_tasks:
                try:
                    match = session.query(MLSMatch).get(task.match_id)
                    if not match:
                        logger.warning(f"Task {task.id}: Match {task.match_id} not found, marking expired")
                        task.mark_expired()
                        continue

                    if match.thread_created:
                        logger.info(f"Task {task.id}: Thread already created for match {task.match_id}, marking completed")
                        task.mark_completed()
                        continue

                    # Check if thread creation time is way overdue (>6 hours)
                    overdue_duration = now - task.scheduled_time
                    if overdue_duration > timedelta(hours=6):
                        logger.warning(f"Task {task.id}: Thread creation for match {task.match_id} is {overdue_duration} overdue, marking expired")
                        task.mark_expired()
                        expired_tasks += 1
                        continue

                    # Recover: create thread immediately
                    logger.warning(f"🔧 RECOVERING: Thread creation for match {task.match_id} ({match.opponent})")
                    logger.warning(f"   Scheduled: {task.scheduled_time.isoformat()}, Overdue by: {overdue_duration}")

                    celery_task = create_mls_match_thread_task.apply_async(args=[match.id])
                    task.mark_running(celery_task.id)
                    recovered_threads += 1

                    logger.info(f"   ✅ Rescheduled with task_id: {celery_task.id}")

                except Exception as e:
                    logger.error(f"Error recovering thread task {task.id}: {e}", exc_info=True)
                    task.mark_failed(str(e))

            # ===================================================================
            # STEP 2: Recover live reporting tasks that are overdue
            # ===================================================================
            logger.debug("\n📺 Step 2: Checking for missing live reporting sessions...")

            pending_reporting_tasks = ScheduledTask.get_pending_tasks(
                session,
                task_type=TaskType.LIVE_REPORTING_START,
                now=now - RECOVERY_GRACE   # see RECOVERY_GRACE above
            )

            logger.debug(f"Found {len(pending_reporting_tasks)} overdue live reporting tasks")

            for task in pending_reporting_tasks:
                try:
                    match = session.query(MLSMatch).get(task.match_id)
                    if not match:
                        logger.warning(f"Task {task.id}: Match {task.match_id} not found, marking expired")
                        task.mark_expired()
                        continue

                    if not match.thread_created or not match.discord_thread_id:
                        logger.warning(f"Task {task.id}: Match {task.match_id} has no thread, marking expired")
                        task.mark_expired()
                        expired_tasks += 1
                        continue

                    # Check if session already exists
                    existing_session = session.query(LiveReportingSession).filter(
                        LiveReportingSession.match_id == str(match.match_id),
                        LiveReportingSession.is_active == True
                    ).first()

                    if existing_session:
                        logger.info(f"Task {task.id}: Live session already exists for match {task.match_id}, marking completed")
                        task.mark_completed()
                        continue

                    # Check if match has already finished (>3 hours past start)
                    match_age = now - match.date_time
                    if match_age > timedelta(hours=3):
                        logger.warning(f"Task {task.id}: Match {task.match_id} finished {match_age} ago, marking expired")
                        task.mark_expired()
                        expired_tasks += 1
                        continue

                    # Recover: start live reporting immediately
                    overdue_duration = now - task.scheduled_time
                    logger.warning(f"🔧 RECOVERING: Live reporting for match {task.match_id} ({match.opponent})")
                    logger.warning(f"   Scheduled: {task.scheduled_time.isoformat()}, Overdue by: {overdue_duration}")

                    celery_task = start_mls_live_reporting_task.apply_async(args=[match.id])
                    task.mark_running(celery_task.id)
                    match.live_reporting_status = MatchStatus.RUNNING
                    recovered_reporting += 1

                    logger.info(f"   ✅ Rescheduled with task_id: {celery_task.id}")

                except Exception as e:
                    logger.error(f"Error recovering reporting task {task.id}: {e}", exc_info=True)
                    task.mark_failed(str(e))

            # ===================================================================
            # STEP 3: Clean up very old expired tasks (>7 days overdue)
            # ===================================================================
            logger.debug("\n🧹 Step 3: Cleaning up very old tasks...")

            expiry_cutoff = now - timedelta(days=7)
            very_old_tasks = session.query(ScheduledTask).filter(
                ScheduledTask.state == TaskState.SCHEDULED,
                ScheduledTask.scheduled_time < expiry_cutoff
            ).all()

            logger.debug(f"Found {len(very_old_tasks)} very old tasks to expire")

            for task in very_old_tasks:
                task.mark_expired()
                expired_tasks += 1
                logger.debug(f"Expired task {task.id} (scheduled {task.scheduled_time.isoformat()})")

            # ===================================================================
            # STEP 4: Mark old "not_started" matches as completed
            # ===================================================================
            logger.debug("\n🏁 Step 4: Marking old not_started matches as completed...")

            completed_old_matches = 0
            old_match_cutoff = now - timedelta(hours=6)

            old_not_started_matches = session.query(MLSMatch).filter(
                MLSMatch.live_reporting_status == MatchStatus.NOT_STARTED,
                MLSMatch.date_time < old_match_cutoff
            ).all()

            logger.debug(f"Found {len(old_not_started_matches)} old not_started matches")

            for match in old_not_started_matches:
                match.live_reporting_status = MatchStatus.COMPLETED
                completed_old_matches += 1
                logger.info(f"Marked old match {match.id} ({match.opponent}) as completed")

            # Commit all changes
            session.commit()

            # ===================================================================
            # Summary
            # ===================================================================
            # This task runs every 5 minutes and recovers nothing the vast
            # majority of the time. It used to print a 20-line banner on every
            # run regardless -- ~5,800 lines a day of zeros, which is most of
            # celery_tasks.log and drowns the runs that DID do something.
            #
            # Say one line when there is nothing to report; stay loud (and at
            # WARNING, because recovery firing means something upstream failed)
            # only when work was actually done. Full per-step detail is still
            # available at DEBUG.
            recovered_total = (recovered_threads + recovered_reporting
                               + expired_tasks + completed_old_matches)
            if recovered_total:
                logger.warning(
                    f"Task recovery ACTED: {recovered_threads} threads, "
                    f"{recovered_reporting} reporting, {expired_tasks} expired, "
                    f"{completed_old_matches} old matches completed "
                    f"-- something upstream failed to schedule these"
                )
            else:
                logger.info("Task recovery: nothing to recover")

            return {
                'success': True,
                'timestamp': now.isoformat(),
                'recovered_threads': recovered_threads,
                'recovered_reporting': recovered_reporting,
                'expired_tasks': expired_tasks,
                'completed_old_matches': completed_old_matches,
                'total_recovered': recovered_threads + recovered_reporting + completed_old_matches
            }

        finally:
            # Release Redis lock
            if redis_client and redis_client.is_available and lock_acquired:
                redis_client.delete(lock_key)

    except SQLAlchemyError as e:
        logger.error(f"Database error in recovery task: {e}", exc_info=True)
        session.rollback()
        return {
            'success': False,
            'error': str(e),
            'error_type': 'database'
        }

    except Exception as e:
        logger.error(f"Unexpected error in recovery task: {e}", exc_info=True)
        return {
            'success': False,
            'error': str(e),
            'error_type': 'general'
        }


# Keep the old function name for backward compatibility (Python code imports only).
# NOTE: This alias does NOT create a new Celery task registration.
# The task is registered as 'app.tasks.tasks_live_reporting_recovery.recover_missing_tasks'.
# Any Celery beat schedules or apply_async calls must use the registered name.
check_and_start_missing_live_reporting = recover_missing_tasks


@celery_task(
    name='app.tasks.tasks_live_reporting_recovery.monitor_stalled_sessions',
    queue='celery',
    max_retries=0,
    soft_time_limit=30,
    time_limit=45,
)
def monitor_stalled_sessions(self, session) -> Dict[str, Any]:
    """
    Flag active LiveReportingSessions that are silently stalled.

    Two failure modes this catches:
    1. Session row created but never polled by the realtime service
       (update_count=0 after >3min since started_at) — e.g. realtime
       container down, ESPN client returning only errors, DB connectivity
       between services broken.
    2. Session was polling but stopped
       (last_update >5min ago while still is_active=True) — e.g. service
       hung, ESPN persistent failures.

    Logs an ERROR (visible in container logs and errors.log) and writes a
    'watchdog' entry to the admin UI live-reporting event ring buffer so
    the condition is discoverable in-app without having to grep container
    logs.
    """
    from datetime import timezone
    from app.services.live_reporting_event_log import record_event as log_event

    now = datetime.now(timezone.utc)
    alerts = []

    active_sessions = session.query(LiveReportingSession).filter_by(is_active=True).all()

    for s in active_sessions:
        started_at = s.started_at
        last_update = s.last_update
        if started_at and started_at.tzinfo is None:
            started_at = started_at.replace(tzinfo=timezone.utc)
        if last_update and last_update.tzinfo is None:
            last_update = last_update.replace(tzinfo=timezone.utc)

        age = (now - started_at).total_seconds() if started_at else 0
        since_update = (now - last_update).total_seconds() if last_update else None

        # Gate on last_update, NOT update_count. update_count counts updates
        # SENT, and a session legitimately sends nothing between creation
        # (~20min before kickoff) and the first live event -- so the old
        # `update_count == 0` test called every healthy pre-match session
        # "never polled" at ERROR every 2 minutes, while the service was in
        # fact polling ESPN every 10s. last_update is now stamped on every
        # successful poll (see realtime_reporting_service._touch_session_poll),
        # so its absence really does mean nothing is servicing this session.
        issue = None
        if last_update is None and age > 180:
            issue = f"no successful poll recorded (age={age:.0f}s)"
        elif since_update is not None and since_update > 300:
            issue = f"polling stalled (last_update={since_update:.0f}s ago)"

        if not issue:
            continue

        logger.error(
            f"STALLED LIVE SESSION id={s.id} match_id={s.match_id} "
            f"competition={s.competition} thread_id={s.thread_id}: {issue}"
        )
        try:
            log_event(
                stage="watchdog", outcome="error",
                session_id=s.id, match_id=str(s.match_id),
                message=f"Stalled session: {issue}",
                context={
                    'update_count': s.update_count,
                    'error_count': s.error_count,
                    'last_error': s.last_error,
                    'last_status': s.last_status,
                    'age_seconds': int(age),
                    'since_update_seconds': int(since_update) if since_update is not None else None,
                },
            )
        except Exception as log_err:
            logger.warning(f"Failed to write watchdog event log for session {s.id}: {log_err}")

        alerts.append({
            'session_id': s.id,
            'match_id': s.match_id,
            'issue': issue,
        })

    return {
        'success': True,
        'checked': len(active_sessions),
        'alerts': len(alerts),
        'details': alerts,
    }
