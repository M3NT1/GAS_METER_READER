"""Exercise the real Receiver class with a failing storage/queue adapter.

HA is not installed: AST loading isolates the coordinator, not HA registration.
"""
import ast
import asyncio
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import logging
import pytest
from test_ha_ledger import Ledger, record, module

class SaveStore:
    def __init__(self,fail=False): self.saved=[]; self.fail=fail
    async def async_save(self,data):
        if self.fail: raise OSError('disk full')
        self.saved.append(deepcopy(data))

def receiver(store,queue,admin=True):
    path=Path(__file__).parents[1]/'custom_components/gas_photo/__init__.py'
    tree=ast.parse(path.read_text())
    tree.body=[node for node in tree.body if isinstance(node,ast.ClassDef) and node.name=='Receiver']
    namespace=dict(asyncio=asyncio,Ledger=Ledger,timestamp=module.timestamp,ServiceValidationError=ValueError,Unauthorized=PermissionError,DOMAIN='gas_photo',METADATA={},_LOGGER=logging.getLogger('test'),async_add_external_statistics=queue,async_dispatcher_send=lambda *args:None)
    exec(compile(tree,str(path),'exec'),namespace)
    async def user(_):return SimpleNamespace(is_admin=admin)
    return namespace['Receiver'](SimpleNamespace(auth=SimpleNamespace(async_get_user=user)),store,Ledger())

def call(): return SimpleNamespace(context=SimpleNamespace(user_id='user'),data={'readings':[record(1)]})

def test_disk_failure_does_not_accept_or_queue():
    queue=[]; obj=receiver(SaveStore(True),lambda *args:queue.append(args))
    with pytest.raises(OSError):asyncio.run(obj.import_readings(call()))
    assert obj.ledger.readings()==[]
    assert queue==[]

def test_store_and_locks_exist_before_queue_and_ids_readback():
    store=SaveStore(); snapshots=[]
    def queue(*args): snapshots.append(deepcopy(store.saved[-1]))
    obj=receiver(store,queue)
    response=asyncio.run(obj.import_readings(call()))
    assert response['accepted']==[{'id':record(1)['id'],'revision':1}]
    assert snapshots[0]['pending'] is True
    assert snapshots[0]['locked_ids']==[record(1)['id']]
    assert obj.query({'ids':[record(1)['id']]})=={'readings':[record(1)]}

def test_non_admin_rejected_before_storage():
    store=SaveStore();obj=receiver(store,lambda *args:None,admin=False)
    with pytest.raises(PermissionError):asyncio.run(obj.import_readings(call()))
    assert store.saved==[]

def test_queue_failure_is_pending_and_retryable():
    store=SaveStore()
    def failure(*args):raise RuntimeError('recorder stopped')
    obj=receiver(store,failure)
    response=asyncio.run(obj.import_readings(call()))
    assert response['statistics_status']=='pending'
    assert len(store.saved[-1]['records'])==1

def test_statistics_readback_requires_bounded_offset_range():
    obj=receiver(SaveStore(),lambda *args:None)
    for query in [{'start':'2026-01-01','end':'2026-01-02'}, {'start':'2026-01-01T00:00:00+00:00','end':'2026-03-01T00:00:00+00:00'}]:
        with pytest.raises(ValueError):asyncio.run(obj.statistics(query))
