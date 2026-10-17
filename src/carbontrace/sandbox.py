"""Container-only pytest execution. There is deliberately no host fallback.

The container is a security boundary; the AST policy only narrows the supported
test format. Mutation scores are a development signal, not tamper-proof grading.
"""

from __future__ import annotations

import ast
import hashlib
import os
import re
import selectors
import subprocess
import tempfile
import time
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass
from pathlib import Path
from uuid import uuid4

from carbontrace.exercise import Exercise, Mutation

MAX_CODE_BYTES = 32_768
MAX_OUTPUT_BYTES = 65_536


class SandboxError(RuntimeError):
    """Validation, runtime availability, or cleanup failure; never host execute."""


def validate_suite(code: str) -> None:
    """Reject unsupported operations before passing code to an isolated runner."""
    if len(code.encode()) > MAX_CODE_BYTES:
        raise SandboxError("Suite exceeds 32 KiB")
    try:
        tree = ast.parse(code)
    except (SyntaxError, RecursionError) as error:
        raise SandboxError("Invalid Python suite") from error
    denied = {
        "open",
        "exec",
        "eval",
        "compile",
        "input",
        "getattr",
        "setattr",
        "delattr",
        "globals",
        "locals",
        "vars",
        "breakpoint",
        "exit",
        "quit",
    }
    for node in ast.walk(tree):
        if isinstance(node, ast.Import) and any(
            alias.name not in {"pytest", "subject", "math"} for alias in node.names
        ):
            raise SandboxError("Only pytest, subject, and math imports are supported")
        if isinstance(node, ast.ImportFrom) and (
            node.level
            or node.module not in {"pytest", "subject", "math"}
            or any(
                alias.name == "*" or alias.name.startswith("_") for alias in node.names
            )
        ):
            raise SandboxError("Unsupported from-import")
        if isinstance(node, ast.Name) and (
            node.id in denied or node.id.startswith("__")
        ):
            raise SandboxError("Unsupported builtin or private name")
        if isinstance(node, ast.Attribute) and (
            node.attr.startswith("_")
            or node.attr in {"skip", "skipif", "xfail", "exit", "main"}
        ):
            raise SandboxError("Unsupported private or test-control attribute")
    if not any(isinstance(node, (ast.Assert, ast.With)) for node in ast.walk(tree)):
        raise SandboxError("Suite must contain assertions or exception checks")


def subject_source(exercise: Exercise, mutation: Mutation | None = None) -> str:
    """Bundle one trusted implementation, without revealing the other mutants."""
    if mutation is None:
        return "from __future__ import annotations\n" + exercise.source
    import inspect

    reference = ast.parse(exercise.source)
    reference_function = reference.body[0]
    assert isinstance(reference_function, ast.FunctionDef)
    reference_function.name = "_reference"
    variant = ast.parse(inspect.getsource(mutation.target))
    variant_function = variant.body[0]
    assert isinstance(variant_function, ast.FunctionDef)
    variant_function.name = exercise.function.__name__
    for node in ast.walk(variant_function):
        if isinstance(node, ast.Name) and node.id == exercise.function.__name__:
            node.id = "_reference"
    return (
        "from __future__ import annotations\n"
        + ast.unparse(reference)
        + "\n"
        + ast.unparse(variant)
        + "\n"
    )


@dataclass(frozen=True)
class Execution:
    """One independently isolated execution, including infrastructure failures."""

    status: str
    tests: int = 0
    failures: int = 0
    errors: int = 0
    skipped: int = 0
    detail: str = ""


def parse_report(report: Path, exit_code: int) -> Execution:
    """Collection errors, empty suites, and skips cannot count as fault detection."""
    if report.is_symlink() or not report.is_file() or report.stat().st_size > 1_048_576:
        return Execution("inconclusive", detail="Missing or oversized pytest report")
    data = report.read_bytes()
    if b"<!DOCTYPE" in data or b"<!ENTITY" in data:
        return Execution("inconclusive", detail="Invalid report declarations")
    try:
        root = ET.fromstring(data)
        cases = list(root.iter("testcase"))
        failures = sum(case.find("failure") is not None for case in cases)
        errors = sum(case.find("error") is not None for case in cases)
        skipped = sum(case.find("skipped") is not None for case in cases)
    except ET.ParseError:
        return Execution("inconclusive", detail="Malformed pytest report")
    status = "inconclusive"
    if cases and not errors and not skipped:
        if exit_code == 0 and failures == 0:
            status = "passed"
        elif exit_code == 1 and failures:
            status = "failed"
    return Execution(status, len(cases), failures, errors, skipped)


def collect_exit(
    process: subprocess.Popen[bytes], marker: str, timeout: float
) -> tuple[int | None, str]:
    """Read a pipe with a strict memory cap; excessive child output cannot fill disk."""
    assert process.stdout is not None
    started = time.monotonic()
    output = bytearray()
    with selectors.DefaultSelector() as selector:
        selector.register(process.stdout, selectors.EVENT_READ)
        while time.monotonic() - started < timeout:
            for key, _events in selector.select(timeout=0.05):
                chunk = os.read(key.fd, 4096)
                if not chunk:
                    return None, "Container exited before reporting completion"
                output.extend(chunk)
                if len(output) > MAX_OUTPUT_BYTES:
                    return None, "Output limit exceeded"
                match = re.search(re.escape(marker).encode() + rb"([0-9]+)\n", output)
                if match:
                    return int(match.group(1)), ""
    return None, "Wall time exceeded"


