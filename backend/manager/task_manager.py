"""
Multi-threaded Task Management System

A thread-safe task management system that tracks tasks across three states:
- PENDING: Tasks waiting to be executed
- IN_PROGRESS: Tasks currently being executed
- DONE: Tasks that have been completed

Features:
- Thread-safe operations using locks and queues
- Task prioritization
- Worker thread pool
- Real-time monitoring and statistics
- No external database dependencies
"""

import threading
import queue
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional, Callable, Any
import logging


class TaskStatus(Enum):
    """Enum representing the possible states of a task."""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    DONE = "done"
    FAILED = "failed"


class TaskPriority(Enum):
    """Enum representing task priority levels."""

    LOW = 1
    NORMAL = 2
    HIGH = 3
    CRITICAL = 4


@dataclass
class Task:
    """
    Represents a task in the system with metadata and execution function.
    """

    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    description: str = ""
    function: Optional[Callable] = None
    args: tuple = field(default_factory=tuple)
    kwargs: dict = field(default_factory=dict)
    priority: TaskPriority = TaskPriority.NORMAL
    status: TaskStatus = TaskStatus.PENDING
    created_at: datetime = field(default_factory=datetime.now)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    result: Any = None
    error: Optional[str] = None
    worker_id: Optional[str] = None

    # File processing specific fields
    work_id: Optional[str] = None
    original_filename: Optional[str] = None
    file_path: Optional[str] = None
    file_size: Optional[int] = None
    progress_percentage: int = 0
    metadata: Optional[dict] = field(default_factory=dict)

    def __lt__(self, other):
        """Allow sorting by priority (higher priority first)."""
        return self.priority.value > other.priority.value

    def execute(self) -> Any:
        """Execute the task function with provided arguments."""
        if self.function is None:
            raise ValueError("Task has no function to execute")

        try:
            self.status = TaskStatus.IN_PROGRESS
            self.started_at = datetime.now()
            self.result = self.function(*self.args, **self.kwargs)
            self.status = TaskStatus.DONE
            self.completed_at = datetime.now()
            return self.result
        except Exception as e:
            self.status = TaskStatus.FAILED
            self.error = str(e)
            self.completed_at = datetime.now()
            raise

    def get_duration(self) -> Optional[float]:
        """Get task execution duration in seconds."""
        if self.started_at and self.completed_at:
            return (self.completed_at - self.started_at).total_seconds()
        return None

    def to_dict(self) -> dict:
        """Convert task to dictionary for serialization."""
        return {
            "id": self.id,
            "work_id": self.work_id,
            "description": self.description,
            "priority": self.priority.name,
            "status": self.status.value,
            "created_at": self.created_at.isoformat(),
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": (
                self.completed_at.isoformat() if self.completed_at else None
            ),
            "result": str(self.result) if self.result is not None else None,
            "error": self.error,
            "worker_id": self.worker_id,
            "duration": self.get_duration(),
            "original_filename": self.original_filename,
            "file_path": self.file_path,
            "file_size": self.file_size,
            "progress_percentage": self.progress_percentage,
            "metadata": self.metadata,
        }


