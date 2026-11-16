"""Bounded public build/endpoint metadata; never carries credentials or paths."""
import ipaddress
import re
import struct

from server.tls_transport import normalize_server_name


def build_label(inventory):
    if inventory is None:
        return 'Development (build unknown)'
    try:
        version, source = inventory['versions']['package'], inventory['source']
        revision, dirty = source['revision'], source['dirty']
    except (KeyError, TypeError):
        raise ValueError('Invalid installed client build metadata') from None
    if (not isinstance(version, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9.+-]{0,63}', version)
            or not isinstance(revision, str) or not re.fullmatch(r'[0-9a-f]{40}', revision)
            or type(dirty) is not bool):
        raise ValueError('Invalid installed client build metadata')
    return version + ' (build ' + revision[:7] + (', modified' if dirty else '') + ')'


def target_bytes(host='', port=0, peer=''):
    if not host:
        if port or peer: raise ValueError('Invalid empty client endpoint')
        return b'\x01\0\0\0\0'
    host = normalize_server_name(host)
    if type(port) is not int or not 1 <= port <= 65535:
        raise ValueError('Invalid client endpoint port')
    if peer: peer = ipaddress.ip_address(peer).compressed
    host, peer = host.encode('ascii'), peer.encode('ascii')
    return bytes((1, len(host))) + host + struct.pack('<H', port) + bytes((len(peer),)) + peer


def read_target(payload):
    if not isinstance(payload, bytes) or not 5 <= len(payload) <= 303 or payload[0] != 1:
        raise ValueError('Invalid client endpoint metadata')
    count = payload[1]
    if len(payload) < count + 5: raise ValueError('Truncated client endpoint metadata')
    host = payload[2:2+count].decode('ascii')
    port, = struct.unpack_from('<H', payload, 2+count)
    size = payload[4+count]
    if len(payload) != 5+count+size: raise ValueError('Invalid client endpoint length')
    peer = payload[5+count:].decode('ascii')
    if target_bytes(host, port, peer) != payload: raise ValueError('Noncanonical client endpoint')
    return host, port, peer


def endpoint_label(host, port, peer=''):
    if not host: return ''
    label = ('[' + host + ']' if ':' in host else host) + ':' + str(port)
    return label + (' (' + peer + ')' if peer and peer != host else '')


def configured_label(value):
    """A malformed optional online setting must not prevent local startup."""
    try:
        return endpoint_label(*read_target(target_bytes(value.get('server_host', ''), value.get('server_port', 47623))))
    except (ValueError, TypeError, AttributeError):
        return ''
