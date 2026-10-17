# Local generated-test execution boundary

Generated Python must use the CLI container runner. The web app still evaluates
only owned literal fixtures and exposes no arbitrary-code upload endpoint.

The runner requires the existing **rootless** `podman-machine-default` connection
and a complete `sha256:` image ID. It fails closed when the VM/image is missing;
it never starts a VM, pulls an image, installs packages, or falls back to host
Python during evaluation. Container construction is a separate, explicit step.

Each reference/mutant run has a new container with no network, a read-only root
filesystem, UID/GID 65532, all capabilities dropped, no-new-privileges, 256 MiB
memory with no additional swap, one CPU, 64 processes, and bounded file sizes.
Only a temporary bundle (one implementation, candidate suite, trusted pytest
launcher) is mounted, read-only. Writable storage is a 32 MiB tmpfs. No provider
credentials, project directory, container socket, ports, or host home directory
are mounted. Default wall time is 15 seconds and captured output is bounded.

The trusted launcher keeps the container alive briefly so the host can copy the
JUnit report out of tmpfs. The runner force-removes its uniquely named container
on completion/error/timeout. A cleanup failure raises an explicit error. It never
prunes other containers, images, volumes, or user data.

The AST check supports only pytest, subject, and math imports and rejects common
I/O/introspection/test-control operations. **This static filter is not a Python
security sandbox.** The rootless Linux container inside Podman's VM provides the
execution boundary. Containers still share a kernel and require an updated
runtime; this is a local hackathon runner, not public multi-tenant hosting.

JUnit and exit status distinguish assertion failures from collection failures,
empty suites, skipped tests, and infrastructure errors. The generated suite
shares the pytest process and could deliberately tamper with grading. Scores are
not adversarially secure. Keep this limitation when interpreting benchmark data.

## Prepare once

The current environment uses `/opt/podman/bin/podman`. Start the VM with Podman
Desktop, then from the project directory:

```sh
mkdir -p .tmp .runtime
export TMPDIR="$PWD/.tmp"
export XDG_RUNTIME_DIR="$PWD/.runtime"
/opt/podman/bin/podman --connection podman-machine-default build \
  --tag localhost/carbontrace-runner:0.2 --file sandbox/Containerfile sandbox
/opt/podman/bin/podman --connection podman-machine-default image inspect \
  localhost/carbontrace-runner:0.2 --format '{{.Id}}'
```

Building downloads the official Python image and pytest; it makes no inference
calls and creates no Google Cloud resources. The base image tag is mutable, so
record the resolved base digest and final image ID for each evaluation environment.
Evaluation accepts only the full local image ID and never implicitly pulls.

## Evaluate a suite

```sh
.venv/bin/python -m carbontrace.benchmark evaluate \
  --task clamp --suite path/to/test_candidate.py \
  --image sha256:FULL_LOCAL_IMAGE_ID --output data/suite-result.json
```

Use `--include-holdout` only after locking the final protocol. This flag is a local
dataset-access decision; it does not enable live inference or authorize spending.

Run the opt-in integration checks after preparing the image:

```sh
CARBONTRACE_CONTAINER_TESTS=1 .venv/bin/pytest --cov=carbontrace \
  --basetemp=.tmp/pytest-container
```

The tests use the recorded image ID for this machine. For another image, set
`CARBONTRACE_SANDBOX_IMAGE` to its full ID. Controls are based on the official
[Podman run documentation](https://docs.podman.io/en/latest/markdown/podman-run.1.html).
