"""CLI harness-control: тонкий адаптер. Аргументы уходят в harness-priv как есть, ответ печатается как есть."""
import sys

from . import client
from .commands import COMMANDS, parse
from .errors import HarnessError


def main(argv, call=client.call, out=sys.stdout):
    if not argv or argv[0] in ('-h', '--help'):
        out.write('harness-control <inspect|validate|deploy|rollback|op|log|ops> [аргументы]\n\n')
        for verb, spec in COMMANDS.items():
            out.write(f'  {verb:9} {spec["doc"]}\n')
        return 0 if argv else 2
    if argv[0] not in COMMANDS:
        out.write(client.dumps(client.unknown_verb(argv[0])) + '\n')
        return 2
    verb, tokens = argv[0], argv[1:]
    try:
        parse(verb, tokens)  # та же проверка, что в harness-priv: отказ без sudo
    except HarnessError as e:
        out.write(client.dumps(e.to_dict()) + '\n')
        return 2
    result = call(verb, tokens)
    out.write(client.dumps(result) + '\n')
    return 1 if 'error' in result else 0
