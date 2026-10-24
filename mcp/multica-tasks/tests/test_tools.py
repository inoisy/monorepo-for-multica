import threading
import unittest

from support import AGENT_A, AGENT_B, HIDDEN_WS, LEADER, OTHER_WS, SQUAD, WS, McpCase
from multica_tasks import tools


class Listing(McpCase):
    def test_ровно_девять_инструментов(self):
        self.assertEqual(sorted(tools.TOOLS), sorted([
            'list_workspaces', 'list_agents', 'list_issues', 'get_issue', 'list_agent_tasks',
            'comment_issue', 'update_issue', 'wake_issue', 'cancel_task']))
        self.assertEqual(len(tools.public_list()), 9)

    def test_воркспейсы_только_из_allowlist(self):
        slugs = [w['slug'] for w in self.ok('list_workspaces')['workspaces']]
        self.assertEqual(slugs, ['stt', 'toons'])

    def test_чужой_воркспейс_forbidden(self):
        for ref in ('hidden', HIDDEN_WS, 'Скрытый', 'нет-такого'):
            with self.subTest(ref):
                self.assertEqual(self.err('list_agents', workspace=ref)['code'], 'forbidden_workspace')
        self.assertFalse([r for r in self.fake.requests if r['path'] == '/api/agents'])

    def test_воркспейс_можно_не_указывать_только_если_он_один(self):
        self.assertEqual(self.err('list_agents')['code'], 'invalid_argument')
        self.service.allowed = ('stt',)
        self.service._workspaces = None
        self.ok('list_agents')


class StaleIssues(McpCase):
    def setUp(self):
        super().setUp()
        f = self.fake
        f.add_issue('TST-10', 'зависла', status='todo', minutes_ago=120)
        f.add_issue('TST-11', 'в работе давно', status='in_progress', minutes_ago=300)
        f.add_issue('TST-12', 'статус не тот', status='review', minutes_ago=500)
        f.add_issue('TST-13', 'у человека', status='todo', assignee=('member', 'u1'), minutes_ago=500)
        f.add_issue('TST-14', 'без исполнителя', status='todo', assignee=None, minutes_ago=500)
        busy = f.add_issue('TST-15', 'ран идёт', status='in_progress', minutes_ago=500)
        f.add_task(busy, AGENT_A, 'running')
        f.add_issue('TST-16', 'сквад', status='todo', assignee=('squad', SQUAD), minutes_ago=90)
        f.add_issue('TST-17', 'чужой воркспейс', status='todo', minutes_ago=500, workspace=OTHER_WS)

    def stale(self, minutes=60, **extra):
        return [i['identifier'] for i in self.ok('list_issues', workspace='stt', stale_minutes=minutes, **extra)['issues']]

    def test_условие_статус(self):
        self.assertNotIn('TST-12', self.stale())

    def test_условие_исполнитель_агент_или_сквад(self):
        found = self.stale()
        self.assertIn('TST-16', found)
        self.assertNotIn('TST-13', found)
        self.assertNotIn('TST-14', found)

    def test_условие_нет_активного_рана(self):
        self.assertNotIn('TST-15', self.stale())

    def test_условие_активность_старше_порога(self):
        self.assertNotIn('TST-1', self.stale(60))
        self.assertIn('TST-1', self.stale(3))
        self.assertEqual(self.stale(60), ['TST-11', 'TST-10', 'TST-16'])

    def test_завершённый_ран_не_считается_активным(self):
        issue = next(i for i in self.fake.issues.values() if i['identifier'] == 'TST-11')
        self.fake.add_task(issue['id'], AGENT_A, 'completed')
        self.assertIn('TST-11', self.stale())

    def test_без_stale_обычный_список_с_именами(self):
        data = self.ok('list_issues', workspace='stt', status='review')
        self.assertEqual([i['identifier'] for i in data['issues']], ['TST-12'])
        self.assertEqual(self.ok('list_issues', workspace='stt', status='todo', assignee='Бэкенд')['issues'][0]['assignee_name'], 'Бэкенд')

    def test_неверный_статус(self):
        self.assertEqual(self.err('list_issues', workspace='stt', status='TODO; drop')['code'], 'invalid_argument')


