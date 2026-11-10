"""Background worker pattern for billable QCloud requests.

Replace ``Queue`` with your job system (Celery, RQ, Arq, a database table).
The rules that matter for billing are the same:

- 429 (``RateLimitError``) and 402 were rejected before any provider work:
  re-enqueue after ``retry_after``, or stop until credits are added.
- 400/404 will not succeed on retry: fail the job.
- ``APIConnectionError``/``APITimeoutError`` after the request was sent, or a
  5xx, are *ambiguous*: the provider may have produced billable output. Mark
  the job for review with the request ID instead of replaying it.

Run: ``QCLOUD_API_KEY=... QCLOUD_MODEL=... python background_worker.py``
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from queue import Empty, Queue

from qcloud_ai import (
    APIConnectionError,
    APIError,
    BadRequestError,
    InsufficientCreditsError,
    NotFoundError,
    QCloud,
    RateLimitError,
)


@dataclass
class Job:
    id: str
    prompt: str
    not_before: float = 0.0
    attempts: int = 0
    result: str | None = None
    state: str = "queued"
    notes: list[str] = field(default_factory=list)


def process(client: QCloud, job: Job, queue: "Queue[Job]", model: str) -> None:
    job.attempts += 1
    try:
        reply = client.chat.completions.create(
            model=model, messages=[{"role": "user", "content": job.prompt}], max_tokens=200
        )
    except RateLimitError as error:
        job.not_before = time.monotonic() + (error.retry_after or 5)
        job.state = "queued"
        job.notes.append(f"rate limited, request {error.request_id}")
        queue.put(job)
    except InsufficientCreditsError as error:
        job.state = "blocked_on_credits"
        job.notes.append(f"insufficient credits, request {error.request_id}")
    except (BadRequestError, NotFoundError) as error:
        job.state = "failed"
        job.notes.append(f"{error.code or error.status_code}: {error.message}")
    except APIError as error:
        job.state = "needs_review"
        job.notes.append(f"server error {error.status_code}, request {error.request_id}")
    except APIConnectionError as error:
        job.state = "needs_review"
        job.notes.append(f"ambiguous connection failure: {type(error).__name__}")
    else:
        job.state = "done"
        job.result = reply.choices[0].message.content


def run(queue: "Queue[Job]", *, idle_exit: bool = True) -> list[Job]:
    model = os.environ["QCLOUD_MODEL"]
    finished: list[Job] = []
    # max_retries applies only to safe cases (429, never-sent connections, GETs).
    with QCloud(timeout=120, max_retries=2) as client:
        while True:
            try:
                job = queue.get(timeout=1)
            except Empty:
                if idle_exit:
                    return finished
                continue
            delay = job.not_before - time.monotonic()
            if delay > 0:
                time.sleep(min(delay, 60))
            process(client, job, queue, model)
            if job.state != "queued":
                finished.append(job)
                print(job.id, job.state, job.result or "; ".join(job.notes))


if __name__ == "__main__":
    jobs: "Queue[Job]" = Queue()
    for index, prompt in enumerate(["Name a prime number.", "Name a colour."]):
        jobs.put(Job(id=f"job-{index}", prompt=prompt))
    run(jobs)
