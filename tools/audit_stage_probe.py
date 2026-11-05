"""External observer of the original HostAudit; no substitute record encoding."""
import gc
import threading
import time


class GCWindows:
    """Observe automatic collection only; do not request or change collection."""
    def __init__(self, clock=time.perf_counter_ns, capacity=8192):
        self.clock,self.capacity=clock,capacity
        self.rows=[];self.errors=[];self.dropped=0;self.active=None
        self.before=dict(enabled=gc.isenabled(),threshold=list(gc.get_threshold()))
        self.callbacks=list(gc.callbacks)
        self.callback=self.observe
        gc.callbacks.append(self.callback)

    def observe(self, phase, info):
        now=self.clock()
        if phase=='start':
            if self.active is not None:self.errors.append('overlapping GC starts')
            self.active=(now,info['generation'],threading.get_ident())
        elif phase=='stop':
            active=self.active;self.active=None
            if active is None or active[1]!=info['generation']:
                self.errors.append('unmatched GC stop');return
            if len(self.rows)<self.capacity:
                self.rows.append(dict(started_ns=active[0],finished_ns=now,generation=active[1],
                    thread_id=active[2],collected=info['collected'],uncollectable=info['uncollectable']))
            else:self.dropped+=1
        else:self.errors.append('unknown GC phase')

    def detach(self):
        gc.callbacks.remove(self.callback)
        after=dict(enabled=gc.isenabled(),threshold=list(gc.get_threshold()))
        return dict(schema=1,capacity=self.capacity,dropped=self.dropped,errors=list(self.errors),
                    active=self.active,before=self.before,after=after,
                    callbacks_preserved=gc.callbacks==self.callbacks,rows=list(self.rows))


class AuditStages:
    class JsonProxy:
        def __init__(self, owner, original):
            self.owner, self.original = owner, original

        def dumps(self, *args, **kwargs):
            return self.owner.measure('audit_json', lambda:self.original.dumps(*args, **kwargs))

        def __getattr__(self, name):
            return getattr(self.original, name)

    class StreamProxy:
        def __init__(self, owner, original):
            self.owner, self.original = owner, original

        def write(self, value):
            return self.owner.measure('audit_write', lambda:self.original.write(value))

        def close(self):
            return self.owner.measure('audit_close', self.original.close)

        def __getattr__(self, name):
            return getattr(self.original, name)

    def __init__(self, audit, module, timing):
        if getattr(type(audit), 'ASYNCHRONOUS', False):
            raise ValueError('audit stage observer requires a synchronous writer')
        if isinstance(module.json, self.JsonProxy):
            raise RuntimeError('audit observer already installed')
        self.audit, self.module, self.timing = audit, module, timing
        self.original_json, self.original_rotate = module.json, audit._rotate
        self.had_rotate = '_rotate' in audit.__dict__
        self.saved_rotate = audit.__dict__.get('_rotate')
        self.current = None
        self.sequence = 0
        self.proxy = self.JsonProxy(self, module.json)
        module.json = self.proxy
        self.wrap_stream()
        def rotate():
            try:
                return self.measure('audit_rotate', self.original_rotate)
            finally:
                self.wrap_stream()
        self.rotate = rotate
        audit._rotate = rotate

    def wrap_stream(self):
        if self.audit.stream is not None and not isinstance(self.audit.stream, self.StreamProxy):
            self.audit.stream = self.StreamProxy(self, self.audit.stream)

    def measure(self, kind, operation):
        return self.timing.call(kind, operation, metadata=self.current or {})

    def call(self, event, **fields):
        if self.current is not None:
            raise RuntimeError('reentrant audit observation')
        self.sequence += 1
        self.current = dict(audit_id=self.sequence, event=event,
                            **{key:fields[key] for key in ('match','frame') if key in fields})
        try:
            return self.measure('audit', lambda:self.audit(event, **fields))
        finally:
            self.current = None

    def detach(self):
        if self.current is not None or self.module.json is not self.proxy or self.audit._rotate is not self.rotate:
            raise RuntimeError('audit observer ownership changed')
        self.module.json = self.original_json
        if self.had_rotate:
            self.audit._rotate = self.saved_rotate
        else:
            del self.audit._rotate
        if isinstance(self.audit.stream, self.StreamProxy):
            if self.audit.stream.owner is not self:
                raise RuntimeError('audit stream ownership changed')
            self.audit.stream = self.audit.stream.original


def review_stages(raw):
    def require(condition, message):
        if not condition:
            raise ValueError(message)
    require(raw['schema']==1 and raw['dropped']==0, 'incomplete audit-stage observations')
    rows=raw['rows']
    allowed={'audit','audit_json','audit_write','audit_rotate','audit_close'}
    require(rows and len(rows)<=raw['capacity'] and all(row['kind'] in allowed for row in rows),
            'invalid audit-stage observations')
    parents={row['audit_id']:row for row in rows if row['kind']=='audit'}
    require(len(parents)==sum(row['kind']=='audit' for row in rows) and
            sorted(parents)==list(range(1,len(parents)+1)), 'audit parent sequence differs')
    children={key:[] for key in parents}
    for row in rows:
        require(type(row['started_ns']) is int and type(row['finished_ns']) is int and
                0<row['started_ns']<=row['finished_ns'], 'invalid audit-stage timing span')
        if row['kind']=='audit':continue
        key=row.get('audit_id')
        if key is None:
            require(row['kind']=='audit_close','unparented audit operation')
            continue
        require(key in parents,'missing audit parent')
        parent=parents[key]
        require(parent['started_ns']<=row['started_ns']<=row['finished_ns']<=parent['finished_ns'],
                'audit child lies outside parent')
        require(all(row.get(k)==parent.get(k) for k in ('event','match','frame')),'audit stage identity changed')
        children[key].append(row)
    # Every successful non-filtered call has one original stream write. Empty
    # groups are permitted for the original diagnostics-off filtering path.
    for group in children.values():
        if group:
            require(sum(row['kind']=='audit_write' for row in group)==1 and
                    sum(row['kind']=='audit_json' for row in group) in (1,2), 'audit stage coverage differs')
    summaries={}
    for kind in sorted({row['kind'] for row in rows}):
        selected=[row for row in rows if row['kind']==kind]
        durations=[(row['finished_ns']-row['started_ns'])/1e6 for row in selected]
        summaries[kind]=dict(count=len(selected),maximum_ms=max(durations),total_ms=sum(durations))
    largest=[]
    for parent in sorted(parents.values(),key=lambda row:row['finished_ns']-row['started_ns'],reverse=True)[:20]:
        largest.append(dict(audit_id=parent['audit_id'],event=parent['event'],frame=parent.get('frame'),
                            total_ms=(parent['finished_ns']-parent['started_ns'])/1e6,
                            children=[dict(kind=row['kind'],duration_ms=(row['finished_ns']-row['started_ns'])/1e6)
                                      for row in children[parent['audit_id']]]))
    return dict(passed=True,scope='Original audit subcall elapsed windows; encoding outside json.dumps is residual; overlapping nested stages are not additive',
                calls=len(parents),stages=summaries,largest_calls=largest)
