"""Read pages on every CPU core but one, handing results back in the order the pages come.

The window's thread adds files and takes results when they are ready, so it stays free while the
other cores read. A PDF is split into one task per page; an image file is one task.
"""

import os
from collections import deque
from concurrent.futures import Future, ProcessPoolExecutor, wait
from multiprocessing import get_context

from .reader import read_or_reason
from .sources import is_blank, page_count, read_pages
from .store import encode_page
from .template import Template

WORKERS = max(1, (os.cpu_count() or 1) - 1)  # one core is left for the window and saving

_template: Template | None = None


def _start(template: Template):
    global _template
    _template = template


def read_task(path: str, only: int | None, skip_blank: bool, template: Template | None = None) -> list | str:
    """[(page number, page, blank, (result, problem) or None when blank)] for a task, or why its file
    couldn't be opened. A read page comes back as its aligned image, already encoded for saving, and no
    page, so less is copied between processes; an unreadable page comes back whole, to be kept."""
    try:
        out = []
        for n, page in enumerate(read_pages(path, only), 1 if only is None else only + 1):
            blank = skip_blank and is_blank(page)
            read = None if blank else read_or_reason(page, template or _template)
            if read and read[0] is not None:
                read[0].aligned = encode_page(read[0].aligned)
                page = None
            out.append((n, page, blank, read))
        return out
    except (OSError, ValueError) as e:
        return str(e)


class PageReader:
    """Files in, results out in order: `add` files, then call `next` until `busy` is False."""

    def __init__(self, template: Template, skip_blank: bool, workers: int | None = None):
        self.template, self.skip_blank = template, skip_blank
        workers = WORKERS if workers is None else workers
        # spawn, not fork: a forked copy of a process running Qt threads can hang
        self.pool = (ProcessPoolExecutor(workers, get_context("spawn"), _start, (template,))
                     if workers > 1 else None)
        self.ahead = 2 * workers  # tasks given out at once, so no core waits
        self.todo: deque[tuple[str, int | None]] = deque()
        self.running: deque[tuple[str, int | None, Future]] = deque()

    def add(self, path: str):
        count = page_count(path)
        self.todo.extend((path, i) for i in range(count)) if count else self.todo.append((path, None))

    @property
    def busy(self) -> bool:
        return bool(self.todo or self.running)

    def next(self, timeout: float = 0.0) -> tuple[str, list | str] | None:
        """(file, what `read_task` gave) for the next task in order, or None while it is still being read."""
        if self.pool is None:
            if self.running:  # given out before the readers stopped
                return self._head(timeout)
            if not self.todo:
                return None
            path, only = self.todo.popleft()
            return path, read_task(path, only, self.skip_blank, self.template)
        while self.todo and len(self.running) < self.ahead:
            path, only = self.todo[0]
            try:
                future = self.pool.submit(read_task, path, only, self.skip_blank)
            except Exception:  # noqa: BLE001  the readers can't start or have died: read here from now on
                self.close()
                return self.next(timeout)
            self.todo.popleft()
            self.running.append((path, only, future))
        return self._head(timeout)

    def _head(self, timeout: float) -> tuple[str, list | str] | None:
        if not self.running or not wait([self.running[0][2]], timeout).done:
            return None
        path, only, future = self.running.popleft()
        try:
            return path, future.result()
        except Exception:  # noqa: BLE001  a worker died (out of memory, killed): read this page here instead
            return path, read_task(path, only, self.skip_blank, self.template)

    def stop(self) -> set[str]:
        """Stop reading; the files with pages not yet handed back."""
        left = {p for p, _ in self.todo} | {p for p, _, _ in self.running}
        self.todo.clear()
        self.running.clear()
        self.close()
        return left

    def close(self):
        if self.pool is not None:
            self.pool.shutdown(wait=False, cancel_futures=True)
            self.pool = None
