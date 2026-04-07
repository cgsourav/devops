"""Invoke the real `theiux` CLI (no simulated deploy)."""

from __future__ import annotations

import os
import queue
import re
import subprocess
import threading
import time
from collections.abc import Iterator
from urllib.parse import urlparse

from app.config import settings

SAFE_PATTERN = re.compile(r'^[a-zA-Z0-9._:/@-]+$')


def subprocess_env_for_tools() -> dict[str, str]:
    """Ensure common tool locations are on PATH (theiux invokes terraform, aws, git)."""
    env = os.environ.copy()
    prefix = '/usr/local/bin:/usr/bin:/bin'
    p = env.get('PATH')
    if not p:
        env['PATH'] = prefix
    else:
        env['PATH'] = f'{prefix}:{p}'
    return env


RUNTIME_PATTERN = re.compile(r'^[a-z0-9][a-z0-9-]*$')
VERSION_PATTERN = re.compile(r'^[a-zA-Z0-9._-]+$')
# Hostname-safe label for *.theiux.local style domains
DOMAIN_LABEL_PATTERN = re.compile(r'^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$')


class TheiuxDeployError(Exception):
    """Non-zero exit or failed remote SSM status after running `theiux deploy-site`."""

    def __init__(
        self,
        message: str,
        *,
        exit_code: int,
        category: str,
        combined_output: str = '',
        reason: str = '',
    ) -> None:
        super().__init__(message)
        self.exit_code = exit_code
        self.category = category
        self.combined_output = combined_output
        # Short machine-readable hint: local_timeout | ssm_timeout | ssm_incomplete | deploy_failed
        self.reason = reason or 'deploy_failed'


def _safe(value: str) -> str:
    if not SAFE_PATTERN.fullmatch(value):
        raise ValueError(f'unsafe argument: {value}')
    if '..' in value:
        raise ValueError('path traversal detected')
    return value


def _validate_repo(repo: str) -> str:
    parsed = urlparse(repo)
    if parsed.scheme not in {'https', 'ssh'}:
        raise ValueError('unsupported repo scheme')
    if not parsed.netloc and parsed.scheme == 'https':
        raise ValueError('invalid repo url')
    return _safe(repo)


def _validate_runtime(runtime: str, runtime_version: str) -> tuple[str, str]:
    if not RUNTIME_PATTERN.fullmatch(runtime):
        raise ValueError('invalid runtime')
    if not VERSION_PATTERN.fullmatch(runtime_version):
        raise ValueError('invalid runtime version')
    return runtime, runtime_version


def deploy_domain_for_app(app_name: str, base_suffix: str | None = None) -> str:
    """Deterministic site FQDN: <sanitized>.theiux.local (or custom suffix)."""
    base = (base_suffix or 'theiux.local').strip('.')
    raw = (app_name or 'app').strip().lower()
    label = re.sub(r'[^a-z0-9-]+', '-', raw).strip('-') or 'app'
    if len(label) > 63:
        label = label[:63].rstrip('-')
    if not DOMAIN_LABEL_PATTERN.match(label):
        label = 'app-' + label[:50]
    return f'{label}.{base}'


def apps_csv_for_bench(app_name: str) -> str:
    """Frappe bench needs `frappe` plus any custom app name."""
    name = (app_name or 'app').strip().lower()
    if name == 'frappe':
        return 'frappe'
    return f'frappe,{name}'


def classify_failure_from_exit_and_output(exit_code: int, combined: str) -> str:
    """Prefer exit-code signals (SSM / CLI) then log heuristics."""
    if exit_code == 124:
        return 'runtime_error'
    if exit_code == 130:
        return 'runtime_error'
    return classify_failure_from_output(combined)


def classify_failure_from_output(combined: str) -> str:
    """Map stderr/stdout text to API error categories."""
    t = combined.lower()
    if any(
        k in t
        for k in (
            'bootstrap-host',
            'automatic host bootstrap failed',
            'preflight missing',
            'host preflight failed after bootstrap',
            'unable to determine repo_url for bootstrap-host',
        )
    ):
        return 'bootstrap_error'
    if any(
        k in t
        for k in (
            'migration error',
            'migration failed',
            'migrate.py',
            'patch error',
            'schema sync',
            'database migration',
            'sql syntax',
            'pymysql.err',
        )
    ):
        return 'migration_error'
    if 'migrat' in t and any(x in t for x in ('error', 'fail', 'traceback', 'exception')):
        return 'migration_error'
    if any(
        k in t
        for k in (
            'build failed',
            'build error',
            'npm err',
            'yarn error',
            'pip install',
            'docker build',
            'error building',
            'compilation error',
            'gcc:',
            'failed building',
        )
    ):
        return 'build_error'
    if 'build' in t and any(x in t for x in ('error', 'failed', 'fatal')):
        return 'build_error'
    return 'runtime_error'


