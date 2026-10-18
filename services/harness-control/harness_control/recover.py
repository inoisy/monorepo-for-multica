"""Доводка прерванных операций: после перезагрузки или падения runner'а.

Правило одно: файлы возвращаются к набору, который был до операции (журнал switch.json в forward/), юниты
перезапускаются под этот набор, операция получает статус interrupted с записью в журнале. Новая версия без
пройденного health никогда не остаётся «наполовину».
"""
import contextlib
import shutil

from . import activate
from .errors import HarnessError
from .store import file_lock

QUEUED_GRACE = 120  # runner мог быть запущен только что: свежие queued не трогаем


def recover_all(h, force=False):
    results = []
    for op in h.store.unfinished():
        unit = f'harness-op-{op["id"]}.service'
        if h.system.unit_props(unit, ['ActiveState']).get('ActiveState') in ('active', 'activating'):
            results.append({'operation_id': op['id'], 'action': 'skipped', 'note': 'runner ещё работает'})
            continue
        if op['status'] == 'queued' and h.clock() - op['created_at'] < QUEUED_GRACE and not force:
            results.append({'operation_id': op['id'], 'action': 'skipped', 'note': 'runner мог ещё не стартовать'})
            continue
        results.append(_recover_one(h, op))
    return {'recovered': results}


def _recover_one(h, op):
    op_id = op['id']
    note = 'прервана до начала замены файлов, целевые файлы не менялись'
    restored = 0
    try:
        if op['verb'] == 'validate' or op['status'] == 'queued':
            note = 'не была выполнена до конца (проверка или запуск прерваны)' if op['status'] != 'queued' else 'runner не запускался'
            shutil.rmtree(h.paths.work / op_id, ignore_errors=True)
        else:
            policy = h.policies.get(op['component'])
            with h._component_lock(policy) as got:
                if not got:
                    return {'operation_id': op_id, 'action': 'skipped', 'note': 'компонент занят другой операцией'}
                restored = activate.restore(h.paths, h.paths.op_dir(op_id) / 'forward', h.owner)
                comp = h.store.component(op['component'])
                # Таймеры мог остановить runner ещё до первой записи, поэтому юниты приводятся в порядок всегда;
                # перезапуск юнитов из политики нужен только если файлы возвращались.
                h.apply_units(policy, h.lanes_of(policy, comp['current_release'] or 'baseline'), changed=None if restored else set())
                if restored:
                    note = f'прервана при замене файлов: восстановлен прежний набор ({restored} файлов)'
                elif (h.paths.op_dir(op_id) / 'forward' / 'switch.json').exists():
                    note = 'прервана после замены или при проверке: файлы уже соответствуют прежнему набору'
                shutil.rmtree(h.paths.work / op_id, ignore_errors=True)
    except (HarnessError, OSError) as e:
        h.store.set_status(op_id, 'interrupted', f'recover не смог вернуть прежний набор: {e}')
        if op['verb'] != 'validate':
            h.store.update_component(op['component'], degraded=1)
        return {'operation_id': op_id, 'action': 'failed', 'note': str(e)}
    h.store.set_status(op_id, 'interrupted', f'recover: {note}')
    h._log(op_id, f'recover: {note}')
    return {'operation_id': op_id, 'action': 'interrupted', 'restored_files': restored, 'note': note}
