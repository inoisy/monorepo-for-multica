import io
import json
import os
import tarfile
import tempfile
import unittest
from pathlib import Path

from support import PKG
from harness_control import commands, policy, redact as redact_mod, source
from harness_control.errors import HarnessError


def tar_of(*members):
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode='w') as tar:
        for name, kind, data in members:
            info = tarfile.TarInfo(name)
            if kind == 'file':
                info.size = len(data)
                tar.addfile(info, io.BytesIO(data))
            elif kind == 'symlink':
                info.type, info.linkname = tarfile.SYMTYPE, data
                tar.addfile(info)
            elif kind == 'dir':
                info.type = tarfile.DIRTYPE
                tar.addfile(info)
    return buf.getvalue()


class Redact(unittest.TestCase):
    def test_секреты_разных_видов(self):
        text = '\n'.join(['API_KEY=abcdef123456', 'Authorization: Bearer abcdefghijkl123', 'https://user:pw1234@host/x.git',
                          'ghp_abcdefghijklmnopqrstuv', '-----BEGIN PRIVATE KEY-----\nMIIB\n-----END PRIVATE KEY-----'])
        out = redact_mod.redact(text)
        for leaked in ('abcdef123456', 'abcdefghijkl123', 'pw1234', 'ghp_abcdefghijklmnopqrstuv', 'MIIB'):
            self.assertNotIn(leaked, out)

    def test_значения_из_окружения_вырезаются_дословно(self):
        self.assertEqual(redact_mod.redact('a zzzzzzzz b', ['zzzzzzzz']), f'a {redact_mod.REDACTED} b')


class Commands(unittest.TestCase):
    def test_parse_и_tokenize_обратимы(self):
        for verb, args in (('validate', {'component': 'harness-canary', 'sha': 'a' * 40, 'key': 'k', 'reason': 'зачем'}),
                           ('deploy', {'component': 'harness-canary', 'validation': '1792306160452-f8ac82a5', 'digest': 'sha256:' + 'b' * 64}),
                           ('log', {'id': '1792306160452-f8ac82a5', 'tail': 7}), ('inspect', {}), ('rollback', {'component': 'x', 'to': 'baseline'})):
            self.assertEqual(commands.parse(verb, commands.tokenize(verb, args)), args)

    def test_лишнее_и_недостающее(self):
        for verb, tokens in (('validate', ['harness-canary']), ('validate', ['a', 'b', 'c']), ('deploy', ['x']), ('inspect', ['--nope', '1']),
                             ('log', ['1792306160452-f8ac82a5', '--tail', 'abc']), ('rollback', ['x', '--to'])):
            with self.assertRaises(HarnessError) as cm:
                commands.parse(verb, tokens)
            self.assertEqual(cm.exception.code, 'bad_request')


class Extract(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def test_обычные_файлы_распаковываются_с_нормальными_правами(self):
        dest = source.extract(tar_of(('a.txt', 'file', b'1'), ('d', 'dir', None), ('d/b.sh', 'file', b'2')), Path(self.tmp.name) / 'x')
        self.assertEqual((dest / 'd' / 'b.sh').read_text(), '2')
        self.assertEqual(oct((dest / 'a.txt').stat().st_mode & 0o777), '0o644')

    def test_симлинк_и_выход_за_каталог_запрещены(self):
        for member in (('l', 'symlink', '/etc/passwd'), ('../escape', 'file', b'x'), ('/abs', 'file', b'x')):
            with self.subTest(member[0]), self.assertRaises(HarnessError) as cm:
                source.extract(tar_of(member), Path(self.tmp.name) / 'y')
            self.assertEqual(cm.exception.code, 'validation_failed')
        self.assertFalse((Path(self.tmp.name) / 'escape').exists())


class Policies(unittest.TestCase):
    def raw(self):
        return json.loads((PKG / 'policy.d' / 'harness-canary.json').read_text())

    def test_поставляемые_политики_корректны(self):
        for path in sorted((PKG / 'policy.d').glob('*.json')):
            b = path.read_bytes()
            self.assertEqual(policy.Policy(json.loads(b), b, 'c', '1').name, path.stem)

    def test_строгая_схема(self):
        cases = {
            'неизвестный ключ': lambda r: r.update(evil=1),
            'dst с ..': lambda r: r['targets'][0].update(dst='/usr/local/../etc/x'),
            'dst относительный': lambda r: r['targets'][0].update(dst='x/y'),
            'режим setuid': lambda r: r['targets'][0].update(mode='4755'),
            'юнит не service/timer': lambda r: r['timers'].append('x.socket'),
            'http не на loopback': lambda r: r['health'].update(http=[{'url': 'http://example.com/', 'expect': [200]}]),
            'source.path абсолютный': lambda r: r['source'].update(path='/etc'),
            'source.path с ..': lambda r: r['source'].update(path='a/../b'),
        }
        for name, mutate in cases.items():
            with self.subTest(name), self.assertRaises(policy.PolicyError):
                raw = self.raw()
                mutate(raw)
                policy.Policy._validate(raw)

    def test_версия_политики_зависит_от_политики_проверок_и_harness(self):
        b = (PKG / 'policy.d' / 'harness-canary.json').read_bytes()
        base = policy.Policy(json.loads(b), b, 'checks-1', 'v1').version
        self.assertNotEqual(base, policy.Policy(json.loads(b), b, 'checks-2', 'v1').version)
        self.assertNotEqual(base, policy.Policy(json.loads(b), b, 'checks-1', 'v2').version)
        b2 = b.replace(b'"timeout": 300', b'"timeout": 301')
        self.assertNotEqual(base, policy.Policy(json.loads(b2), b2, 'checks-1', 'v1').version)

    def test_хэш_каталога_checks_видит_правку_и_запрещает_симлинки(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / 'a.py').write_text('1')
            before = policy.hash_tree(d)
            (Path(d) / 'a.py').write_text('2')
            self.assertNotEqual(before, policy.hash_tree(d))
            (Path(d) / 'l').symlink_to('a.py')
            with self.assertRaises(policy.PolicyError):
                policy.hash_tree(d)


if __name__ == '__main__':
    unittest.main()