class TaskManager:
    """
    Thread-safe task management system that coordinates task execution
    across multiple worker threads.
    """

    def __init__(self, max_workers: int = 1):
        """
        Initialize the task manager.

        Args:
            max_workers: Maximum number of worker threads
        """
        self.max_workers = max_workers
        self._lock = threading.RLock()
        self._pending_queue = queue.PriorityQueue()
        self._in_progress: Dict[str, Task] = {}
        self._done: Dict[str, Task] = {}
        self._failed: Dict[str, Task] = {}
        self._workers: List[threading.Thread] = []
        self._shutdown_event = threading.Event()
        self._stats_lock = threading.Lock()

        # Statistics
        self._total_tasks_added = 0
        self._total_tasks_completed = 0
        self._total_tasks_failed = 0

        # Setup logging
        self.logger = logging.getLogger(__name__)

        # Start worker threads
        self._start_workers()

    def _start_workers(self):
        """Start worker threads."""
        for i in range(self.max_workers):
            worker = threading.Thread(
                target=self._worker_thread, name=f"TaskWorker-{i + 1}", daemon=True
            )
            worker.start()
            self._workers.append(worker)

    def _worker_thread(self):
        """Worker thread main loop."""
        worker_id = threading.current_thread().name

        while not self._shutdown_event.is_set():
            try:
                # Get next task from queue (blocking with timeout)
                priority_task = self._pending_queue.get(timeout=1.0)
                task = priority_task[
                    2
                ]  # Extract task from priority tuple (priority, timestamp, task)

                # Move task to in-progress
                with self._lock:
                    task.worker_id = worker_id
                    self._in_progress[task.id] = task

                try:
                    # Execute the task
                    task.execute()

                    # Move to completed
                    with self._lock:
                        del self._in_progress[task.id]
                        self._done[task.id] = task
                        with self._stats_lock:
                            self._total_tasks_completed += 1

                except Exception as e:
                    # Move to failed
                    with self._lock:
                        del self._in_progress[task.id]
                        self._failed[task.id] = task
                        with self._stats_lock:
                            self._total_tasks_failed += 1

                    self.logger.error(
                        f"Worker {worker_id} failed to execute task {task.id}: {e}"
                    )

                finally:
                    self._pending_queue.task_done()

            except queue.Empty:
                # Timeout waiting for task, continue loop
                continue
            except Exception as e:
                self.logger.error(f"Worker {worker_id} encountered error: {e}")

    def add_task(
        self,
        description: str,
        function: Callable,
        args: tuple = (),
        kwargs: dict = None,
        priority: TaskPriority = TaskPriority.NORMAL,
        work_id: str = None,
        original_filename: str = None,
        file_path: str = None,
        file_size: int = None,
        metadata: dict = None,
    ) -> str:
        """
        Add a new task to the system.

        Args:
            description: Human-readable task description
            function: Function to execute
            args: Positional arguments for the function
            kwargs: Keyword arguments for the function
            priority: Task priority level
            work_id: Optional work ID for file processing
            original_filename: Original filename for file processing
            file_path: File path for file processing
            file_size: File size for file processing
            metadata: Additional metadata

        Returns:
            Task ID
        """
        if kwargs is None:
            kwargs = {}
        if metadata is None:
            metadata = {}

        task = Task(
            description=description,
            function=function,
            args=args,
            kwargs=kwargs,
            priority=priority,
            work_id=work_id,
            original_filename=original_filename,
            file_path=file_path,
            file_size=file_size,
            metadata=metadata,
        )

        # Add to pending queue with priority
        priority_tuple = (
            priority.value * -1,
            time.time(),
            task,
        )  # Negative for descending order
        self._pending_queue.put(priority_tuple)

        with self._stats_lock:
            self._total_tasks_added += 1

        return task.id

    def get_task(self, task_id: str) -> Optional[Task]:
        """Get a task by ID from any state."""
        with self._lock:
            # Check in-progress first
            if task_id in self._in_progress:
                return self._in_progress[task_id]

            # Check completed
            if task_id in self._done:
                return self._done[task_id]

            # Check failed
            if task_id in self._failed:
                return self._failed[task_id]

        # Check pending queue (expensive operation)
        temp_queue = queue.Queue()
        found_task = None

        try:
            while True:
                try:
                    priority_task = self._pending_queue.get_nowait()
                    task = priority_task[2]  # Extract task from priority tuple
                    if task.id == task_id:
                        found_task = task
                    temp_queue.put(priority_task)
                except queue.Empty:
                    break

            # Put everything back
            while not temp_queue.empty():
                self._pending_queue.put(temp_queue.get())

        except Exception as e:
            self.logger.error(f"Error searching pending queue: {e}")

        return found_task

    def get_task_by_work_id(self, work_id: str) -> Optional[Task]:
        """Get a task by work_id from any state."""
        with self._lock:
            # Check all collections
            for task_dict in [self._in_progress, self._done, self._failed]:
                for task in task_dict.values():
                    if task.work_id == work_id:
                        return task

        # Check pending queue
        temp_queue = queue.Queue()
        found_task = None

        try:
            while True:
                try:
                    priority_task = self._pending_queue.get_nowait()
                    task = priority_task[2]
                    if task.work_id == work_id:
                        found_task = task
                    temp_queue.put(priority_task)
                except queue.Empty:
                    break

            # Put everything back
            while not temp_queue.empty():
                self._pending_queue.put(temp_queue.get())

        except Exception as e:
            self.logger.error(f"Error searching pending queue: {e}")

        return found_task

    def update_task_progress(self, task_id: str, progress_percentage: int):
        """Update task progress percentage."""
        with self._lock:
            if task_id in self._in_progress:
                self._in_progress[task_id].progress_percentage = progress_percentage

    def update_task_metadata(self, task_id: str, metadata_update: dict):
        """Update task metadata."""
        with self._lock:
            task = None
            if task_id in self._in_progress:
                task = self._in_progress[task_id]
            elif task_id in self._done:
                task = self._done[task_id]
            elif task_id in self._failed:
                task = self._failed[task_id]

            if task:
                if task.metadata is None:
                    task.metadata = {}
                task.metadata.update(metadata_update)

    def get_pending_tasks(self) -> List[Task]:
        """Get all pending tasks."""
        tasks = []
        temp_queue = queue.Queue()

        try:
            while True:
                try:
                    priority_task = self._pending_queue.get_nowait()
                    task = priority_task[2]  # Extract task from priority tuple
                    tasks.append(task)
                    temp_queue.put(priority_task)
                except queue.Empty:
                    break

            # Put everything back
            while not temp_queue.empty():
                self._pending_queue.put(temp_queue.get())

        except Exception as e:
            self.logger.error(f"Error getting pending tasks: {e}")

        return sorted(
            tasks, key=lambda t: (t.priority.value, t.created_at), reverse=True
        )

    def get_in_progress_tasks(self) -> List[Task]:
        """Get all in-progress tasks."""
        with self._lock:
            return list(self._in_progress.values())

    def get_done_tasks(self) -> List[Task]:
        """Get all completed tasks."""
        with self._lock:
            return list(self._done.values())

    def get_failed_tasks(self) -> List[Task]:
        """Get all failed tasks."""
        with self._lock:
            return list(self._failed.values())

    def get_statistics(self) -> Dict[str, Any]:
        """Get system statistics."""
        with self._stats_lock:
            with self._lock:
                pending_count = self._pending_queue.qsize()
                in_progress_count = len(self._in_progress)
                done_count = len(self._done)
                failed_count = len(self._failed)

                return {
                    "total_added": self._total_tasks_added,
                    "total_completed": self._total_tasks_completed,
                    "total_failed": self._total_tasks_failed,
                    "pending": pending_count,
                    "in_progress": in_progress_count,
                    "done": done_count,
                    "failed": failed_count,
                    "workers": self.max_workers,
                    "active_workers": len([w for w in self._workers if w.is_alive()]),
                }

    def wait_for_completion(self, timeout: Optional[float] = None) -> bool:
        """
        Wait for all pending tasks to complete.

        Args:
            timeout: Maximum time to wait in seconds

        Returns:
            True if all tasks completed, False if timeout
        """
        start_time = time.time()

        while True:
            stats = self.get_statistics()
            if stats["pending"] == 0 and stats["in_progress"] == 0:
                return True

            if timeout and (time.time() - start_time) > timeout:
                return False

            time.sleep(0.1)

    def shutdown(self, wait: bool = True, timeout: Optional[float] = None):
        """
        Shutdown the task manager and all worker threads.

        Args:
            wait: Whether to wait for current tasks to complete
            timeout: Maximum time to wait for shutdown
        """

        if wait:
            self.wait_for_completion(timeout)

        # Signal shutdown
        self._shutdown_event.set()

        # Wait for workers to finish
        for worker in self._workers:
            if worker.is_alive():
                worker.join(timeout=1.0)

    def clear_completed_tasks(self):
        """Clear all completed and failed tasks from memory."""
        with self._lock:
            self._done.clear()
            self._failed.clear()

    def print_status(self):
        """Print current system status to console."""
        stats = self.get_statistics()

        status_lines = [
            "\n" + "=" * 50,
            "TASK MANAGER STATUS",
            "=" * 50,
            f"Total Tasks Added: {stats['total_added']}",
            f"Total Completed: {stats['total_completed']}",
            f"Total Failed: {stats['total_failed']}",
            f"Pending: {stats['pending']}",
            f"In Progress: {stats['in_progress']}",
            f"Done: {stats['done']}",
            f"Failed: {stats['failed']}",
            f"Workers: {stats['active_workers']}/{stats['workers']}",
            "=" * 50,
        ]
        self.logger.info("\n".join(status_lines))

        # Show recent in-progress tasks
        in_progress = self.get_in_progress_tasks()
        if in_progress:
            in_progress_lines = ["\nIN PROGRESS TASKS:"]
            for task in in_progress[:5]:  # Show max 5
                duration = (
                    time.time() - task.started_at.timestamp() if task.started_at else 0
                )
                in_progress_lines.append(
                    f"  {task.id[:8]}... - {task.description} ({duration:.1f}s) [Worker: {task.worker_id}]"
                )
            self.logger.info("\n".join(in_progress_lines))

        # Show recent pending tasks
        pending = self.get_pending_tasks()
        if pending:
            pending_lines = [
                f"\nNEXT PENDING TASKS (showing {min(5, len(pending))} of {len(pending)}):"
            ]
            for task in pending[:5]:
                wait_time = time.time() - task.created_at.timestamp()
                pending_lines.append(
                    f"  {task.id[:8]}... - {task.description} (waiting {wait_time:.1f}s) [Priority: {task.priority.name}]"
                )
            self.logger.info("\n".join(pending_lines))
