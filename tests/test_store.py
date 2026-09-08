from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import sqlite3

import pytest

from gasphoto.store import Store


@pytest.fixture
def store(tmp_path):
    return Store(tmp_path / 'ledger.sqlite')


def photo(store, n, at='2026-01-01T12:00:00.123+01:00', filename=None):
    return store.add_photo(f'{n:064x}', filename or f'{n}.jpg', f'/archive/{n}.jpg', at, {'exif': {'camera': 'phone'}})


def test_dedup_preserves_original_and_survives_reopen(store):
    first = photo(store, 1)
    store.add_photo(first['id'], 'changed.jpg', '/changed', None, {})
    assert len(store.list_photos()) == 1
    assert Store(store.db_path).get_photo(first['id']) == first
    assert first['metadata']['exif']['camera'] == 'phone'


def test_approval_outbox_revision_and_stale_ack(store):
    row = photo(store, 1)
    approved = store.approve(row['id'], '00100.123')
    assert approved['status'] == 'pending_sync'
    wire = store.pending_readings()[0]
    assert {k: v for k, v in wire.items() if k != 'metadata'} == {
        'id': row['id'], 'meter_id': 'gas_main', 'captured_at': row['captured_at'],
        'value': '100.123', 'revision': 1, 'source': 'manual_review',
    }
    store.set_sync_error(row['id'], 'offline')
    assert store.get_photo(row['id'])['error'] == 'offline'
    store.approve(row['id'], '100.124')
    assert store.mark_synced(row['id'], 1) is False
    assert store.get_photo(row['id'])['revision'] == 2
    assert store.mark_synced(row['id'], 2) is True
    assert store.pending_readings() == []
    assert store.get_photo(row['id'])['status'] == 'synced'


@pytest.mark.parametrize('value', ['NaN', 'Infinity', '-Infinity', '-0.001', '100000', '1.0001', '1e2', '', True, None, '1,234', '0x12'])
def test_invalid_values_cannot_be_approved(store, value):
    row = photo(store, 1)
    with pytest.raises(ValueError):
        store.approve(row['id'], value)
    assert store.pending_readings() == []


@pytest.mark.parametrize('value', ['0', '99999.999', '00001.002'])
def test_meter_range_endpoints(store, value):
    store.approve(photo(store, 1)['id'], value)
    assert len(store.pending_readings()) == 1


@pytest.mark.parametrize('at', [None, '', 'invalid', '2026-01-01T12:00:00', '2026-02-30T12:00:00+01:00'])
def test_invalid_capture_requires_manual_correction(store, at):
    row = photo(store, 1, at)
    with pytest.raises(ValueError):
        store.approve(row['id'], '100')
    corrected = store.approve(row['id'], '100', '2026-01-01T12:00:00.001+01:00')
    assert corrected['metadata']['original_captured_at'] == at
    assert corrected['metadata']['review_history'][-1]['captured_at'] == corrected['captured_at']


