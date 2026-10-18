"""Единый формат отказа: {error, reason, missing}. Коды — контракт для CLI и MCP."""

CODES = frozenset({
    'unknown_component', 'forbidden_component', 'verb_not_allowed', 'validation_not_found', 'validation_failed',
    'digest_mismatch', 'artifact_tampered', 'policy_changed', 'ref_not_allowed', 'busy', 'locked_degraded',
    'unsafe_target', 'tests_decreased', 'not_installed',
    # служебные: разбор запроса, идемпотентность, неизвестная операция/релиз, сбой окружения
    'bad_request', 'idempotency_conflict', 'operation_not_found', 'release_not_found', 'internal',
})


class HarnessError(Exception):
    def __init__(self, code, reason, missing=None):
        assert code in CODES, code
        super().__init__(f'{code}: {reason}')
        self.code, self.reason, self.missing = code, reason, missing
        self.primary = None

    def with_primary(self, primary):
        """Первичная причина отказа проверки: check, exit_code, signal, timeout, oom_kill."""
        self.primary = primary
        return self

    def to_dict(self):
        out = {'error': self.code, 'reason': self.reason, 'missing': self.missing}
        if self.primary:
            out['primary_reason'] = self.primary
        return out