class GetIssue(McpCase):
    def test_описание_комментарии_и_раны(self):
        iid = self.fake.add_issue('TST-20', 'Задача')
        self.fake.comments[iid] = [{'id': f'c{n:02d}', 'content': f'коммент {n}', 'author_type': 'agent', 'author_id': 'x',
                                    'created_at': f'2026-10-24T10:{n:02d}:00Z'} for n in range(15)]
        self.fake.add_task(iid, AGENT_A, 'completed')
        self.fake.add_task(iid, AGENT_B, 'running')
        data = self.ok('get_issue', workspace='stt', issue='TST-20')
        self.assertEqual(data['issue']['description'], 'Описание TST-20')
        self.assertEqual([c['content'] for c in data['comments']], [f'коммент {n}' for n in range(5, 15)])
        self.assertEqual([r['status'] for r in data['runs']], ['completed', 'running'])
        self.assertEqual(len(self.ok('get_issue', workspace='stt', issue='TST-20', comments=3)['comments']), 3)
        self.assertEqual(self.ok('get_issue', workspace='stt', issue='TST-20', comments=0)['comments'], [])

    def test_задача_чужого_воркспейса_не_найдена(self):
        self.fake.add_issue('TST-21', 'не наша', workspace=OTHER_WS)
        self.assertEqual(self.err('get_issue', workspace='stt', issue='TST-21')['code'], 'not_found')

    def test_ключ_задачи_проверяется(self):
        self.assertEqual(self.err('get_issue', workspace='stt', issue='../agents')['code'], 'invalid_argument')

    def test_list_agent_tasks(self):
        iid = self.fake.add_issue('TST-22', 'x')
        self.fake.add_task(iid, AGENT_A, 'running')
        data = self.ok('list_agent_tasks', workspace='stt', agent='Бэкенд')
        self.assertEqual([t['status'] for t in data['tasks']], ['running'])
        self.assertEqual(self.err('list_agent_tasks', workspace='stt', agent='Нет')['code'], 'not_found')


class WakeIssue(McpCase):
    def setUp(self):
        super().setUp()
        self.iid = self.fake.add_issue('TST-30', 'будим', assignee=('agent', AGENT_A))

    def test_без_активного_рана_один_rerun(self):
        data = self.ok('wake_issue', workspace='stt', issue='TST-30')
        self.assertEqual((data['result'], self.fake.rerun_calls), ('queued', 1))
        self.assertEqual(data['task_id'], self.fake.tasks[-1]['id'])

    def test_активные_статусы_не_будят(self):
        for status in ('queued', 'dispatched', 'running', 'waiting_local_directory', 'deferred'):
            with self.subTest(status):
                self.fake.tasks.clear()
                task = self.fake.add_task(self.iid, AGENT_A, status)
                data = self.ok('wake_issue', workspace='stt', issue='TST-30')
                self.assertEqual(data, {'result': 'already_active', 'task_id': task, 'agent_id': AGENT_A, 'status': status})
        self.assertEqual(self.fake.rerun_calls, 0)

    def test_завершённый_ран_не_мешает(self):
        self.fake.add_task(self.iid, AGENT_A, 'completed')
        self.fake.add_task(self.iid, AGENT_A, 'failed')
        self.assertEqual(self.ok('wake_issue', workspace='stt', issue='TST-30')['result'], 'queued')

    def test_активный_ран_другого_агента_не_считается(self):
        self.fake.add_task(self.iid, AGENT_B, 'running')
        self.assertEqual(self.ok('wake_issue', workspace='stt', issue='TST-30')['result'], 'queued')

    def test_сквад_будит_лидера(self):
        self.fake.add_issue('TST-31', 'сквад', assignee=('squad', SQUAD))
        data = self.ok('wake_issue', workspace='stt', issue='TST-31')
        self.assertEqual((data['result'], data['agent_id']), ('queued', LEADER))
        again = self.ok('wake_issue', workspace='stt', issue='TST-31')
        self.assertEqual(again['result'], 'already_active')
        self.assertEqual(self.fake.rerun_calls, 1)

    def test_без_исполнителя_агента(self):
        self.fake.add_issue('TST-32', 'человек', assignee=('member', 'u1'))
        self.assertEqual(self.err('wake_issue', workspace='stt', issue='TST-32')['code'], 'no_agent_assignee')

    def test_параллельные_вызовы_дают_один_rerun(self):
        results, barrier = [], threading.Barrier(8)

        def worker():
            barrier.wait()
            results.append(self.ok('wake_issue', workspace='stt', issue='TST-30')['result'])

        threads = [threading.Thread(target=worker) for _ in range(8)]
        [t.start() for t in threads]
        [t.join() for t in threads]
        self.assertEqual(sorted(results), ['already_active'] * 7 + ['queued'])
        self.assertEqual(self.fake.rerun_calls, 1)


