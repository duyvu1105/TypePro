"""Per-target deadlines with explicit outcomes, preserving the caller's timer."""
from contextlib import contextmanager
import signal
import time


class QueryTimeout(TimeoutError):
    pass


@contextmanager
def query_deadline(seconds):
    if seconds<=0:
        yield
        return
    def expired(signum,frame):
        raise QueryTimeout('graph target deadline exceeded')
    previous_handler=signal.getsignal(signal.SIGALRM)
    started=time.monotonic()
    previous_timer=signal.setitimer(signal.ITIMER_REAL,0)
    signal.signal(signal.SIGALRM,expired)
    signal.setitimer(signal.ITIMER_REAL,min(seconds,previous_timer[0]) if previous_timer[0] else seconds)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL,0)
        signal.signal(signal.SIGALRM,previous_handler)
        if previous_timer[0]:
            signal.setitimer(signal.ITIMER_REAL,max(.000001,previous_timer[0]-(time.monotonic()-started)),previous_timer[1])
