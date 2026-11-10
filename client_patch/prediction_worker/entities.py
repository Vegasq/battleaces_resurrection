"""Bounded original-view identity history for confirmed command admission.

The caller records original views,invalidates speculative views BEFORE restore,
and promotes only the reconciler's confirmed frontier. Never derive admission
from the current predicted head alone. Known dead identities remain recorded,
matching the server's delayed-order contract. Match/world lifetime owns this
object;it must never be reused across a rematch.

ActiveIdentityHistory is a separate selection contract. Its uint64 observation
epochs never turn the retained known-dead scalar map into an active admission
list, nor establish permanent identity of the native uint32 allocator.
"""
from __future__ import annotations

import struct
import copy

from server.native_simulation import _Buffer


class IdentityError(ValueError):pass


def identities(raw, *, expected_frame, max_entities, allow_bootstrap=False):
    if type(raw) is not bytes or not 8 <= len(raw) <= 16*1024*1024:
        raise IdentityError('identity snapshot byte limit')
    b = _Buffer(raw)
    root = b.read('I',0);b.bounds(root,4)
    frame = b.scalar(root,0,'I')
    bootstrap = allow_bootstrap and expected_frame == -1 and frame == 0xffffffff
    if not bootstrap and (frame != expected_frame or not 0 <= frame <= 0x7fffffff):
        raise IdentityError('identity snapshot frame mismatch')
    components = []
    for field in (2,3):  # Same Army/Type intersection used by server history.
        table = b.table(root,field)
        ids,count = b.vector(table,0,4)
        values,length = b.vector(table,1,4)
        if count != length or count > max_entities:
            raise IdentityError('identity component count/size mismatch')
        rows = {}
        for index in range(count):
            entity,value = b.read('I',ids+index*4),b.read('I',values+index*4)
            if entity in rows:raise IdentityError('duplicate identity component ID')
            rows[entity] = value
        components.append(rows)
    army,kind = components
    return {entity:(army[entity],kind[entity]) for entity in army.keys() & kind.keys()}


def active_identities(raw, *, expected_frame, max_entities, allow_bootstrap=False):
    result=identities(raw,expected_frame=expected_frame,max_entities=max_entities,allow_bootstrap=allow_bootstrap)
    b=_Buffer(raw);table=b.table(b.read('I',0),4)
    ids,count=b.vector(table,0,4);values,length=b.vector(table,1,4)
    if count!=length or count>max_entities:
        raise IdentityError('active entity-state component count/size mismatch')
    seen=set()
    for index in range(count):
        entity,state=b.read('I',ids+index*4),b.read('I',values+index*4)
        if entity in seen:raise IdentityError('duplicate active entity-state ID')
        seen.add(entity)
        if state==6:result.pop(entity,None)  # Exact shipped EntityState.DEAD.
    return result


class IdentityHistory:
    def __init__(self, *, max_views=16, max_entities=65536, max_known=262144,
                 max_bytes=32*1024*1024):
        if (type(max_views) is not int or not 1 <= max_views <= 32 or
            type(max_entities) is not int or not 1 <= max_entities <= 65536 or
            type(max_known) is not int or not max_entities <= max_known <= 262144 or
            type(max_bytes) is not int or not 12 <= max_bytes <= 64*1024*1024):
            raise IdentityError('invalid identity history budget')
        self.max_views,self.max_entities,self.max_known,self.max_bytes = max_views,max_entities,max_known,max_bytes
        self.views,self.known = {},{}
        self.confirmed_frame = self.promoted_frame = -1

    def _budget(self, views, known):
        if len(views) > self.max_views or len(known) > self.max_known or (
                sum(len(view) for view in views.values()) + len(known))*12 > self.max_bytes:
            raise IdentityError('identity history budget reached')

    def observe(self, raw, *, physical_frame):
        view = identities(raw,expected_frame=physical_frame,max_entities=self.max_entities)
        if physical_frame < self.promoted_frame:
            raise IdentityError('view predates retained confirmed identity')
        if physical_frame == self.promoted_frame and self.views.get(physical_frame) != view:
            raise IdentityError('confirmed entity identity map changed')
        proposed = dict(self.views)
        proposed[physical_frame] = view
        # The promoted base is retained in known;older maps need no cache slot.
        proposed = {frame:rows for frame,rows in proposed.items() if frame >= self.promoted_frame}
        self._budget(proposed,self.known)
        self.views = proposed

    def invalidate_after(self, frame):
        if type(frame) is not int or frame < self.promoted_frame:
            raise IdentityError('cannot invalidate confirmed entity identities')
        self.views = {number:rows for number,rows in self.views.items() if number <= frame}

    def confirm(self, frontier):
        if type(frontier) is not int or not self.confirmed_frame <= frontier <= 0x7fffffff:
            raise IdentityError('confirmed identity frontier is not monotonic')
        choices = [frame for frame in self.views if self.promoted_frame < frame <= frontier]
        if choices:
            chosen = max(choices)
            known = dict(self.known)
            for frame in sorted(choices):known.update(self.views[frame])
            views = {frame:rows for frame,rows in self.views.items() if frame >= chosen}
            self._budget(views,known)
            self.known,self.views,self.promoted_frame = known,views,chosen
        self.confirmed_frame = frontier

    def lookup(self, entity):
        if type(entity) is not int or not 0 <= entity <= 0xffffffff:
            raise IdentityError('entity ID is not uint32')
        return self.known.get(entity)

    def packet(self):
        result = bytearray(struct.pack('<iI',self.promoted_frame,len(self.known)))
        for entity,(army,kind) in sorted(self.known.items()):
            result.extend(struct.pack('<III',entity,army,kind))
        return bytes(result)


