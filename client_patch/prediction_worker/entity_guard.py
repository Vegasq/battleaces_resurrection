"""Prediction-only, owner-thread native entity allocation interval evidence.

These counters are observer metadata outside the rewound original heap. They
are invalidated with the command timeline. A full 12-bit EnTT generation cycle
needs 4095 master creations; a guarded interval strictly below that excludes
numeric-ID ABA within that interval, rather than assuming IDs last forever.
"""
from __future__ import annotations

import ctypes as C


class EntityGuardError(RuntimeError):pass


class Stats(C.Structure):
    _fields_ = [(name,C.c_uint64) for name in (
        'version','error','owner','world','master','epoch','creates','hints',
        'other_creates','other_hints','foreign','depth')]


class EntityGuard:
    def __init__(self, arena, world):
        self.arena,self.world = arena,int(world)
        self.pending,self.counts,self.owner = None,{},None
        self.total_creations=self.maximum_interval_creations=0
        self.creation_samples=[]
        self.api = [getattr(arena.dll,name) for name in (
            'BAEntityGuardInstall','BAEntityGuardBind','BAEntityGuardReset',
            'BAGetEntityGuard','BAEntityGuardUnbind')]
        for function,args in zip(self.api,([], [C.c_uint64], [], [C.POINTER(Stats),C.c_uint32], [C.c_uint64])):
            function.argtypes,function.restype = args,C.c_int32
        if not getattr(arena,'_entity_observer_installed',False):
            self._checked(self.api[0](), 'install')
            arena._entity_observer_installed=True
        self._checked(self.api[1](self.world),'bind')
        self.bound=True
        try:self.snapshot()
        except BaseException:
            self.close()
            raise

    @classmethod
    def optional(cls,arena,world):
        dll=getattr(arena,'dll',None)
        if dll is None or not hasattr(dll,'BAEntityGuardInstall'):return None
        return cls(arena,world)

    @staticmethod
    def _checked(code,where):
        if code:raise EntityGuardError('native entity observer '+where+' failed')

    def snapshot(self):
        value=Stats();self._checked(self.api[3](C.byref(value),C.sizeof(value)),'read')
        if (value.version!=1 or value.error or value.foreign or value.depth or
                value.world!=self.world or value.master!=self.world+0x22a08 or
                value.hints or not value.owner):
            raise EntityGuardError('native entity observer binding/counter failure')
        if self.owner is None:self.owner=int(value.owner)
        if value.owner!=self.owner:raise EntityGuardError('native entity observer owner changed')
        return tuple(int(getattr(value,name)) for name,_ in Stats._fields_)

    def begin(self,raw):
        from .prediction import frame_number
        frame=frame_number(raw)
        if self.pending is not None or frame in self.counts:
            raise EntityGuardError('native entity frame was not retired/invalidation missing')
        before=self.snapshot();self._checked(self.api[2](),'reset');after=self.snapshot()
        if after[5]!=before[5]+1 or any(after[6:10]):
            raise EntityGuardError('native entity observer reset did not start a fresh epoch')
        self.pending=frame

    def finish(self):
        if self.pending is None:raise EntityGuardError('native entity Step has no prepared frame')
        value=self.snapshot();frame=self.pending
        if value[6]>=4095:raise EntityGuardError('native entity generation budget exceeded')
        proposed=dict(self.counts);proposed[frame]=value[6]
        # This is a rolling bound, never a match-lifetime creation cap. Keep
        # 32 ticks for requested view intervals and guard every 14-tick window
        # (12 predicted ticks plus the retained checkpoint boundary/margin).
        proposed={number:count for number,count in proposed.items() if number>=frame-31}
        interval_creates=sum(count for number,count in proposed.items() if number>=frame-13)
        if interval_creates>=4095:
            raise EntityGuardError('native entity speculative interval may wrap its generation')
        self.counts,self.pending=proposed,None
        self.total_creations+=value[6]  # Includes replay; diagnostic, never an admission budget.
        self.maximum_interval_creations=max(self.maximum_interval_creations,interval_creates)
        if value[6] and len(self.creation_samples)<16:self.creation_samples.append((frame,value[6]))

    def invalidate_after(self,frame):
        if self.pending is not None:raise EntityGuardError('cannot rewind an in-flight native entity frame')
        self.counts={number:count for number,count in self.counts.items() if number<=frame}

    def continuity(self,start,end):
        if type(start) is not int or type(end) is not int or not -1<=start<end or end-start>14:
            return False
        interval=range(start+1,end+1)
        return all(number in self.counts for number in interval) and sum(self.counts[number] for number in interval)<4095

    def close(self):
        if self.bound:
            self._checked(self.api[4](self.world),'unbind');self.bound=False
