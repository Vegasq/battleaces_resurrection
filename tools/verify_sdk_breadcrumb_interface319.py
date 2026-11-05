"""Inventory every metadata-declared IBreadcrumbs implementation in build37822."""
from __future__ import annotations

import hashlib
import struct

from tools.extract_descriptors import Metadata
from tools.review_reporter_delegate_targets300 import METADATA, MD_SHA
from tools.verify_sdk_breadcrumb_collectors318 import verify as verify_guards


def verify():
    raw = METADATA.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == MD_SHA
    md = Metadata(raw)
    matches = [(index, record) for index, record in enumerate(md.types)
               if (md.string(record[1]), md.string(record[0])) ==
               ('BugsnagUnity', 'IBreadcrumbs')]
    assert len(matches) == 1
    interface_index, interface = matches[0]
    assert interface_index == 19973 and interface[2] == 45089
    assert [(md.string(method[0]), method[-1])
            for method in md.methods_for_type(interface)] == [
                ('Leave', 3), ('Leave', 1), ('Retrieve', 0)]

    start, size = md.header[34:36]
    assert size % 4 == 0 and start + size <= len(raw)
    declared_entries = size // 4
    used = set()
    implementers = []
    for index, record in enumerate(md.types):
        first, count = record[13], record[22]
        if not count:
            continue
        assert 0 <= first <= declared_entries - count
        slots = set(range(first, first + count))
        assert used.isdisjoint(slots)
        used.update(slots)
        interfaces = struct.unpack_from('<' + str(count) + 'i', raw, start + first * 4)
        if interface[2] in interfaces:
            implementers.append((index, record))
    assert len(used) == declared_entries == 12973
    assert len(implementers) == 1
    concrete_index, concrete = implementers[0]
    assert concrete_index == 20022
    assert (md.string(concrete[1]), md.string(concrete[0]), concrete[2]) == (
        'BugsnagUnity', 'Breadcrumbs', 38616)
    assert [(md.string(method[0]), method[-1])
            for method in md.methods_for_type(concrete) if md.string(method[0]) in ('Leave', 'Retrieve')] == [
                ('Leave', 3), ('Leave', 1), ('Retrieve', 0)]
    # A metadata-declared derived class could inherit this interface without
    # listing it again. No type has Breadcrumbs as its direct parent.
    subclasses = [index for index, record in enumerate(md.types)
                  if record[4] == concrete[2]]
    assert not subclasses
    guard_result = verify_guards()
    assert guard_result['passed'] and guard_result['recipe'] >= 30
    return dict(passed=True, metadata_sha256=MD_SHA,
                type_definitions=len(md.types), interface_slots=declared_entries,
                interface_type_index=interface[2], implementers=[concrete_index],
                direct_subclasses=subclasses, guarded_leave_overloads=2)


if __name__ == '__main__':
    print('PASS', verify())
