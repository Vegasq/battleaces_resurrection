"""Single-world original-native adapter for quiescent prediction boundaries."""
from __future__ import annotations

import ctypes as C

from .native import HostError


class CheckpointAdapter:
    def __init__(self, session, world_key):
        self.session, self.world = session, session._world(world_key)
        self.world_key = world_key
        if session.arena is None:
            raise HostError('native prediction needs an owned checkpoint arena')
        self.arena, self.tokens = session.arena, {}
        self.root_bindings()  # Refuse older transport-only helpers immediately.

    def root_bindings(self):
        self.session.healthy()
        return self.arena.root_bindings()

    def capture(self, frame):
        binding = self.root_bindings()
        token = self.arena.capture()
        if token in self.tokens:
            raise HostError('native helper reused a retained checkpoint token')
        self.tokens[token] = (binding, frame)
        try:
            if self.root_bindings() != binding:
                raise HostError('native roots changed across checkpoint capture')
        except BaseException as error:
            try:
                self.drop(token)
            except Exception as cleanup:
                raise HostError(str(error) + '; checkpoint cleanup: ' + str(cleanup)) from error
            raise
        return token

    def restore(self, token):
        if token not in self.tokens:
            raise HostError('unknown native checkpoint token')
        # All validation precedes mutation of arena,.data or static TLS. The
        # OS FLS slots lie outside those snapshots and must retain their roots.
        binding, frame = self.tokens[token]
        if self.root_bindings() != binding:
            raise HostError('native root binding differs from saved checkpoint')
        history = getattr(self.session, 'identity_histories', {}).get(self.world_key)
        if history is not None:
            history.invalidate_after(frame)
        active = getattr(self.session, 'active_identity_histories', {}).get(self.world_key)
        if active is not None:
            active.invalidate_after(frame)
        observer=getattr(self.session,'entity_guards',{}).get(self.world_key)
        if observer is not None:observer.invalidate_after(frame)
        diagnostic = getattr(self.session, 'movement_observer', None)
        if diagnostic is not None:
            diagnostic.invalidate_after(self.world_key, frame)
        self.arena.restore(token)
        if self.root_bindings() != binding:
            raise HostError('native roots changed during checkpoint restore')

    def drop(self, token):
        if token not in self.tokens:
            raise HostError('unknown native checkpoint release token')
        self.arena.drop(token)
        del self.tokens[token]

    def process_frame(self, raw, dt):
        if type(raw) is not bytes or not raw or dt != 50:
            raise HostError('native replay requires one50ms InputActions frame')
        message = C.create_string_buffer(raw)
        observer=getattr(self.session,'entity_guards',{}).get(self.world_key)
        if observer is not None:observer.begin(raw)
        if self.session._call('SimProcessMsg', self.world, message, len(raw)):
            raise HostError('original native replay ProcessMsg failed')
        current = C.c_int32(-1)
        if self.session._call('SimStep', self.world, 50, C.byref(current)):
            raise HostError('original native replay Step failed')
        if observer is not None:observer.finish()
        callback = getattr(self.session, '_after_prediction_replay', None)
        if callback is not None:
            callback(self.world_key, raw)

    def close(self):
        errors = []
        for token in list(self.tokens):
            try:
                self.drop(token)
            except Exception as error:
                errors.append(str(error))
        if errors:
            raise HostError('native snapshot cleanup failed: ' + '; '.join(errors))
