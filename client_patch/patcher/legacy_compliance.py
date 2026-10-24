"""Disable the discontinued Korean account flow in the community client.

Build37822 source/serialized route: docs/legacy-compliance171.txt.
This is separate from analytics recipe23 and the replacement LAN transport.
Original game recovery restores these bytes with the rest of GameAssembly.
"""

PATCHES = [
    # Instance void; return before object access or native prologue. Prevents
    # creating the entire Korean prefab, including its active WebView demo.
    {'name': 'Disable original Korean compliance dialog creation',
     'rva': 0x3d508d0, 'offset': 0x3d4eed0,
     'before': '48895c241056', 'after': 'c39090909090'},
    # Instance void; no request construction, enqueue or original service call.
    {'name': 'Disable original Korean login validation request',
     'rva': 0x3e3af60, 'offset': 0x3e39560,
     'before': '48895c2408488974241057', 'after': 'c390909090909090909090'},
    # A retained response must not wait on a compliance dialog we disabled.
    # Clear the old pending flag and preserve fallthrough/stack/register state.
    {'name': 'Clear obsolete compliance wait in original login finalizer',
     'rva': 0x3e3f11a, 'offset': 0x3e3d71a,
     'before': '80bf08010000000f85d0040000',
     'after':  'c6870801000000909090909090'},
    # Use the ORIGINAL null-JudgeLoginData branch target, before event dispatch
    # and pending-flag assignment. E9 displacement is relative to five bytes.
    {'name': 'Skip original Korean compliance gate before prompt dispatch',
     'rva': 0x3e3f1f2, 'offset': 0x3e3d7f2,
     'before': '0f84a0000000', 'after': 'e9a100000090'},
]


def descriptor(*, restored=False):
    return {'version': 1,
            'korean_login_compliance': 'original-restored' if restored else 'disabled',
            'dialog_creation_blocked': not restored,
            'validation_request_blocked': not restored,
            'original_pending_gate_skipped': not restored,
            'community_transport_changed': False}
