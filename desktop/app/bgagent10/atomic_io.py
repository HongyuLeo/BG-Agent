"""Bounded Windows sharing-conflict recovery; no training/rules exceptions hidden."""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import time
import uuid

RETRYABLE_WINERRORS = frozenset({5, 32, 33})


def sharing_conflict(error: BaseException) -> bool:
    return isinstance(error, OSError) and getattr(error, 'winerror', None) in RETRYABLE_WINERRORS


def retry_io(operation, timeout: float = 2.0):
    deadline = time.monotonic() + timeout
    delay = .01
    while True:
        try:
            return operation()
        except OSError as error:
            remaining = deadline - time.monotonic()
            if not sharing_conflict(error) or remaining <= 0:
                raise
            time.sleep(min(delay, remaining))
            delay = min(.1, delay * 2)


def _stderr(value) -> None:
    try:
        sys.stderr.write(json.dumps(value, ensure_ascii=False, default=str) + '\n')
        sys.stderr.flush()
    except Exception:
        # Reporting must never replace the original training exception.
        pass


def atomic_write(path, write, *, timeout: float = 2.0) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    primary = None
    try:
        with retry_io(lambda: temporary.open('xb'), timeout) as stream:
            write(stream)
            stream.flush()
            os.fsync(stream.fileno())
        retry_io(lambda: os.replace(temporary, path), timeout)
    except BaseException as error:
        primary = error
        raise
    finally:
        try:
            retry_io(lambda: temporary.unlink(missing_ok=True), .25)
        except OSError as cleanup_error:
            if primary is not None:
                primary.add_note(f'Could not remove temporary file {temporary}: {cleanup_error}')
            _stderr(dict(event='atomic_temporary_cleanup_failed', path=str(temporary), error=str(cleanup_error)))


def atomic_json(path, value, *, timeout: float = 2.0) -> None:
    # Validate serialization before any write. Invalid values are never retried.
    data = json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False).encode('utf8')
    atomic_write(path, lambda stream: stream.write(data), timeout=timeout)


def progress_json(path, value) -> bool:
    try:
        atomic_json(path, value, timeout=.25)
        return True
    except OSError as error:
        if not sharing_conflict(error):
            raise
        _stderr(dict(event='progress_write_deferred', path=str(path), error=str(error)))
        return False


def report_failure(run_dir, error: BaseException, traceback_text: str, *, checkpoint=None):
    """Independent no-rename fallback and stderr retain primary+reporting failures."""
    directory = Path(run_dir) / 'errors'
    value = dict(error=str(error), error_type=type(error).__name__, traceback=traceback_text,
                 checkpoint=checkpoint, time=time.time())
    path = directory / ('fatal-' + str(time.time_ns()) + '-' + uuid.uuid4().hex + '.json')
    try:
        atomic_json(path, value)
        return path
    except Exception as reporting_error:
        value['atomic_report_error'] = repr(reporting_error)
        fallback = directory / ('fatal-fallback-' + uuid.uuid4().hex + '.json')
        try:
            directory.mkdir(parents=True, exist_ok=True)
            # This unique file needs no rename and is only an emergency record.
            with fallback.open('x', encoding='utf8') as stream:
                json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
                stream.flush()
                os.fsync(stream.fileno())
            return fallback
        except Exception as fallback_error:
            value['fallback_report_error'] = repr(fallback_error)
            _stderr(dict(event='fatal_report_fallback', **value))
            return None


def report_status_failure(error: BaseException) -> None:
    _stderr(dict(event='failed_status_write_failed', error=repr(error)))