class ActiveIdentityHistory:
    """World-local confirmed observation epochs for selection admission.

    Separate from the known-dead scalar command history. Only promoted actual
    views allocate nonzero tokens. Equal identities in consecutive observed
    confirmed frames keep tokens; observed absence/type/army changes or a gap
    renew them. Unobserved intra-tick ABA is NOT detected. No claim is made that
    native uint32 IDs are permanent allocation identities. A consumer must bind
    the opaque world ID as well as the token, and use the promoted frame header.
    """
    def __init__(self, *, max_views=16,max_entities=65536,max_bytes=32*1024*1024):
        if (type(max_views) is not int or not 1<=max_views<=32 or
                type(max_entities) is not int or not 1<=max_entities<=65536 or
                type(max_bytes) is not int or not 20<=max_bytes<=64*1024*1024):
            raise IdentityError('invalid active identity history budget')
        self.max_views,self.max_entities,self.max_bytes=max_views,max_entities,max_bytes
        self.views,self.active={},{}
        self.promoted_frame=self.confirmed_frame=-1
        self._promoted=False;self._next_token=1

    def _budget(self,views,active):
        if (len(views)>self.max_views or len(active)>self.max_entities or
                sum(len(view) for view in views.values())*12+len(active)*20>self.max_bytes):
            raise IdentityError('active identity history budget reached')

    def _observe(self,frame,view):
        if frame<self.promoted_frame:
            raise IdentityError('active view predates promoted observation')
        if self._promoted and frame==self.promoted_frame and self.views.get(frame)!=view:
            raise IdentityError('confirmed active entity map changed')
        proposed={number:rows for number,rows in self.views.items() if number>=self.promoted_frame}
        proposed[frame]=view
        self._budget(proposed,self.active)
        self.views=proposed

    def observe(self,raw,*,physical_frame):
        if type(physical_frame) is not int or not 0<=physical_frame<=0x7fffffff:
            raise IdentityError('active physical frame outside canonical range')
        view=active_identities(raw,expected_frame=physical_frame,max_entities=self.max_entities)
        self._observe(physical_frame,view)

    def bootstrap(self,raw):
        if self.confirmed_frame!=-1 or any(frame>=0 for frame in self.views):
            raise IdentityError('bootstrap must precede native/canonical frame0')
        view=active_identities(raw,expected_frame=-1,max_entities=self.max_entities,allow_bootstrap=True)
        staged=copy.copy(self)
        staged._observe(-1,view);staged.confirm(-1)
        self.views,self.active=staged.views,staged.active
        self.promoted_frame,self.confirmed_frame=staged.promoted_frame,staged.confirmed_frame
        self._promoted,self._next_token=staged._promoted,staged._next_token

    def invalidate_after(self,frame):
        if type(frame) is not int or frame<self.promoted_frame:
            raise IdentityError('cannot invalidate confirmed active identities')
        self.views={number:rows for number,rows in self.views.items() if number<=frame}

    def confirm(self,frontier,*,continuity_proof=None):
        if type(frontier) is not int or not self.confirmed_frame<=frontier<=0x7fffffff:
            raise IdentityError('active confirmation frontier is not monotonic')
        # Reserved for a qualified interval observer, not a global trust flag.
        # The caller's callback must inspect metadata only and prove this exact
        # inclusive transition. NativeSession supplies its guarded original
        # master-creation interval observer when that optional ABI is present.
        if continuity_proof is not None and not callable(continuity_proof):
            raise IdentityError('active continuity proof must be an interval callback')
        choices=sorted(frame for frame in self.views if frame<=frontier and
                       (not self._promoted or frame>self.promoted_frame))
        active,promoted,next_token=self.active,self.promoted_frame,self._next_token
        had_view=self._promoted
        for frame in choices:
            gap=had_view and frame!=promoted+1
            if gap and continuity_proof is not None:
                proven=continuity_proof(promoted,frame)
                if type(proven) is not bool:
                    raise IdentityError('active continuity proof must return a strict bool')
                gap=not proven
            proposed={}
            for entity,identity in sorted(self.views[frame].items()):
                old=active.get(entity)
                if not gap and old is not None and old[:2]==identity:
                    proposed[entity]=old
                else:
                    if next_token>0xffffffffffffffff:
                        raise IdentityError('active identity observation token space exhausted')
                    proposed[entity]=(*identity,next_token);next_token+=1
            active,promoted,had_view=proposed,frame,True
        views={frame:rows for frame,rows in self.views.items() if frame>=promoted}
        self._budget(views,active)
        self.active,self.views=active,views
        self.promoted_frame,self._promoted,self._next_token=promoted,had_view,next_token
        self.confirmed_frame=frontier

    def active_packet(self):
        result=bytearray(struct.pack('<iI',self.promoted_frame,len(self.active)))
        for entity,(army,kind,token) in sorted(self.active.items()):
            result.extend(struct.pack('<IIIQ',entity,army,kind,token))
        return bytes(result)