def ensure_remote_host_ready() -> Iterator[tuple[str, str]]:
    """Run preflight, auto-bootstrap once if needed, then re-check readiness."""
    yield '[bootstrap] Running remote host preflight checks', 'info'
    try:
        yield from stream_theiux_argv(['preflight-host'])
        yield '[bootstrap] Host preflight checks passed', 'info'
        return
    except TheiuxDeployError as preflight_err:
        yield f'[bootstrap] Preflight reported missing prerequisites ({preflight_err.reason}); attempting auto-bootstrap', 'error'

    try:
        yield from stream_theiux_argv(['bootstrap-host'])
    except TheiuxDeployError as bootstrap_err:
        raise TheiuxDeployError(
            'automatic host bootstrap failed',
            exit_code=bootstrap_err.exit_code,
            category='bootstrap_error',
            combined_output=bootstrap_err.combined_output,
            reason='bootstrap_failed',
        ) from bootstrap_err

    yield '[bootstrap] Verifying host readiness after bootstrap', 'info'
    try:
        yield from stream_theiux_argv(['preflight-host'])
    except TheiuxDeployError as postcheck_err:
        raise TheiuxDeployError(
            'host preflight failed after bootstrap',
            exit_code=postcheck_err.exit_code,
            category='bootstrap_error',
            combined_output=postcheck_err.combined_output,
            reason='bootstrap_incomplete',
        ) from postcheck_err
    yield '[bootstrap] Host is ready', 'info'


def stream_theiux_deploy(
    *,
    domain: str,
    git_repo_url: str,
    runtime: str,
    runtime_version: str,
    apps_csv: str,
) -> Iterator[tuple[str, str]]:
    """
    Run `theiux deploy-site` with validated argv only (no shell).
    Yields (line, level) where level is 'info' or 'error'.
    Raises TheiuxDeployError on non-zero exit.
    """
    yield from ensure_remote_host_ready()
    safe_domain = _safe(domain)
    _validate_runtime(runtime, runtime_version)
    if git_repo_url:
        _validate_repo(git_repo_url)

    cli = settings.theiux_cli_path
    cmd: list[str] = [
        cli,
        'deploy-site',
        '--domain',
        safe_domain,
        '--apps',
        apps_csv,
        '--runtime',
        runtime,
        '--runtime-version',
        runtime_version,
    ]
    if git_repo_url:
        cmd.extend(['--git-repo', _validate_repo(git_repo_url)])

    timeout = float(getattr(settings, 'theiux_deploy_timeout_seconds', 3600) or 3600)

    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
        env=subprocess_env_for_tools(),
    )
    assert proc.stdout is not None and proc.stderr is not None

    out_lines: list[str] = []
    err_lines: list[str] = []
    q: queue.Queue[tuple[str | None, str | None]] = queue.Queue()

    def pump(stream, bucket: list[str], tag: str) -> None:
        try:
            for line in iter(stream.readline, ''):
                bucket.append(line)
                q.put((tag, line.rstrip('\n')))
        finally:
            stream.close()
            q.put((None, None))

    t_out = threading.Thread(target=pump, args=(proc.stdout, out_lines, 'out'))
    t_err = threading.Thread(target=pump, args=(proc.stderr, err_lines, 'err'))
    t_out.start()
    t_err.start()

    finished = 0
    deadline = time.monotonic() + timeout
    while finished < 2:
        remaining = max(0.1, deadline - time.monotonic())
        if remaining <= 0:
            proc.kill()
            try:
                proc.wait(timeout=5)
            except Exception:
                pass
            t_out.join(timeout=2)
            t_err.join(timeout=2)
            combined = ''.join(out_lines) + ''.join(err_lines)
            raise TheiuxDeployError(
                f'local subprocess timed out after {int(timeout)}s (theiux deploy-site killed)',
                exit_code=-1,
                category='runtime_error',
                combined_output=combined,
                reason='local_timeout',
            )
        try:
            tag, line = q.get(timeout=min(remaining, 0.5))
        except queue.Empty:
            continue
        if tag is None:
            finished += 1
            continue
        assert line is not None
        yield line, 'error' if tag == 'err' else 'info'

    while True:
        try:
            tag, line = q.get_nowait()
        except queue.Empty:
            break
        if tag is None:
            continue
        if line is not None:
            yield line, 'error' if tag == 'err' else 'info'

    t_out.join(timeout=5)
    t_err.join(timeout=5)
    code = proc.wait(timeout=30)
    combined = ''.join(out_lines) + ''.join(err_lines)
    if code != 0:
        reason = 'deploy_failed'
        if code == 124:
            reason = 'ssm_timeout'
        elif code == 130:
            reason = 'ssm_cancelled'
        elif code == 2:
            reason = 'ssm_parse_or_api_error'
        cat = classify_failure_from_exit_and_output(code, combined)
        raise TheiuxDeployError(
            f'theiux deploy-site failed (exit {code})',
            exit_code=code,
            category=cat,
            combined_output=combined,
            reason=reason,
        )


