"""Reject incomplete/corrupted observation evidence instead of false absence."""
import copy
import unittest
from tools.review_crash_policy170 import aggregate, stream, symbol_calls


class StreamTests(unittest.TestCase):
    def fixture(self):
        return dict(pid=19, state='detached', messages_truncated=False, messages=[
            dict(type='send', payload=dict(schema=1, seq=1, pid=19, runId='owned',
                                          kind='observer-ready', data={'errors': []}))])

    def test_complete_identity_bound_stream(self):
        self.assertEqual(len(stream(self.fixture(), 19, 'owned')), 1)

    def test_transport_loss_script_error_foreign_identity_and_gaps_refuse(self):
        original = self.fixture()
        variants = []
        for key, value in [('messages_truncated', True), ('state', 'running'), ('pid', 20)]:
            data = copy.deepcopy(original); data[key] = value; variants.append(data)
        for key, value in [('seq', 2), ('pid', 20), ('runId', 'foreign'), ('schema', 2),
                           ('kind', 'budget-exceeded'), ('kind', 'decode-error')]:
            data = copy.deepcopy(original); data['messages'][0]['payload'][key] = value; variants.append(data)
        data = copy.deepcopy(original); data['messages'][0]['type'] = 'error'; variants.append(data)
        for value in variants:
            with self.subTest(value=value), self.assertRaises(ValueError):
                stream(value, 19, 'owned')

    def test_observer_errors_unknown_roots_and_overflow_refuse(self):
        for key, value in [('errors', ['failure']), ('unknownRelativeRoots', 1), ('overflow', True)]:
            data = self.fixture(); data['messages'][0]['payload']['data'][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                stream(data, 19, 'owned')


class SymbolTests(unittest.TestCase):
    def test_nested_calls_match_on_same_thread(self):
        events = [dict(tid=19, kind=kind, data={'name': name}) for kind, name in
                  [('crash-api-enter', 'SymInitialize'), ('crash-api-enter', 'SymInitializeW'),
                   ('crash-api-leave', 'SymInitializeW'), ('crash-api-leave', 'SymInitialize')]]
        expected = {'SymInitialize': 1, 'SymInitializeW': 1}
        symbol_calls(events, expected)
        for variant in (events[1:] + events[:1], [events[0], events[1], events[3], events[2]],
                        events[:2] + [dict(events[2], tid=20)] + events[3:]):
            with self.subTest(variant=variant), self.assertRaises(ValueError):
                symbol_calls(variant, expected)


class AggregateTests(unittest.TestCase):
    def fixture(self):
        row = dict(tid=19, path='owned.pdb', operation='NtCreateFile', returnValue=-1073741772,
                   frames=None, pending=False, count=3, firstOrdinal=1, lastOrdinal=3, firstMs=10, lastMs=12)
        event = dict(seq=1, kind='policy-files', data=dict(boundary='filter-return', offset=0, rows=[row]))
        final = dict(seq=2, elapsedMs=13, data=dict(boundary='filter-return',
                     fileAggregate=dict(operations=3, rows=1, overflow=False)))
        return [event], final

    def test_exact_repeated_failure_total(self):
        events, final = self.fixture()
        self.assertEqual(aggregate(events, final)[0]['count'], 3)

    def test_lost_duplicated_or_reordered_chunk_refuses(self):
        events, final = self.fixture()
        for variant in ([], events * 2, [dict(events[0], data=dict(events[0]['data'], offset=1))]):
            with self.subTest(variant=variant), self.assertRaises(ValueError):
                aggregate(variant, final)

    def test_totals_overflow_and_boundary_refuse(self):
        for key, value in [('rows', 2), ('operations', 4), ('overflow', True)]:
            events, final = self.fixture(); final['data']['fileAggregate'][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                aggregate(events, final)
        events, final = self.fixture(); final['data']['boundary'] = 'heartbeat'
        with self.assertRaises(ValueError):
            aggregate(events, final)

    def test_pending_io_or_impossible_row_refuses(self):
        for key, value in [('pending', True), ('count', 0), ('firstOrdinal', 2),
                           ('lastOrdinal', 2), ('lastMs', 14), ('frames', [])]:
            events, final = self.fixture(); events[0]['data']['rows'][0][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                aggregate(events, final)


if __name__ == '__main__':
    unittest.main()
