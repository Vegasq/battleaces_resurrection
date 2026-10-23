"""Fixed exception classifications; never persist exception arguments or paths."""
from .worker_client import WorkerError,WorkerTimeout
from .protocol import ProtocolError
from .game_data import GameDataError,InputError
from .protobuf_wire import WireError
from .cosmetics import CosmeticError


def validation_reason(error,fallback):
    # These exact authored types contain bounded validation messages. Generic
    # ValueError/KeyError can originate in storage or third-party code instead.
    if type(error) in (ProtocolError,GameDataError,InputError,WireError,CosmeticError):
        return str(error)[:1024]
    return fallback


def failure_fields(error):
    # Labels are authored constants, not a dynamic class name or str/repr(error).
    # Empty-argument class labels preserve existing worker-log consumers.
    categories=((WorkerTimeout,'worker_timeout','WorkerTimeout'),
                (WorkerError,'worker_error','WorkerError'),
                (PermissionError,'permission','PermissionError'),
                (FileNotFoundError,'missing_file','FileNotFoundError'),
                (TimeoutError,'timeout','TimeoutError'),
                (OSError,'os_error','OSError'),
                (ValueError,'invalid_data','ValueError'),
                (KeyError,'missing_field','KeyError'))
    kind,label=next(((kind,label) for cls,kind,label in categories if isinstance(error,cls)),('internal','Exception'))
    fields=dict(error_kind=kind,error=label+'()')
    if isinstance(error,OSError):
        for name in ('errno','winerror'):
            value=getattr(error,name,None)
            if type(value) is int and -(2**31)<=value<=2**32-1:fields[name]=value
    return fields
