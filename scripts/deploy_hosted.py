"""Execute only the separately approved, frozen hosted-demo deployment plan.

No command runs at import. Use setup, build, build-status, deploy, then verify.
Approval and source hashes are checked before obtaining cloud credentials. Each
build/deploy dispatch has a local one-shot receipt; errors never trigger a retry.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import secrets
import subprocess
import tempfile
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "operation", choices=["setup", "build", "build-status", "deploy", "verify"]
    )
    operation = parser.parse_args().operation
    root = Path(__file__).resolve().parents[1]
    os.chdir(root)
    plan = json.loads(Path("docs/hosted-deployment-plan.json").read_text())
    plan_hash = plan.pop("plan_sha256")
    assert (
        hashlib.sha256(
            json.dumps(plan, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        == plan_hash
    )
    approval = json.loads(Path("docs/hosted-deployment-approval.json").read_text())
    assert approval["plan_sha256"] == plan_hash and approval["approved"] is True
    assert (
        hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
        == plan["operator_sha256"]
    )
    stage = Path(plan["prepared_directory"])
    assert all(
        hashlib.sha256((stage / name).read_bytes()).hexdigest() == value
        for name, value in plan["files"].items()
    )
    assert {
        str(path.relative_to(stage)) for path in stage.rglob("*") if path.is_file()
    } == set(plan["files"])

    import truststore

    truststore.inject_into_ssl()
    import google.auth
    from google.auth.transport.requests import AuthorizedSession, Request

    credentials, _ = google.auth.default(
        scopes=["https://www.googleapis.com/auth/cloud-platform"]
    )
    project, region, service = plan["project"], plan["region"], plan["service"]
    runtime, bucket, secret = (
        plan["runtime_service_account"],
        plan["ledger_bucket"],
        plan["signing_secret"],
    )
    role = f"projects/{project}/roles/carbontraceDemoPredict"
    cli_config = root / ".tmp/gcloud-live"
    cli_config.mkdir(exist_ok=True)

    def cloud(args: list[str]) -> str:
        if not credentials.valid:
            credentials.refresh(Request())
        env = {
            **os.environ,
            "CLOUDSDK_CONFIG": str(cli_config),
            "CLOUDSDK_AUTH_ACCESS_TOKEN": credentials.token,
            "CLOUDSDK_CORE_PROJECT": project,
            "CLOUDSDK_CORE_DISABLE_PROMPTS": "1",
            "CLOUDSDK_COMPONENT_MANAGER_DISABLE_UPDATE_CHECK": "1",
            "CLOUDSDK_PYTHON": str(root / ".venv/bin/python"),
            "CLOUDSDK_PYTHON_SITEPACKAGES": "1",
            "PYTHONPATH": str(root / ".tmp/gcloud-python"),
            "TMPDIR": str(root / ".tmp"),
        }
        result = subprocess.run(
            [
                str(root / ".tools/google-cloud-sdk/bin/gcloud"),
                *args,
                "--project=" + project,
                "--quiet",
            ],
            env=env,
            capture_output=True,
            text=True,
        )
        if result.returncode:
            raise SystemExit(result.stderr.strip())
        return result.stdout

    def once(name: str) -> Path:
        path = root / f".tmp/hosted-{name}.json"
        with path.open("x") as handle:
            json.dump({"status": "dispatching", "plan_sha256": plan_hash}, handle)
        return path

    if operation == "setup":
        receipt = once("setup")
        billing = json.loads(
            cloud(["billing", "projects", "describe", project, "--format=json"])
        )
        assert billing["billingEnabled"] is True
        existing = json.loads(
            cloud(
                [
                    "run",
                    "services",
                    "describe",
                    service,
                    "--region=" + region,
                    "--format=json",
                ]
            )
        )
        assert (
            existing["status"]["latestReadyRevisionName"] == plan["previous_revision"]
        )
        cloud(["services", "enable", "secretmanager.googleapis.com"])
        # This identity can invoke models, but cannot provision or administer them.
        cloud(
            [
                "iam",
                "roles",
                "create",
                "carbontraceDemoPredict",
                "--title=CarbonTrace demo inference",
                "--permissions=aiplatform.endpoints.predict",
                "--stage=GA",
            ]
        )
        cloud(
            [
                "projects",
                "add-iam-policy-binding",
                project,
                "--member=serviceAccount:" + runtime,
                "--role=" + role,
                "--condition=None",
            ]
        )
        cloud(
            [
                "storage",
                "buckets",
                "create",
                "gs://" + bucket,
                "--location=" + region,
                "--uniform-bucket-level-access",
                "--public-access-prevention",
                "--soft-delete-duration=0",
            ]
        )
        lifecycle = root / ".tmp/hosted-lifecycle.json"
        lifecycle.write_text(
            json.dumps(
                {
                    "rule": [
                        {
                            "action": {"type": "Delete"},
                            "condition": {"age": 7, "matchesPrefix": ["runs/"]},
                        }
                    ]
                }
            )
        )
        cloud(
            [
                "storage",
                "buckets",
                "update",
                "gs://" + bucket,
                "--lifecycle-file=" + str(lifecycle),
            ]
        )
        cloud(
            [
                "storage",
                "buckets",
                "add-iam-policy-binding",
                "gs://" + bucket,
                "--member=serviceAccount:" + runtime,
                "--role=roles/storage.objectUser",
            ]
        )
        # Seed once as operator. The runtime refuses to recreate a missing meter.
        session = AuthorizedSession(credentials)
        response = session.put(
            "https://storage.googleapis.com/"
            + bucket
            + "/budget/"
            + plan["pool_epoch"]
            + ".json",
            data=json.dumps(
                {"epoch": plan["pool_epoch"], "limit": 6, "runs": {}}
            ).encode(),
            headers={
                "Content-Type": "application/json",
                "x-goog-if-generation-match": "0",
            },
            timeout=30,
            allow_redirects=False,
        )
        assert response.status_code in (200, 201), "Meter initialization failed; stop"
        cloud(["secrets", "create", secret, "--replication-policy=automatic"])
        # The signing key never enters command arguments, build context or receipts.
        with tempfile.NamedTemporaryFile(dir=root / ".tmp") as handle:
            handle.write(secrets.token_hex(32).encode())
            handle.flush()
            cloud(["secrets", "versions", "add", secret, "--data-file=" + handle.name])
        cloud(
            [
                "secrets",
                "add-iam-policy-binding",
                secret,
                "--member=serviceAccount:" + runtime,
                "--role=roles/secretmanager.secretAccessor",
            ]
        )
        receipt.write_text(json.dumps({"status": "ready", "plan_sha256": plan_hash}))
        print(
            "Private storage, fixed six-run meter, signing secret and scoped IAM are ready."
        )
    elif operation == "build":
        assert (
            json.loads(Path(".tmp/hosted-setup.json").read_text())["status"] == "ready"
        )
        receipt = once("build")
        result = json.loads(
            cloud(
                [
                    "builds",
                    "submit",
                    str(stage),
                    "--region=" + region,
                    "--config=" + str(stage / "cloudbuild.yaml"),
                    "--service-account=projects/"
                    + project
                    + "/serviceAccounts/"
                    + plan["build_service_account"],
                    "--gcs-source-staging-dir=gs://carbontrace-511814-build-source/source",
                    "--substitutions=_IMAGE=" + plan["image_tag"],
                    "--async",
                    "--format=json",
                ]
            )
        )
        receipt.write_text(json.dumps(result, indent=2))
        print(json.dumps({key: result.get(key) for key in ("id", "status", "logUrl")}))
    elif operation == "build-status":
        receipt = Path(".tmp/hosted-build.json")
        build = json.loads(receipt.read_text())
        result = json.loads(
            cloud(
                [
                    "builds",
                    "describe",
                    build["id"],
                    "--region=" + region,
                    "--format=json",
                ]
            )
        )
        receipt.write_text(json.dumps(result, indent=2))
        print(
            json.dumps(
                {key: result.get(key) for key in ("id", "status", "failureInfo")}
            )
        )
    elif operation == "deploy":
        build = json.loads(Path(".tmp/hosted-build.json").read_text())
        assert build["status"] == "SUCCESS"
        image = next(
            row
            for row in build["results"]["images"]
            if row["name"] == plan["image_tag"]
        )
        image_ref = plan["image_tag"].rsplit(":", 1)[0] + "@" + image["digest"]
        receipt = once("service")
        result = json.loads(
            cloud(
                [
                    "run",
                    "deploy",
                    service,
                    "--image=" + image_ref,
                    "--region=" + region,
                    "--service-account=" + runtime,
                    "--port=8080",
                    "--cpu=1",
                    "--memory=512Mi",
                    "--min=0",
                    "--max=1",
                    "--concurrency=16",
                    "--timeout=180s",
                    "--cpu-throttling",
                    "--no-cpu-boost",
                    "--allow-unauthenticated",
                    "--set-env-vars=CARBONTRACE_MODE=hosted-live,CARBONTRACE_LEDGER_BUCKET="
                    + bucket
                    + ",CARBONTRACE_POOL_EXPIRES="
                    + plan["pool_expires_at"],
                    "--set-secrets=CARBONTRACE_QUOTE_KEY=" + secret + ":1",
                    "--format=json",
                ]
            )
        )
        receipt.write_text(json.dumps(result, indent=2))
        print(
            json.dumps(
                {
                    "url": result["status"]["url"],
                    "revision": result["status"]["latestReadyRevisionName"],
                }
            )
        )
    else:
        result = json.loads(
            cloud(
                [
                    "run",
                    "services",
                    "describe",
                    service,
                    "--region=" + region,
                    "--format=json",
                ]
            )
        )
        policy = json.loads(
            cloud(["projects", "get-iam-policy", project, "--format=json"])
        )
        roles = [
            row["role"]
            for row in policy.get("bindings", [])
            if "serviceAccount:" + runtime in row.get("members", [])
        ]
        assert roles == [role], "Unexpected runtime project roles"
        custom = json.loads(
            cloud(
                ["iam", "roles", "describe", "carbontraceDemoPredict", "--format=json"]
            )
        )
        assert custom["includedPermissions"] == ["aiplatform.endpoints.predict"]
        bucket_config = json.loads(
            cloud(["storage", "buckets", "describe", "gs://" + bucket, "--format=json"])
        )
        Path(".tmp/hosted-verified.json").write_text(
            json.dumps(
                {"service": result, "bucket": bucket_config, "project_roles": roles},
                indent=2,
            )
        )
        print(
            "Runtime role verified; service and bucket configuration saved privately for inspection."
        )


if __name__ == "__main__":
    main()
