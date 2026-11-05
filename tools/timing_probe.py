"""External host timing windows. No disk writes or changes to production clocks."""
import asyncio
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor


class TimingObservations:
    def __init__(self, capacity=65536, clock=time.perf_counter_ns):
        if type(capacity) is not int or capacity < 1:
            raise ValueError('positive timing capacity required')
        self.capacity, self.clock = capacity, clock
        self.rows = []
        self.dropped = 0
        self.record_total_ns = self.record_max_ns = 0

    def record(self, kind, started, finished, **fields):
        before = self.clock()
        if finished < started:
            raise ValueError('timing clock moved backwards')
        if len(self.rows) < self.capacity:
            self.rows.append(dict(kind=kind, started_ns=started, finished_ns=finished, **fields))
        else:
            self.dropped += 1
        elapsed = self.clock() - before
        self.record_total_ns += elapsed
        self.record_max_ns = max(self.record_max_ns, elapsed)

    def call(self, kind, operation, *args, metadata=None, **kwargs):
        started = self.clock()
        try:
            return operation(*args, **kwargs)
        finally:
            finished = self.clock()
            self.record(kind, started, finished, **(metadata or {}))

    async def loop_probe(self, period=.05, sleep=asyncio.sleep):
        while True:
            deadline = self.clock() + round(period * 1_000_000_000)
            await sleep(period)
            finished = self.clock()
            self.record('loop_delay', min(deadline, finished), finished)

    def report(self):
        return dict(schema=1, capacity=self.capacity, dropped=self.dropped,
                    record_total_ns=self.record_total_ns, record_max_ns=self.record_max_ns,
                    rows=list(self.rows))


class AsyncStatusPublisher:
    """One owned status write at a time; drain uncancellable I/O before shutdown."""
    def __init__(self, timing=None):
        self.timing = timing
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='qualification-status')
        self.pending = None
        self.closed = False

    async def call(self, operation, *args):
        if self.closed or self.pending is not None:
            raise RuntimeError('status publisher closed or already writing')
        span = {}
        def perform():
            span['started'] = time.perf_counter_ns()
            try:
                return operation(*args)
            finally:
                span['finished'] = time.perf_counter_ns()
        self.pending = asyncio.get_running_loop().run_in_executor(self.executor, perform)
        cancelled = None
        try:
            while True:
                try:
                    result = await asyncio.shield(self.pending)
                    break
                except asyncio.CancelledError as error:
                    if self.pending.cancelled():
                        raise
                    cancelled = error
        finally:
            self.pending = None
            if self.timing and 'finished' in span:
                self.timing.record('status', span['started'], span['finished'])
        if cancelled is not None:
            raise cancelled
        return result

    def close(self):
        if self.pending is not None:
            raise RuntimeError('status publisher closed before I/O drained')
        self.executor.shutdown(wait=True)
        self.closed = True


def review_timing(raw, events):
    """Join original audit stamps to measured spans; overlapping windows aren't causes."""
    def require(condition, message):
        if not condition:
            raise ValueError(message)
    require(raw['schema'] == 1 and raw['dropped'] == 0, 'incomplete timing probe')
    rows = raw['rows']
    require(0 < len(rows) <= raw['capacity'], 'invalid timing count')
    counts = Counter(row['kind'] for row in rows)
    require({'audit', 'status', 'loop_delay'} <= set(counts) <= {'audit', 'status', 'loop_delay', 'status_view',
            'audit_json','audit_write','audit_rotate','audit_close'},
            'missing or unknown timing category')
    for row in rows:
        require(type(row['started_ns']) is int and type(row['finished_ns']) is int and
                0 < row['started_ns'] <= row['finished_ns'], 'invalid timing span')
    audits = [row for row in rows if row['kind'] == 'audit']
    stamps = [event for event in events if event['event'] == 'frame_queued']
    frames = {(row['match'], row['frame']): row for row in audits if row['event'] == 'frame_queued'}
    require(len(frames) == sum(row['event'] == 'frame_queued' for row in audits) == len(stamps),
            'frame timing coverage differs')
    require(len({(event['match'], event['frame']) for event in stamps}) == len(stamps),
            'duplicate original frame stamp')
    for event in stamps:
        row = frames.get((event['match'], event['frame']))
        require(row is not None and row['started_ns'] <= event['perf_counter_ns'] <= row['finished_ns'],
                'original frame timestamp lies outside observed audit call')
    previous = {}
    gaps = []
    for event in sorted(stamps, key=lambda value: value['perf_counter_ns']):
        prior = previous.get(event['match'])
        previous[event['match']] = event
        if prior is None:
            require(event['frame'] == 0, 'missing first frame')
            continue
        require(event['frame'] == prior['frame'] + 1, 'noncontiguous frame observations')
        start, end = prior['perf_counter_ns'], event['perf_counter_ns']
        gap = (end - start) / 1_000_000
        if gap < 200:
            continue
        overlaps = []
        for row in rows:
            overlap = max(0, min(end, row['finished_ns']) - max(start, row['started_ns']))
            if overlap:
                overlaps.append(dict(kind=row['kind'], overlap_ms=overlap / 1_000_000,
                                     duration_ms=(row['finished_ns']-row['started_ns']) / 1_000_000,
                                     event=row.get('event'), match=row.get('match'), frame=row.get('frame')))
        overlaps.sort(key=lambda value: value['overlap_ms'], reverse=True)
        gaps.append(dict(match=event['match'], frame=event['frame'], gap_ms=gap,
                         frame_work_ms=event['frame_work_ms'], worker_ms=event['worker_ms'],
                         snapshot_ms=event['snapshot_ms'], interval_ms=event['interval_ms'],
                         outside_current_interval_and_work_ms=gap-event['interval_ms']-event['frame_work_ms'],
                         overlaps=overlaps[:12]))
    gaps.sort(key=lambda value: value['gap_ms'], reverse=True)
    maxima = {kind:max((row['finished_ns']-row['started_ns'])/1_000_000
                      for row in rows if row['kind'] == kind) for kind in counts}
    return dict(passed=True, scope='Measured overlapping timing windows; not sole-cause or performance acceptance',
                counts=dict(counts), frame_audits=len(frames), maxima_ms=maxima,
                record_total_ms=raw['record_total_ns']/1_000_000, record_max_ms=raw['record_max_ns']/1_000_000,
                gaps_over_200ms=len(gaps), largest_gaps=gaps[:20])