class ContainerRunner:
    """Run one suite per reference/mutant in a restricted rootless Podman container."""

    def __init__(
        self,
        image: str,
        work_root: Path,
        executable: str = "/opt/podman/bin/podman",
        timeout_seconds: float = 15,
    ) -> None:
        """Require a content-addressed local image and bounded wall time."""
        if not re.fullmatch(r"sha256:[a-f0-9]{64}", image):
            raise SandboxError("Use the full local sha256 image ID, not a mutable tag")
        if not 0.1 <= timeout_seconds <= 30:
            raise SandboxError("Wall time must be between 0.1 and 30 seconds")
        self.image = image
        self.work_root = work_root.resolve()
        self.work_root.mkdir(parents=True, exist_ok=True)
        self.timeout_seconds = timeout_seconds
        self.prefix = [executable, "--connection", "podman-machine-default"]

    def control(self, args: list[str]) -> subprocess.CompletedProcess[str]:
        """Invoke only the container CLI, using argument arrays and finite waits."""
        try:
            return subprocess.run(
                self.prefix + args,
                capture_output=True,
                text=True,
                timeout=10,
                env=os.environ.copy(),
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            raise SandboxError(
                "Container runtime unavailable; no host fallback"
            ) from error

    def preflight(self) -> None:
        """Fail closed unless rootless Podman and the exact local image are ready."""
        info = self.control(["info", "--format", "{{.Host.Security.Rootless}}"])
        if info.returncode or info.stdout.strip() != "true":
            raise SandboxError("A running rootless Podman connection is required")
        image = self.control(["image", "exists", self.image])
        if image.returncode:
            raise SandboxError("Pinned image is missing; evaluation never pulls images")

    def command(self, name: str, bundle: Path) -> list[str]:
        """Expose the complete execution boundary for tests and inspection."""
        return self.prefix + [
            "run",
            "--name",
            name,
            "--pull=never",
            "--network=none",
            "--read-only",
            "--read-only-tmpfs=false",
            "--tmpfs",
            "/tmp:rw,nosuid,nodev,size=32m",
            "--user",
            "65532:65532",
            "--cap-drop=all",
            "--security-opt=no-new-privileges",
            "--memory=256m",
            "--memory-swap=256m",
            "--cpus=1",
            "--pids-limit=64",
            "--ulimit=nofile=128:128",
            "--ulimit=fsize=1048576:1048576",
            "--log-driver=none",
            "--stop-timeout=1",
            "--hostname=carbontrace",
            "--volume",
            f"{bundle}:/work:ro",
            "--entrypoint=python",
            self.image,
            "/work/_runner.py",
        ]

    def run(self, source: str, suite: str) -> Execution:
        """Bound logs and wall time, collect JUnit, and remove our container always."""
        validate_suite(suite)
        self.preflight()
        with tempfile.TemporaryDirectory(prefix="ct-", dir=self.work_root) as temporary:
            root = Path(temporary)
            bundle = root / "bundle"
            bundle.mkdir(mode=0o755)
            for filename, code in (
                ("subject.py", source),
                ("test_candidate.py", suite),
            ):
                path = bundle / filename
                path.write_text(code)
                path.chmod(0o644)
            name = f"carbontrace-{uuid4().hex}"
            marker = f"{name}-complete="
            # Keep tmpfs alive until the host collects the report, then force-remove.
            harness = (
                "import os, time, pytest\n"
                "status = pytest.main(['-q', '--tb=short', '-p', 'no:cacheprovider', "
                "'--confcutdir=/work', '--junitxml=/tmp/report.xml', '/work/test_candidate.py'])\n"
                f"os.write(1, ('\\n{marker}' + str(int(status)) + '\\n').encode())\n"
                "while True: time.sleep(1)\n"
            )
            (bundle / "_runner.py").write_text(harness)
            (bundle / "_runner.py").chmod(0o644)
            process: subprocess.Popen[bytes] | None = None
            try:
                process = subprocess.Popen(
                    self.command(name, bundle),
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    env=os.environ.copy(),
                )
                exit_code, reason = collect_exit(process, marker, self.timeout_seconds)
                if exit_code is None:
                    return Execution("inconclusive", detail=reason)
                copied = self.control(
                    ["cp", f"{name}:/tmp/report.xml", str(root / "report.xml")]
                )
                if copied.returncode:
                    return Execution(
                        "inconclusive", detail="Container did not produce a report"
                    )
                return parse_report(root / "report.xml", exit_code)
            except OSError as error:
                raise SandboxError(
                    "Container process failed; no host fallback"
                ) from error
            finally:
                try:
                    removed = self.control(["rm", "--force", "--ignore", name])
                except SandboxError as error:
                    raise SandboxError(
                        f"Could not remove owned container {name}"
                    ) from error
                finally:
                    if process is not None:
                        if process.poll() is None:
                            process.kill()
                        process.wait(timeout=3)
                        if process.stdout is not None:
                            process.stdout.close()
                if removed.returncode:
                    raise SandboxError(f"Could not remove owned container {name}")

    def evaluate(self, exercise: Exercise, suite: str) -> dict[str, object]:
        """Accept only passing reference suites that detect all four known faults."""
        reference = self.run(subject_source(exercise), suite)
        mutations: dict[str, Execution] = {}
        if reference.status == "passed":
            for mutation in exercise.mutations:
                result = self.run(subject_source(exercise, mutation), suite)
                if result.tests != reference.tests:
                    result = Execution("inconclusive", detail="Test count changed")
                mutations[mutation.name] = result
        detected = sum(item.status == "failed" for item in mutations.values())
        return {
            "task_id": exercise.id,
            "image_id": self.image,
            "suite_sha256": hashlib.sha256(suite.encode()).hexdigest(),
            "reference": asdict(reference),
            "mutations": {name: asdict(result) for name, result in mutations.items()},
            "detected": detected,
            "total_mutations": len(exercise.mutations),
            "accepted": reference.status == "passed"
            and detected == len(exercise.mutations),
            "live_model_calls": 0,
        }
