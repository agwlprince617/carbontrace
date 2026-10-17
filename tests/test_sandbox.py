"""Fail-closed runner checks and opt-in tests against real local containers."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from carbontrace.benchmarks import EXERCISES
from carbontrace.quality import render_suite
from carbontrace.sandbox import (
    ContainerRunner,
    Execution,
    SandboxError,
    collect_exit,
    parse_report,
    subject_source,
    validate_suite,
)

IMAGE = os.environ.get(
    "CARBONTRACE_SANDBOX_IMAGE",
    "sha256:af50fdb931d09782d5a8aee70ccbaa5856e8661c4af09c64279fc59213cab021",
)


@pytest.mark.parametrize(
    "script, expected",
    [
        ("print('owned-complete=0', flush=True)", (0, "")),
        ("print('x' * 100000, flush=True)", (None, "Output limit exceeded")),
        ("pass", (None, "Container exited before reporting completion")),
        ("import time; time.sleep(5)", (None, "Wall time exceeded")),
    ],
)
def test_output_collection_is_bounded(
    script: str, expected: tuple[int | None, str]
) -> None:
    """Use only first-party subprocess probes to test capped pipe reads and timeout."""
    process = subprocess.Popen([sys.executable, "-c", script], stdout=subprocess.PIPE)
    try:
        assert collect_exit(process, "owned-complete=", 0.5) == expected
    finally:
        if process.poll() is None:
            process.kill()
        process.wait(timeout=2)
        assert process.stdout is not None
        process.stdout.close()


@pytest.mark.parametrize(
    "code",
    [
        "import os\nassert True",
        "from os import system\nassert True",
        "from .subject import x\nassert True",
        "from pytest import *\nassert True",
        "from subject import _reference\nassert True",
        "assert subject.__dict__",
        "assert eval('1')",
        "assert __import__('os')",
        "assert pytest.skip('x')",
        "def test_invalid(",
        "pass",
        "#" * 32769,
    ],
)
def test_unsupported_input_never_reaches_execution(code: str) -> None:
    """AST checks reject common I/O, introspection, and test-control constructs."""
    with pytest.raises(SandboxError):
        validate_suite(code)


def test_report_errors_skips_empty_and_invalid_xml_cannot_pass(tmp_path: Path) -> None:
    """Only actual assertion failures with pytest exit 1 count as detection."""
    report = tmp_path / "report.xml"
    assert parse_report(report, 0).status == "inconclusive"
    for xml, code, status in [
        ("<testsuites><testcase/></testsuites>", 0, "passed"),
        ("<testsuites><testcase><failure/></testcase></testsuites>", 1, "failed"),
        ("<testsuites><testcase><failure/></testcase></testsuites>", 2, "inconclusive"),
        ("<testsuites><testcase><error/></testcase></testsuites>", 1, "inconclusive"),
        ("<testsuites><testcase><skipped/></testcase></testsuites>", 0, "inconclusive"),
        ("<testsuites/>", 5, "inconclusive"),
        ("broken", 0, "inconclusive"),
        ("<!DOCTYPE x><testsuites/>", 0, "inconclusive"),
    ]:
        report.write_text(xml)
        assert parse_report(report, code).status == status
    report.write_bytes(b"x" * 1_048_577)
    assert parse_report(report, 0).status == "inconclusive"


def test_configuration_and_runtime_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No mutable image tag, rootful runtime, missing image, or missing CLI is accepted."""
    with pytest.raises(SandboxError):
        ContainerRunner("python:latest", tmp_path)
    with pytest.raises(SandboxError):
        ContainerRunner(IMAGE, tmp_path, timeout_seconds=100)
    runner = ContainerRunner(
        IMAGE, tmp_path, executable="/nonexistent/carbontrace-podman"
    )
    with pytest.raises(SandboxError):
        runner.preflight()
    runner = ContainerRunner(IMAGE, tmp_path)
    monkeypatch.setattr(
        runner, "control", lambda _args: subprocess.CompletedProcess([], 0, "false", "")
    )
    with pytest.raises(SandboxError):
        runner.preflight()
    monkeypatch.setattr(
        runner,
        "control",
        lambda args: subprocess.CompletedProcess(
            [], 0 if args[0] == "info" else 1, "true", ""
        ),
    )
    with pytest.raises(SandboxError):
        runner.preflight()
    command = runner.command("owned-name", tmp_path)
    for option in (
        "--pull=never",
        "--network=none",
        "--read-only",
        "--memory=256m",
        "--cpus=1",
        "--pids-limit=64",
        "--cap-drop=all",
        "--security-opt=no-new-privileges",
    ):
        assert option in command
    assert f"{tmp_path}:/work:ro" in command


