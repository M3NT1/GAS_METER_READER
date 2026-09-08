import importlib.util
from pathlib import Path
from datetime import datetime, timezone
import pytest

spec = importlib.util.spec_from_file_location('ledger', Path(__file__).parents[1] / 'custom_components/gas_photo/ledger.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
Ledger = module.Ledger
NOW = datetime(2026, 9, 7, tzinfo=timezone.utc)

def record(n, day=1, value='100.000', revision=1, **extra):
    return dict(id=f'{n:064x}', meter_id='gas_main', captured_at=f'2026-01-{day:02d}T12:43:42.865+01:00', value=value, revision=revision, source='manual_review', **extra)

def test_exact_baseline_ten_and_duplicate():
    ledger = Ledger()
    readings = [record(1), record(2, 2, '110.000')]
    ledger.apply(readings, now=NOW)
    ledger.apply(readings, now=NOW)
    assert len(ledger.readings()) == 2
    assert ledger.readings()[0]['captured_at'] == readings[0]['captured_at']
    assert ledger.hourly(now=NOW) == [dict(start='2026-01-01T11:00:00+00:00', state=100.0, sum=0.0), dict(start='2026-01-02T11:00:00+00:00', state=110.0, sum=10.0)]

def test_revision_audit_conflict_and_atomicity():
    ledger = Ledger()
    ledger.apply([record(1), record(2, 3, '110')], now=NOW)
    ledger.apply([record(2, 3, '111', 2)], now=NOW)
    assert len(ledger.dump()['history']) == 1
    for batch in [[record(2, 3, '110')], [record(2, 3, '112', 2)], [record(3, 2, '105'), record(4, 2, '106')]]:
        with pytest.raises(ValueError): ledger.apply(batch, now=NOW)
    assert len(ledger.readings()) == 2

def test_late_insertion_and_neighbors():
    ledger = Ledger()
    ledger.apply([record(1), record(3, 3, '110')], now=NOW)
    ledger.apply([record(2, 2, '105')], now=NOW)
    assert [r['sum'] for r in ledger.hourly(now=NOW)] == [0, 5, 10]
    with pytest.raises(ValueError): ledger.apply([record(4, 2, '111', captured='unused')], now=NOW)

def test_published_baseline_and_timestamp_protected():
    ledger = Ledger()
    ledger.apply([record(1), record(2, 2, '110')], now=NOW)
    ledger.prepare_publication(now=NOW)
    ledger = Ledger(ledger.dump())
    with pytest.raises(ValueError): ledger.apply([record(1, 1, '99', 2)], now=NOW)
    with pytest.raises(ValueError): ledger.apply([record(2, 3, '110', 2)], now=NOW)
    ledger.apply([record(2, 2, '109', 2)], now=NOW)
    assert ledger.hourly(now=NOW)[1]['sum'] == 9

@pytest.mark.parametrize('field,value', [('value','NaN'),('value','Infinity'),('value','-1'),('value','1.0001'),('revision',True),('captured_at','2026-01-01T00:00:00'),('captured_at','2099-01-01T00:00:00+00:00'),('metadata',{'huge':'x'*17000})])
def test_invalid(field,value):
    row=record(1); row[field]=value
    with pytest.raises(ValueError): Ledger().apply([row],now=NOW)

def test_same_hour_latest_and_open_hour():
    ledger=Ledger(); first=record(1); second=record(2,value='100.010'); second['captured_at']='2026-01-01T12:50:00+01:00'
    ledger.apply([second,first],now=NOW)
    assert ledger.hourly(now=NOW)[0]['state'] == 100.01
    assert ledger.hourly(now=NOW)[0]['sum'] == 0.01
    assert ledger.hourly(now=datetime(2026,1,1,11,55,tzinfo=timezone.utc)) == []

def test_rate_and_earlier_than_published_origin():
    ledger=Ledger(max_m3_per_hour=10)
    ledger.apply([record(1,2)],now=NOW)
    ledger.prepare_publication(now=NOW)
    with pytest.raises(ValueError): ledger.apply([record(2,1,'99')],now=NOW)
    with pytest.raises(ValueError): ledger.apply([record(3,3,'1000')],now=NOW)