class UpdateIssue(McpCase):
    def setUp(self):
        super().setUp()
        self.iid = self.fake.add_issue('TST-40', 'меняем', assignee=('agent', AGENT_A))

    def puts(self):
        return [r for r in self.fake.requests if r['method'] == 'PUT']

    def test_всегда_suppress_run(self):
        self.ok('update_issue', workspace='stt', issue='TST-40', status='todo')
        self.ok('update_issue', workspace='stt', issue='TST-40', assignee='Тестировщик')
        self.ok('update_issue', workspace='stt', issue='TST-40', status='qa', wake=False)
        self.assertEqual(len(self.puts()), 3)
        self.assertTrue(all(r['body']['suppress_run'] is True for r in self.puts()))

    def test_только_статус_ран_не_ставит(self):
        self.ok('update_issue', workspace='stt', issue='TST-40', status='todo')
        self.assertEqual(self.fake.rerun_calls, 0)
        self.assertEqual(self.fake.issues[self.iid]['status'], 'todo')

    def test_wake_true_при_статусе_ставит_один_ран(self):
        data = self.ok('update_issue', workspace='stt', issue='TST-40', status='todo', wake=True)
        self.assertEqual((data['wake']['result'], self.fake.rerun_calls), ('queued', 1))

    def test_смена_исполнителя_и_комментарий_дают_один_ран(self):
        data = self.ok('update_issue', workspace='stt', issue='TST-40', assignee='Тестировщик')
        self.assertEqual((data['wake']['result'], data['wake']['agent_id']), ('queued', AGENT_B))
        self.ok('comment_issue', workspace='stt', issue='TST-40', text='передаю, смотри ветку')
        runs = [t for t in self.fake.tasks if t['issue_id'] == self.iid and t['status'] == 'queued']
        self.assertEqual(len(runs), 1)

    def test_сквад_по_имени_и_снятие_исполнителя(self):
        self.ok('update_issue', workspace='stt', issue='TST-40', assignee='Сквад', wake=False)
        issue = self.fake.issues[self.iid]
        self.assertEqual((issue['assignee_type'], issue['assignee_id']), ('squad', SQUAD))
        self.ok('update_issue', workspace='stt', issue='TST-40', assignee='none')
        self.assertEqual(self.puts()[-1]['body']['assignee_id'], None)

    def test_неизвестный_исполнитель_ничего_не_пишет(self):
        self.assertEqual(self.err('update_issue', workspace='stt', issue='TST-40', assignee='Призрак')['code'], 'not_found')
        self.assertEqual(self.puts(), [])

    def test_нужно_хоть_одно_изменение(self):
        self.assertEqual(self.err('update_issue', workspace='stt', issue='TST-40')['code'], 'invalid_argument')

    def test_ошибка_wake_после_записи_не_теряет_запись(self):
        self.fake.fail[('POST', f'/api/issues/{self.iid}/rerun')] = (403, {'error': 'invocation not allowed'})
        data = self.ok('update_issue', workspace='stt', issue='TST-40', assignee='Тестировщик')
        self.assertEqual(data['wake']['result'], 'failed')
        self.assertEqual(self.fake.issues[self.iid]['assignee_id'], AGENT_B)