def test_changed_collection_is_not_a_detected_mutant(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A mutant that changes the test count remains inconclusive."""
    runner = ContainerRunner(IMAGE, tmp_path)
    results = iter([Execution("passed", tests=2)] + [Execution("failed", tests=1)] * 4)
    monkeypatch.setattr(runner, "run", lambda *_args: next(results))
    result = runner.evaluate(EXERCISES["clamp"], "assert True")
    assert result["detected"] == 0
    assert result["accepted"] is False


@pytest.mark.parametrize("cleanup", ["success", "failed", "unavailable"])
def test_process_start_failure_and_cleanup_are_explicit(
    cleanup: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A missing process or failed cleanup cannot trigger host execution or success."""
    runner = ContainerRunner(IMAGE, tmp_path)
    monkeypatch.setattr(runner, "preflight", lambda: None)

    def control(_args: list[str]) -> subprocess.CompletedProcess[str]:
        """Simulate only cleanup responses; never run candidate code on the host."""
        if cleanup == "unavailable":
            raise SandboxError("Runtime unavailable")
        return subprocess.CompletedProcess([], int(cleanup == "failed"), "", "")

    def unavailable(*_args: object, **_kwargs: object) -> None:
        """Simulate inability to spawn the runtime client."""
        raise OSError("Missing runtime")

    monkeypatch.setattr(runner, "control", control)
    monkeypatch.setattr(subprocess, "Popen", unavailable)
    with pytest.raises(
        SandboxError,
        match=(
            "Container process failed"
            if cleanup == "success"
            else "Could not remove owned container"
        ),
    ):
        runner.run(subject_source(EXERCISES["clamp"]), render_suite("clamp", "strong"))


container = pytest.mark.skipif(
    os.environ.get("CARBONTRACE_CONTAINER_TESTS") != "1",
    reason="Opt in only with prepared rootless Podman and a pinned local image",
)


@container
@pytest.mark.parametrize("task", list(EXERCISES))
def test_actual_isolated_reference_and_mutants(task: str, tmp_path: Path) -> None:
    """Verify every transformed implementation in five separate containers."""
    runner = ContainerRunner(
        os.environ.get("CARBONTRACE_SANDBOX_IMAGE", IMAGE), tmp_path
    )
    result = runner.evaluate(EXERCISES[task], render_suite(task, "strong"))
    assert result["accepted"], result
    assert result["detected"] == 4


@container
def test_actual_empty_collection_error_timeout_and_weak_suite(tmp_path: Path) -> None:
    """Real errors and timeouts fail closed; surviving mutants do not get credit."""
    runner = ContainerRunner(IMAGE, tmp_path)
    source = subject_source(EXERCISES["clamp"])
    assert runner.run(source, "assert True").status == "inconclusive"
    assert (
        runner.run(source, "from subject import missing\nassert True").status
        == "inconclusive"
    )
    assert (
        runner.evaluate(EXERCISES["merge"], render_suite("merge", "compact"))[
            "detected"
        ]
        == 0
    )
    runner.timeout_seconds = 1
    timed = runner.run(
        source, "def test_forever():\n    assert True\n    while True: pass\n"
    )
    assert timed.status == "inconclusive" and timed.detail == "Wall time exceeded"


@container
def test_actual_container_restrictions(tmp_path: Path) -> None:
    """An owned probe checks the effective user, filesystem, network, and cgroups."""
    source = """def probe():
    import os, socket
    from pathlib import Path
    readonly = False
    try:
        Path('/work/forbidden').write_text('blocked')
    except OSError:
        readonly = True
    network_blocked = False
    try:
        socket.create_connection(('1.1.1.1', 53), timeout=0.2)
    except OSError:
        network_blocked = True
    status = Path('/proc/self/status').read_text()
    return [os.getuid(), readonly, network_blocked,
        'NoNewPrivs:\\t1' in status, 'CapEff:\\t0000000000000000' in status,
        Path('/sys/fs/cgroup/memory.max').read_text().strip(),
        Path('/sys/fs/cgroup/pids.max').read_text().strip()]
"""
    suite = "from subject import probe\ndef test_controls():\n    assert probe() == [65532, True, True, True, True, '268435456', '64']\n"
    result = ContainerRunner(IMAGE, tmp_path).run(source, suite)
    assert result.status == "passed", result
