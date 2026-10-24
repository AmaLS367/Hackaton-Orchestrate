"""Package this checkout's raw Codex/Claude JSONL traces; run after quitting both apps.

--exclude-session prepares an incomplete archive while the excluded session is active.
Original paths and JSONL structure are retained; credential strings are redacted.
Always inspect the resulting archive before sharing it.
"""

import argparse
import json
import os
import re
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOKEN = re.compile(r'\b(?:sk-[A-Za-z0-9_-]{16,}|gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})\b')
ASSIGNMENT = re.compile(
    r'(?i)(\b(?:[A-Z_]*(?:API_KEY|ACCESS_TOKEN|REFRESH_TOKEN|PASSWORD|CLIENT_SECRET))\s*[=:]\s*[\"\']?)'
    r'([A-Za-z0-9_./+\-]{16,})')
BEARER = re.compile(r'(?i)(\bBearer\s+)[A-Za-z0-9._~+/-]{20,}')
PRIVATE_KEYS = {'api_key', 'access_token', 'refresh_token', 'password', 'authorization',
                'creator_user_id', 'creator_account_id'}


def redact(value):
    if isinstance(value, dict):
        return {k: '[REDACTED]' if k.casefold() in PRIVATE_KEYS and isinstance(v, str) and v else redact(v)
                for k, v in value.items()}
    if isinstance(value, list):
        return [redact(v) for v in value]
    if isinstance(value, str):
        value = TOKEN.sub('[REDACTED]', value)
        value = ASSIGNMENT.sub(r'\1[REDACTED]', value)
        value = BEARER.sub(r'\1[REDACTED]', value)
        value = re.sub(r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----.*?'
                       r'-----END (?:RSA |EC |OPENSSH )?PRIVATE KEY-----', '[REDACTED]', value, flags=re.S)
    return value


def sanitized_jsonl(path):
    lines, changes = [], 0
    for raw in path.read_text(encoding='utf-8').splitlines(keepends=True):
        original = json.loads(raw)
        cleaned = redact(original)
        if cleaned == original:
            lines.append(raw)
        else:
            lines.append(json.dumps(cleaned, ensure_ascii=False, separators=(',', ':')) + '\n')
            changes += 1
    return ''.join(lines).encode('utf-8'), changes


def same_checkout(cwd, root):
    return str(cwd).replace('\\', '/').rstrip('/').casefold() == str(root).replace('\\', '/').rstrip('/').casefold()


def discover(root, codex_home, claude_home, excluded=()):
    result = {}
    sessions = codex_home / 'sessions'
    for path in sorted(sessions.rglob('rollout-*.jsonl')):
        try:
            with path.open(encoding='utf-8') as stream:
                first = json.loads(next(stream))
        except (OSError, StopIteration, ValueError):
            # Empty/in-progress files elsewhere cannot identify this checkout.
            continue
        meta = first.get('payload', {})
        if first.get('type') != 'session_meta' or not same_checkout(meta.get('cwd'), root):
            continue
        if meta.get('id', meta.get('session_id')) in excluded:
            continue
        result['agent-trace/codex/sessions/' + path.relative_to(sessions).as_posix()] = path
    projects = claude_home / 'projects'
    for project in sorted(projects.iterdir()) if projects.is_dir() else ():
        if not project.is_dir():
            continue
        matches = False
        for path in sorted(project.glob('*.jsonl')):
            with path.open(encoding='utf-8') as stream:
                for raw in stream:
                    if same_checkout(json.loads(raw).get('cwd'), root):
                        matches = True
                        break
            if matches:
                break
        if matches:
            for path in sorted(project.rglob('*.jsonl')):
                if path.stem not in excluded:
                    result['agent-trace/claude-code/projects/' + path.relative_to(projects).as_posix()] = path
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--codex-home', type=Path, default=Path(os.environ.get('CODEX_HOME', Path.home() / '.codex')))
    parser.add_argument('--claude-home', type=Path, default=Path.home() / '.claude')
    parser.add_argument('--exclude-session', action='append', default=[])
    parser.add_argument('--destination', type=Path, default=ROOT / 'agent-trace.zip')
    args = parser.parse_args()
    if args.destination.resolve().is_relative_to(ROOT / 'dataset'):
        parser.error('traces must remain outside dataset')
    files = discover(ROOT, args.codex_home, args.claude_home, set(args.exclude_session))
    if not files:
        parser.error('no matching local structured traces found; export manually per agent_trace_instructions.md')
    redactions = 0
    with zipfile.ZipFile(args.destination, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        for name, path in sorted(files.items()):
            before = path.stat()
            data, count = sanitized_jsonl(path)
            after = path.stat()
            if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                raise ValueError('trace changed during copy; quit the harness and retry')
            archive.writestr(name, data)
            redactions += count
    with zipfile.ZipFile(args.destination) as archive:
        assert archive.namelist() == sorted(files) and archive.testzip() is None
        for name in archive.namelist():
            for line in archive.read(name).decode('utf-8').splitlines():
                json.loads(line)
    print(json.dumps({'archive': str(args.destination), 'structured_trace_files': len(files),
        'redacted_jsonl_entries': redactions, 'excluded_sessions': args.exclude_session,
        'manual_steps': 'After quitting apps: rerun without exclusions; export Claude /export transcripts; '
                        'inspect ZIP for personal information and secrets before sharing.'}, indent=2))


if __name__ == '__main__':
    main()
