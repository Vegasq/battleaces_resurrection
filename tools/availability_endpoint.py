"""Owned numeric-loopback endpoints for refusal, TLS stall and pending TCP checks."""
from __future__ import annotations
import copy
import os
import select
import socket
import threading

NETWORK_STATES = ('rc-refused', 'rc-handshake-timeout',
                  'verified-refused', 'verified-handshake-timeout',
                  'rc-connect-timeout', 'verified-connect-timeout')

# Windows SDK ws2def.h. Set before listen, on this exclusive loopback socket
# only. No accept call is made: TCP stays pending on supported Windows stacks.
# Actual sock_connect observation is required; option readback alone is no proof.
SO_CONDITIONAL_ACCEPT = 0x3002


class AvailabilityEndpoint:
    def __init__(self, state):
        if state not in NETWORK_STATES: raise ValueError('Unsupported owned endpoint')
        if state.endswith('-connect-timeout') and os.name != 'nt':
            raise ValueError('Conditional acceptance requires Windows')
        self.state = state
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        if hasattr(socket, 'SO_EXCLUSIVEADDRUSE'):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        self.socket.bind(('127.0.0.1', 0))
        self.port = self.socket.getsockname()[1]
        self.stop = threading.Event()
        self.lock = threading.Lock()
        self.rows, self.errors = [], []
        self.owner_closed_peers = 0
        self.closed = False
        self.thread = None
        self.conditional_accept = False
        if state.endswith('-connect-timeout'):
            try:
                self.socket.setsockopt(socket.SOL_SOCKET, SO_CONDITIONAL_ACCEPT, 1)
                self.conditional_accept = self.socket.getsockopt(socket.SOL_SOCKET, SO_CONDITIONAL_ACCEPT) == 1
                if not self.conditional_accept: raise RuntimeError('Conditional acceptance unavailable')
                self.socket.listen(1)
            except BaseException:
                self.socket.close()
                raise
        if state.endswith('handshake-timeout'):
            self.socket.listen(4)
            self.socket.setblocking(False)
            self.thread = threading.Thread(target=self._serve, daemon=True, name='owned-TLS-stall')
            self.thread.start()
        # Refusal intentionally reserves the exclusive bound port WITHOUT listen.

    def _serve(self):
        peers = {}
        try:
            while not self.stop.is_set():
                readable, _, _ = select.select([self.socket, *peers], [], [], .05)
                for connection in readable:
                    if connection is self.socket:
                        peer, address = self.socket.accept()
                        peer.setblocking(False)
                        with self.lock:
                            if address[0] != '127.0.0.1' or len(self.rows) >= 4:
                                peer.close(); raise RuntimeError('Unexpected owned endpoint peer/count')
                            row = dict(bytes=0, client_hello=False, closed_by_client=False)
                            self.rows.append(row)
                        peers[peer] = (row, bytearray())
                    else:
                        row, prefix = peers[connection]
                        try: data = connection.recv(65536)
                        except ConnectionResetError: data = b''
                        with self.lock:
                            if not data:
                                row['closed_by_client'] = True
                                connection.close(); del peers[connection]
                            else:
                                row['bytes'] += len(data)
                                prefix.extend(data[:max(0, 6-len(prefix))])
                                if row['bytes'] > 65536: raise RuntimeError('Unbounded handshake input')
                                if len(prefix) == 6:
                                    if prefix[:2] != b'\x16\x03' or prefix[5] != 1:
                                        raise RuntimeError('Expected TLS ClientHello,not application data')
                                    row['client_hello'] = True
                        # Never send ServerHello, close early, or supply an error.
        except BaseException as error:
            with self.lock: self.errors.append(type(error).__name__+': '+str(error))
        finally:
            with self.lock:
                self.owner_closed_peers += len(peers)
                for peer in peers: peer.close()

    def snapshot(self):
        with self.lock:
            return dict(state=self.state, host='127.0.0.1', port=self.port,
                        listening=not self.state.endswith('-refused'), conditional_accept=self.conditional_accept,
                        peers=copy.deepcopy(self.rows),
                        live_peers=sum(not row['closed_by_client'] for row in self.rows),
                        errors=list(self.errors), owner_closed_peers=self.owner_closed_peers,
                        thread_alive=self.thread is not None and self.thread.is_alive(), closed=self.closed)

    def close(self):
        if not self.closed:
            self.stop.set()
            if self.thread:
                self.thread.join(2)
                if self.thread.is_alive(): raise RuntimeError('Owned endpoint did not stop')
            self.socket.close()
            self.closed = True
        return self.snapshot()
