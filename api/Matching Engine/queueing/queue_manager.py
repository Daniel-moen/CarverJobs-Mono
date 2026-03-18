import queue
import threading
import uuid
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import datetime, timezone

from models.match_result import JobMatch
from services.matching_service import MatchingService

from .models import MatchRequest, MatchResult


class MatchQueue:
    def __init__(
        self,
        matching_service: MatchingService,
        max_queue_size: int = 100,
        worker_count: int = 3,
    ) -> None:
        if max_queue_size <= 0:
            raise ValueError("max_queue_size must be > 0")
        if worker_count <= 0:
            raise ValueError("worker_count must be > 0")
        self._matching_service = matching_service
        self._queue: queue.Queue[MatchRequest] = queue.Queue(maxsize=max_queue_size)
        self._executor = ThreadPoolExecutor(max_workers=worker_count)
        self._results: dict[str, Future[MatchResult]] = {}
        self._lock = threading.Lock()
        self._shutdown_event = threading.Event()
        self._dispatcher_thread = threading.Thread(target=self._dispatch_loop, daemon=True)
        self._dispatcher_thread.start()

    def submit(self, user, jobs, metadata: dict[str, str] | None = None) -> Future[MatchResult]:
        request_id = self._enqueue_request(user, jobs, metadata)
        with self._lock:
            return self._results[request_id]

    def enqueue(self, user, jobs, metadata: dict[str, str] | None = None) -> str:
        return self._enqueue_request(user, jobs, metadata)

    def get_result(self, request_id: str, timeout: float | None = None) -> MatchResult | None:
        with self._lock:
            future = self._results.get(request_id)
        if not future:
            return None
        return future.result(timeout=timeout)

    def pending_count(self) -> int:
        return self._queue.qsize()

    def shutdown(self, wait: bool = True) -> None:
        self._shutdown_event.set()
        if wait:
            self._dispatcher_thread.join(timeout=5)
        self._executor.shutdown(wait=wait, cancel_futures=False)

    def _enqueue_request(self, user, jobs, metadata: dict[str, str] | None) -> str:
        request_id = uuid.uuid4().hex
        request = MatchRequest(
            request_id=request_id,
            user=user,
            jobs=jobs,
            metadata=metadata or {},
        )
        with self._lock:
            if request_id in self._results:
                raise RuntimeError("Duplicate request id generated")
            placeholder: Future[MatchResult] = Future()
            self._results[request_id] = placeholder
        self._queue.put(request, block=True)
        return request_id

    def _dispatch_loop(self) -> None:
        while not self._shutdown_event.is_set():
            try:
                request = self._queue.get(timeout=0.2)
            except queue.Empty:
                continue
            with self._lock:
                placeholder = self._results.get(request.request_id)
            if not placeholder:
                self._queue.task_done()
                continue
            future = self._executor.submit(self._process_request, request)
            future.add_done_callback(lambda f, p=placeholder: self._complete_placeholder(p, f))
            self._queue.task_done()

    @staticmethod
    def _complete_placeholder(placeholder: Future[MatchResult], future: Future[MatchResult]) -> None:
        try:
            placeholder.set_result(future.result())
        except Exception as exc:  # noqa: BLE001
            placeholder.set_exception(exc)

    def _process_request(self, request: MatchRequest) -> MatchResult:
        started = datetime.now(timezone.utc)
        try:
            matches: list[JobMatch] = self._matching_service.match_user_to_jobs(
                request.user,
                request.jobs,
            )
            finished = datetime.now(timezone.utc)
            return MatchResult(
                request_id=request.request_id,
                matches=matches,
                started_at=started,
                finished_at=finished,
                error=None,
            )
        except Exception as exc:  # noqa: BLE001
            finished = datetime.now(timezone.utc)
            return MatchResult(
                request_id=request.request_id,
                matches=[],
                started_at=started,
                finished_at=finished,
                error=str(exc),
            )
