"""Deterministic grouping safety, not a substitute for labeled recall evaluation."""
import copy
import unittest

from app.services.story_clustering import compatible, cosine, event_key


def card():
    return {'kind': 'report', 'entities': [
        {'mention': 'North Labs', 'resolution': 'resolved', 'resolved_id': 'company:north'}],
        'event_hints': [{'actors': ['North Labs'], 'action': 'released', 'object': 'Product 2',
                         'date': '2026-09-01', 'place_ids': ['country:gb']}]}


class StoryClusteringTests(unittest.TestCase):
    def test_same_specific_development_matches_with_validated_threshold(self):
        self.assertTrue(compatible(card(), [1., 0.], card(), [1., .01], threshold=.99))

    def test_uncalibrated_threshold_cannot_merge(self):
        for threshold in (None, True, '0.9', float('nan'), float('inf'), -1, 0, 1.1):
            with self.subTest(threshold=threshold):
                self.assertFalse(compatible(card(), [1.], card(), [1.], threshold=threshold))

    def test_identical_vector_cannot_merge_distinct_developments(self):
        for field, value in [('action', 'recalled'), ('object', 'Product 3'),
                             ('date', '2026-09-02'), ('place_ids', ['country:us'])]:
            other = card()
            other['event_hints'][0][field] = value
            with self.subTest(field=field):
                self.assertFalse(compatible(card(), [1.], other, [1.], threshold=.9))

    def test_namesake_with_different_identity_never_merges(self):
        other = card()
        other['entities'][0]['resolved_id'] = 'company:other-north'
        self.assertFalse(compatible(card(), [1.], other, [1.], threshold=.9))

    def test_conflicting_identity_for_same_mention_abstains(self):
        value = card()
        value['entities'].append({**value['entities'][0], 'resolved_id': 'company:other'})
        self.assertIsNone(event_key(value))

    def test_unresolved_and_ambiguous_mentions_abstain(self):
        for resolution in ('unresolved', 'ambiguous'):
            value = card()
            value['entities'][0]['resolution'] = resolution
            self.assertIsNone(event_key(value))

    def test_unknown_invalid_and_missing_dates_abstain(self):
        for day in (None, '', '2026-02-30', 'yesterday'):
            value = card()
            value['event_hints'][0]['date'] = day
            self.assertIsNone(event_key(value))

    def test_multievent_and_roundup_never_force_dedupe(self):
        value = card()
        value['event_hints'].append(copy.deepcopy(value['event_hints'][0]))
        self.assertIsNone(event_key(value))
        for kind in ('roundup', 'listicle', 'opinion', 'satire', 'promo', 'unknown'):
            value = card()
            value['kind'] = kind
            self.assertIsNone(event_key(value))

    def test_missing_specific_action_or_object_abstains(self):
        for field in ('action', 'object'):
            for content in ('', '  ', None):
                value = card()
                value['event_hints'][0][field] = content
                self.assertIsNone(event_key(value))

    def test_similarity_is_still_required_for_same_event_tuple(self):
        self.assertFalse(compatible(card(), [1., 0.], card(), [0., 1.], threshold=.9))

    def test_bridge_does_not_imply_pairwise_compatibility(self):
        left, bridge, right = [1., 0.], [1., 1.], [0., 1.]
        self.assertTrue(compatible(card(), left, card(), bridge, threshold=.7))
        self.assertTrue(compatible(card(), bridge, card(), right, threshold=.7))
        self.assertFalse(compatible(card(), left, card(), right, threshold=.7))

    def test_event_keys_ignore_actor_order_and_duplicates(self):
        value = card()
        value['event_hints'][0]['actors'] *= 2
        value['event_hints'][0]['place_ids'] *= 2
        self.assertEqual(event_key(value), event_key(card()))

    def test_pgvector_text_decodes_and_invalid_vectors_abstain(self):
        self.assertEqual(cosine('[1.0, 0.0]', [1., 0.]), 1.)
        for vector in (None, 1, 'broken', '{}', '[true]', [True], ['1'],
                       [float('nan')], [float('inf')], [0.], [], [1., 1.]):
            with self.subTest(vector=vector):
                self.assertEqual(cosine(vector, [1.]), -1.)


if __name__ == '__main__':
    unittest.main()
