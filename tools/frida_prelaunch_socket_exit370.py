"""Combine selected socket-handle counts with the owned exit-boundary observer."""
from __future__ import annotations

from tools.frida_attribution_clock import replace_once
from tools.frida_prelaunch_exit367 import EXIT_ADAPTER
from tools.frida_socket_handles import build_source as socket_source


def build_source(config: dict) -> str:
    exit_adapter = replace_once(
        EXIT_ADAPTER,
        'unknownRelativeRoots,overflow,transportHoldMs:200',
        'unknownRelativeRoots,overflow,socketHandles:{send:{...socketHandles.send},recv:{...socketHandles.recv}},transportHoldMs:200')
    return socket_source(config) + exit_adapter
