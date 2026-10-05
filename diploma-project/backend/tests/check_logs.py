"""Verify diagnostic correlation and secret absence without displaying log content."""
import subprocess
from dotenv import dotenv_values


env = dotenv_values('../.env')
result = subprocess.run(['docker', 'compose', 'logs', '--no-color', 'backend'], capture_output=True, text=True, encoding='utf-8')
assert result.returncode == 0, 'Could not read local backend logs'
logs = result.stdout + result.stderr
checked = 0
for name, value in env.items():
    if value and any(part in name for part in ('PASSWORD', 'KEY', 'DATABASE_URL')):
        assert value not in logs, 'Secret-bearing diagnostic output detected; do not display it'
        checked += 1
assert 'check_failed' in logs and 'request_id' in logs and 'operation_id' in logs and 'resolve_fields' in logs and 'error_type' in logs
print(f'PASS: request/operation/stage/error correlation; {checked} configured secret values absent from backend logs')
