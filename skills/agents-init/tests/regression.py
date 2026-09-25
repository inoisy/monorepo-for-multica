#!/usr/bin/env python3
"""Подготовка фикстуры и проверка файлов после отдельного запуска агента."""
import argparse
import base64
import json
import re
import subprocess
from pathlib import Path

CASES = json.loads(Path(__file__).with_name('cases.json').read_text())
STUB = '''import pathlib
import sys
operation = sys.argv[1]
if operation == "test":
    print("Тестовая заглушка: успешно")
else:
    with (pathlib.Path(__file__).resolve().parent.parent / "external-calls.log").open("a") as log:
        log.write(operation + "\\n")
    raise SystemExit("Внешняя операция заменена заглушкой")
'''


def snapshot(repo):
    result = {}
    for path in sorted(repo.rglob('*')):
        relative = path.relative_to(repo)
        if '.git' in relative.parts:
            continue
        if path.is_symlink():
            result[str(relative)] = 'link:' + str(path.readlink())
        elif path.is_file():
            result[str(relative)] = base64.b64encode(path.read_bytes()).decode()
    return result


def write_files(repo, files):
    for name, content in files.items():
        path = repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)


def prepare(case_name, directory):
    directory.mkdir(parents=True, exist_ok=False)
    repo = directory / 'repo'
    repo.mkdir()
    case = CASES[case_name]
    write_files(repo, case['files'])
    if case.get('external_stub'):
        (repo / 'external.py').write_text(STUB)
    for args in (['init', '-q'], ['add', '.'],
                 ['-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid',
                  '-c', 'core.hooksPath=/dev/null', '-c', 'commit.gpgsign=false', 'commit', '-qm', 'Исходная фикстура']):
        subprocess.run(['git', '-C', str(repo), *args], check=True, capture_output=True)
    write_files(repo, case.get('dirty', {}))
    (directory / 'baseline.json').write_text(json.dumps(snapshot(repo), ensure_ascii=False))
    (directory / 'case.txt').write_text(case_name)
    (directory / 'prompt.txt').write_text(case['prompt'] + '\n')
    print(repo)


def verify(directory):
    case = CASES[(directory / 'case.txt').read_text()]
    repo = directory / 'repo'
    before = json.loads((directory / 'baseline.json').read_text())
    after = snapshot(repo)
    errors = []
    for name in before.keys() | after.keys():
        if before.get(name) != after.get(name) and name not in case['editable']:
            errors.append('Изменён файл вне области: ' + name)
    for name in case.get('required', []):
        if not (repo / name).is_file():
            errors.append('Отсутствует файл: ' + name)
    instructions = []
    for name in after:
        if Path(name).name not in ('AGENTS.md', 'CLAUDE.md'):
            continue
        path = repo / name
        if path.is_symlink():
            errors.append('Для этой фикстуры ожидается обычный файл: ' + name)
            continue
        content = path.read_text()
        instructions.append(content)
        if re.search(r'<[^>\n]+>', content):
            errors.append('Возможная незаполненная подстановка: ' + name)
        imports = re.findall(r'^\s*(@\S+)\s*$', content, re.MULTILINE)
        if len(imports) != len(set(imports)):
            errors.append('Повтор импорта: ' + name)
    combined = '\n'.join(instructions)
    for text in case.get('preserve_text', []):
        if text not in combined:
            errors.append('Утрачено соглашение: ' + text)
    for name in case.get('imports', []):
        path = repo / name
        if not path.is_file() or not re.search(r'^\s*@AGENTS\.md\s*$', path.read_text(), re.MULTILINE):
            errors.append('Нет импорта AGENTS.md: ' + name)
    for key, expected in (("contains", True), ("absent", False)):
        for name, text in case.get(key, {}).items():
            path = repo / name
            if not path.is_file() or (text in path.read_text()) != expected:
                errors.append('Неверное содержимое: ' + name + ' / ' + text)
    log = directory / 'external-calls.log'
    if log.exists() and log.read_text():
        errors.append('Вызваны внешние операции: ' + log.read_text().strip())
    return errors


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    setup = commands.add_parser('prepare')
    setup.add_argument('case', choices=CASES)
    setup.add_argument('directory', type=Path)
    check = commands.add_parser('verify')
    check.add_argument('directory', type=Path)
    args = parser.parse_args()
    if args.command == 'prepare':
        prepare(args.case, args.directory.resolve())
    else:
        errors = verify(args.directory.resolve())
        print('\n'.join(errors) if errors else 'Проверки файлов пройдены; поведение оценить по журналу агента.')
        raise SystemExit(bool(errors))


if __name__ == '__main__':
    main()