class CommentIssue(McpCase):
    def setUp(self):
        super().setUp()
        self.iid = self.fake.add_issue('TST-50', 'комментируем', assignee=('agent', AGENT_A))

    def test_по_умолчанию_note_и_без_рана(self):
        data = self.ok('comment_issue', workspace='stt', issue='TST-50', text='заметка')
        self.assertEqual(self.fake.comments[self.iid][0]['content'], '/note заметка')
        self.assertEqual((data['woke'], data['posted_as_note']), ([], True))
        self.assertEqual(self.fake.tasks, [])

    def test_note_не_удваивается(self):
        self.ok('comment_issue', workspace='stt', issue='TST-50', text='/note уже помечено')
        self.assertEqual(self.fake.comments[self.iid][0]['content'], '/note уже помечено')

    def test_wake_публикует_обычный_и_называет_разбуженного(self):
        data = self.ok('comment_issue', workspace='stt', issue='TST-50', text='проснись', wake=True)
        self.assertEqual(self.fake.comments[self.iid][0]['content'], 'проснись')
        self.assertEqual([w['agent_id'] for w in data['woke']], [AGENT_A])
        self.assertFalse(data['posted_as_note'])

    def test_wake_с_note_противоречит(self):
        self.assertEqual(self.err('comment_issue', workspace='stt', issue='TST-50', text='/note x', wake=True)['code'], 'invalid_argument')
        self.assertEqual(self.fake.comments, {})

    def test_пустой_и_слишком_длинный_текст(self):
        self.assertEqual(self.err('comment_issue', workspace='stt', issue='TST-50', text='   ')['code'], 'invalid_argument')
        self.assertEqual(self.err('comment_issue', workspace='stt', issue='TST-50', text='x' * 20001)['code'], 'invalid_argument')


class CancelTask(McpCase):
    def test_cancel_возвращает_итоговый_статус(self):
        iid = self.fake.add_issue('TST-60', 'x')
        task = self.fake.add_task(iid, AGENT_A, 'running')
        data = self.ok('cancel_task', workspace='stt', task_id=task)
        self.assertEqual(data, {'task_id': task, 'status': 'cancelled'})
        self.assertEqual(self.writes()[-1]['path'], f'/api/tasks/{task}/cancel')

    def test_плохой_id_и_неизвестный_ран(self):
        self.assertEqual(self.err('cancel_task', workspace='stt', task_id='../x')['code'], 'invalid_argument')
        self.assertEqual(self.err('cancel_task', workspace='stt', task_id='eeeeeeee-0000-4000-8000-0000000000ff')['code'], 'api_404')


class Errors(McpCase):
    def test_ошибка_api_это_iserror_с_кодом_и_текстом(self):
        self.fake.fail[('GET', '/api/agents')] = (500, {'error': 'boom'})
        error = self.err('list_agents', workspace='stt')
        self.assertEqual((error['code'], error['message']), ('api_500', 'boom'))

    def test_недоступный_api(self):
        self.opener.down = True
        self.assertEqual(self.err('list_workspaces')['code'], 'api_unavailable')

    def test_лишние_и_неверные_аргументы(self):
        self.assertEqual(self.err('get_issue', issue='TST-1', evil=1)['code'], 'invalid_argument')
        self.assertEqual(self.err('get_issue', workspace='stt')['code'], 'invalid_argument')
        self.assertEqual(self.err('get_issue', workspace='stt', issue='TST-1', comments=True)['code'], 'invalid_argument')
        self.assertEqual(self.err('get_issue', workspace='stt', issue='TST-1', comments=999)['code'], 'invalid_argument')
        self.assertEqual(self.err('wake_issue')['code'], 'invalid_argument')

    def test_неизвестный_инструмент(self):
        self.assertEqual(self.err('delete_issue')['code'], 'unknown_tool')

    def test_успех_не_помечается_ошибкой(self):
        is_error, payload = self.call('list_workspaces')
        self.assertFalse(is_error)
        self.assertNotIn('error', payload)


if __name__ == '__main__':
    unittest.main()