def test_future_capture_rejected(store):
    row = photo(store, 1, (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat())
    with pytest.raises(ValueError, match='future'):
        store.approve(row['id'], '100')


def test_out_of_range_utc_conversion_is_reviewable(store):
    row = photo(store, 1, '0001-01-01T00:00:00+01:00')
    assert row['status'] == 'needs_timestamp'
    with pytest.raises(ValueError):
        store.approve(row['id'], '100')


def test_previous_and_next_neighbors_checked_and_equal_allowed(store):
    left = photo(store, 1, '2026-01-01T10:00:00+00:00')
    right = photo(store, 2, '2026-01-01T14:00:00+00:00')
    middle = photo(store, 3, '2026-01-01T13:00:00+01:00')
    store.approve(left['id'], '100')
    store.approve(right['id'], '110')
    for value in ['99', '111']:
        with pytest.raises(ValueError):
            store.approve(middle['id'], value)
    store.approve(middle['id'], '100')
    with pytest.raises(ValueError):
        store.approve(left['id'], '101')


def test_same_instant_conflict_uses_utc(store):
    first = photo(store, 1)
    second = photo(store, 2, '2026-01-01T11:00:00.123Z')
    store.approve(first['id'], '100')
    with pytest.raises(ValueError):
        store.approve(second['id'], '100.001')
    store.approve(second['id'], '100')


def test_rate_limit_applies_in_both_directions_with_liter_tolerance(store):
    store.approve(photo(store, 1, '2026-01-01T10:00:00Z')['id'], '100')
    future = photo(store, 2, '2026-01-01T11:00:00Z')
    with pytest.raises(ValueError):
        store.approve(future['id'], '106.002')
    store.approve(future['id'], '106.001')
    earlier = photo(store, 3, '2026-01-01T09:00:00Z')
    with pytest.raises(ValueError):
        store.approve(earlier['id'], '93.998')


def test_custom_rate_limit(tmp_path):
    store = Store(tmp_path / 'custom.db', max_m3_per_hour=1)
    store.approve(photo(store, 1, '2026-01-01T10:00:00Z')['id'], '100')
    with pytest.raises(ValueError):
        store.approve(photo(store, 2, '2026-01-01T11:00:00Z')['id'], '102')


def test_proposal_cannot_change_accepted_record(store):
    row = photo(store, 1)
    assert store.set_proposal(row['id'], {'value': '100'})['proposal'] == {'value': '100'}
    store.approve(row['id'], '100')
    before = store.get_photo(row['id'])
    store.set_proposal(row['id'], {'value': '999'}, 'ocr error')
    assert store.get_photo(row['id']) == before


def test_recognition_proposals_expose_position_and_counter_statuses(store):
    position = photo(store, 1)
    store.set_proposal(position['id'], {'value': None, 'crop': [.2, .4, .8, .5]})
    assert store.get_photo(position['id'])['status'] == 'position_identified'
    counter = photo(store, 2)
    store.set_proposal(counter['id'], {'value': '01817.759', 'crop': [.2, .4, .8, .5]})
    assert store.get_photo(counter['id'])['status'] == 'counter_recognized'


def test_metadata_and_proposals_must_be_json_objects(store):
    with pytest.raises(ValueError):
        store.add_photo('a' * 64, 'a.jpg', '/a', None, [])
    row = photo(store, 1)
    for invalid in [[], 'text', {'score': float('nan')}]:
        with pytest.raises(ValueError):
            store.set_proposal(row['id'], invalid)


def test_latest_capture_order_uses_instant_and_stable_filename(store):
    photo(store, 1, '2026-01-01T12:00:00+02:00', 'b.jpg')
    photo(store, 2, '2026-01-01T11:00:00Z', 'c.jpg')
    photo(store, 3, '2026-01-01T10:00:00Z', 'a.jpg')
    photo(store, 4, None)
    assert [r['filename'] for r in store.list_photos()] == ['c.jpg', 'a.jpg', 'b.jpg', '4.jpg']


def test_parallel_calls_use_independent_connections_and_preserve_revisions(store):
    row = photo(store, 1)
    with ThreadPoolExecutor(max_workers=6) as pool:
        list(pool.map(lambda _: store.approve(row['id'], '100'), range(12)))
    assert store.get_photo(row['id'])['revision'] == 12
    with sqlite3.connect(store.db_path) as connection:
        assert connection.execute('SELECT COUNT(*) FROM audit WHERE photo_id=?', (row['id'],)).fetchone()[0] == 12


def test_missing_ids_and_invalid_identifiers(store):
    assert store.get_photo('f' * 64) is None
    with pytest.raises(ValueError):
        store.approve('f' * 64, '1')
    with pytest.raises(ValueError):
        store.add_photo('not-a-hash', 'a', '/a', None, {})


def test_training_example_is_bound_to_an_approved_revision(store):
    row = photo(store, 1)
    store.approve(row['id'], '01817.759')
    example = store.record_training_example(
        row['id'],
        [[.20, .44], [.80, .44], [.80, .52], [.20, .52]],
        '01817.759',
        'corrected',
    )
    assert example['value_digits'] == '01817759'
    assert example['photo_id'] == row['id']
    assert store.training_examples() == [example]
