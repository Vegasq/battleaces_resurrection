"""Bounded original-view identity history for confirmed command admission.

The caller records original views,invalidates speculative views BEFORE restore,
and promotes only the reconciler's confirmed frontier. Never derive admission
from the current predicted head alone. Known dead identities remain recorded,
matching the server's delayed-order contract. Match/world lifetime owns this
object;it must never be reused across a rematch.
"""
from __future__ import annotations

import struct

from server.native_simulation import _Buffer


class IdentityError(ValueError):pass


def identities(raw, *, expected_frame, max_entities):
    if type(raw) is not bytes or not 8 <= len(raw) <= 16*1024*1024:
        raise IdentityError('identity snapshot byte limit')
    b = _Buffer(raw)
    root = b.read('I',0);b.bounds(root,4)
    frame = b.scalar(root,0,'I')
    if frame != expected_frame or not 0 <= frame <= 0x7fffffff:
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