def stream_theiux_argv(argv: list[str]) -> Iterator[tuple[str, str]]:
    """Run `theiux <argv...>` (SSM-backed). Yields (line, level). Raises TheiuxDeployError on failure."""
    if not argv:
        raise ValueError('empty argv')
    cli = settings.theiux_cli_path
    cmd: list[str] = [cli, *argv]
    timeout = float(getattr(settings, 'theiux_deploy_timeout_seconds', 3600) or 3600)
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
        env=subprocess_env_for_tools(),
    )
    assert proc.stdout is not None and proc.stderr is not None
    out_lines: list[str] = []
    err_lines: list[str] = []
    q: queue.Queue[tuple[str | None, str | None]] = queue.Queue()

    def pump(stream, bucket: list[str], tag: str) -> None:
        try:
            for line in iter(stream.readline, ''):
                bucket.append(line)
                q.put((tag, line.rstrip('\n')))
        finally:
            stream.close()
            q.put((None, None))

    t_out = threading.Thread(target=pump, args=(proc.stdout, out_lines, 'out'))
    t_err = threading.Thread(target=pump, args=(proc.stderr, err_lines, 'err'))
    t_out.start()
    t_err.start()
    finished = 0
    deadline = time.monotonic() + timeout
    while finished < 2:
        remaining = max(0.1, deadline - time.monotonic())
        if remaining <= 0:
            proc.kill()
            try:
                proc.wait(timeout=5)
            except Exception:
                pass
            t_out.join(timeout=2)
            t_err.join(timeout=2)
            combined = ''.join(out_lines) + ''.join(err_lines)
            raise TheiuxDeployError(
                f'theiux {" ".join(argv)} timed out locally',
                exit_code=-1,
                category='runtime_error',
                combined_output=combined,
                reason='local_timeout',
            )
        try:
            tag, line = q.get(timeout=min(remaining, 0.5))
        except queue.Empty:
            continue
        if tag is None:
            finished += 1
            continue
        assert line is not None
        yield line, 'error' if tag == 'err' else 'info'
    while True:
        try:
            tag, line = q.get_nowait()
        except queue.Empty:
            break
        if tag is None:
            continue
        if line is not None:
            yield line, 'error' if tag == 'err' else 'info'
    t_out.join(timeout=5)
    t_err.join(timeout=5)
    code = proc.wait(timeout=30)
    combined = ''.join(out_lines) + ''.join(err_lines)
    if code != 0:
        reason = 'deploy_failed'
        if code == 124:
            reason = 'ssm_timeout'
        elif code == 130:
            reason = 'ssm_cancelled'
        elif code == 2:
            reason = 'ssm_parse_or_api_error'
        if argv and argv[0] in {'bootstrap-host', 'preflight-host'}:
            cat = 'bootstrap_error'
            if argv[0] == 'bootstrap-host':
                reason = 'bootstrap_failed'
            else:
                reason = 'preflight_failed'
        else:
            cat = classify_failure_from_exit_and_output(code, combined)
        raise TheiuxDeployError(
            f'theiux {" ".join(argv)} failed (exit {code})',
            exit_code=code,
            category=cat,
            combined_output=combined,
            reason=reason,
        )


def stream_theiux_inventory_bench() -> Iterator[tuple[str, str]]:
    yield from stream_theiux_argv(['inventory-bench'])


def stream_theiux_inventory_site(domain: str) -> Iterator[tuple[str, str]]:
    d = _safe(domain)
    yield from stream_theiux_argv(['inventory-site', '--domain', d])


def stream_theiux_get_app_only(git_repo_url: str, git_branch: str | None = None) -> Iterator[tuple[str, str]]:
    yield from ensure_remote_host_ready()
    args: list[str] = ['get-app-only', '--git-repo', _validate_repo(git_repo_url)]
    if git_branch and git_branch.strip():
        args.extend(['--branch', _safe(git_branch.strip())])
    yield from stream_theiux_argv(args)


def stream_theiux_install_app_on_site(*, domain: str, app_name: str, git_repo_url: str | None) -> Iterator[tuple[str, str]]:
    d = _safe(domain)
    app = _safe(app_name)
    args = ['install-app-on-site', '--domain', d, '--app', app]
    if git_repo_url:
        args.extend(['--git-repo', _validate_repo(git_repo_url)])
    yield from stream_theiux_argv(args)


def stream_theiux_uninstall_app_from_site(*, domain: str, app_name: str) -> Iterator[tuple[str, str]]:
    d = _safe(domain)
    app = _safe(app_name)
    yield from stream_theiux_argv(['uninstall-app-from-site', '--domain', d, '--app', app])
