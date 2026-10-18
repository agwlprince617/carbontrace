"""Apply one frozen, approved paired-comparison update using existing cloud resources.

Operations: build, build-status, deploy, verify, smoke. Smoke sends only the separately approved pair.
Every mutation has a create-only dispatch marker; failures are never retried.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import subprocess
from datetime import UTC, datetime
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "operation", choices=["build", "build-status", "deploy", "smoke", "verify"]
    )
    operation = parser.parse_args().operation
    root = Path(__file__).resolve().parents[1]
    os.chdir(root)
    plan = json.loads(Path("docs/hosted-comparison-plan.json").read_text())
    plan_hash = plan.pop("plan_sha256")
    assert (
        hashlib.sha256(
            json.dumps(plan, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        == plan_hash
    )
    approval = json.loads(Path("docs/hosted-comparison-approval.json").read_text())
    assert approval["approved"] is True and approval["plan_sha256"] == plan_hash
    assert approval["allowance_usd"] == "5.00"
    assert (
        hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
        == plan["operator_sha256"]
    )
    stage = Path(plan["prepared_directory"])
    assert {str(p.relative_to(stage)) for p in stage.rglob("*") if p.is_file()} == set(
        plan["files"]
    )
    assert all(
        hashlib.sha256((stage / name).read_bytes()).hexdigest() == digest
        for name, digest in plan["files"].items()
    )

    # Obtain cloud credentials only after exact source, operator and approval checks.
    import truststore

    truststore.inject_into_ssl()
    import google.auth
    import requests
    from google.auth.transport.requests import Request

    credentials, _ = google.auth.default(
        scopes=["https://www.googleapis.com/auth/cloud-platform"]
    )
    project, region, service = plan["project"], plan["region"], plan["service"]

    def cloud(args: list[str]) -> dict:
        if not credentials.valid:
            credentials.refresh(Request())
        env = {
            **os.environ,
            "CLOUDSDK_CONFIG": str(root / ".tmp/gcloud-live"),
            "CLOUDSDK_AUTH_ACCESS_TOKEN": credentials.token,
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
                "--format=json",
            ],
            env=env,
            capture_output=True,
            text=True,
        )
        if result.returncode:
            raise SystemExit(result.stderr.strip())
        return json.loads(result.stdout)

    def describe() -> dict:
        return cloud(["run", "services", "describe", service, "--region=" + region])

    def once(name: str) -> None:
        with Path(f".tmp/hosted-comparison-{name}-dispatch.json").open("x") as handle:
            json.dump(
                {"plan_sha256": plan_hash, "started_at": datetime.now(UTC).isoformat()},
                handle,
            )

    def public(path: str) -> dict:
        response = requests.get(plan["url"].rstrip("/") + path, timeout=45)
        response.raise_for_status()
        return response.json()

    def image_ref() -> str:
        build = json.loads(Path(".tmp/hosted-comparison-build.json").read_text())
        assert build["status"] == "SUCCESS"
        image = next(
            row
            for row in build["results"]["images"]
            if row["name"] == plan["image_tag"]
        )
        return plan["image_tag"].rsplit(":", 1)[0] + "@" + image["digest"]

    if operation == "build":
        assert (
            describe()["metadata"]["resourceVersion"]
            == plan["baseline_resource_version"]
        )
        assert (
            cloud(["billing", "projects", "describe", project])["billingEnabled"]
            is True
        )
        once("build")
        result = cloud(
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
            ]
        )
        Path(".tmp/hosted-comparison-build.json").write_text(
            json.dumps(result, indent=2)
        )
        print(json.dumps({key: result.get(key) for key in ("id", "status", "logUrl")}))
    elif operation == "build-status":
        build = json.loads(Path(".tmp/hosted-comparison-build.json").read_text())
        result = cloud(["builds", "describe", build["id"], "--region=" + region])
        Path(".tmp/hosted-comparison-build.json").write_text(
            json.dumps(result, indent=2)
        )
        print(
            json.dumps(
                {key: result.get(key) for key in ("id", "status", "failureInfo")}
            )
        )
    elif operation == "deploy":
        before = describe()
        assert (
            before["metadata"]["resourceVersion"] == plan["baseline_resource_version"]
        )
        once("deploy")
        result = cloud(
            [
                "run",
                "services",
                "update",
                service,
                "--region=" + region,
                "--image=" + image_ref(),
            ]
        )
        Path(".tmp/hosted-comparison-service.json").write_text(
            json.dumps(result, indent=2)
        )
        print(
            json.dumps(
                {
                    "revision": result["status"]["latestReadyRevisionName"],
                    "url": result["status"]["url"],
                }
            )
        )
    elif operation == "smoke":
        from decimal import Decimal

        assert (
            describe()["spec"]["template"]["spec"]["containers"][0]["image"]
            == image_ref()
        )
        assert public("/api/hosted/status")["budget_usd"] == "4"
        prepared = requests.post(
            plan["url"].rstrip("/") + "/api/hosted/quote",
            json=plan["smoke_draft"],
            timeout=45,
        )
        prepared.raise_for_status()
        signed = prepared.json()
        quote = signed["quote"]
        assert quote["prompt_sha256"] == plan["smoke_prompt_sha256"]
        assert quote["generation_calls"] == quote["token_count_calls"] == 2
        assert [row["model_id"] for row in quote["models"]] == plan["smoke_models"]
        assert Decimal(quote["reservation_usd"]) == Decimal("0.089293")
        assert quote["execution_mode"] == "hosted_model_comparison"
        Path(".tmp/hosted-comparison-smoke-quote.json").write_text(
            json.dumps(signed, indent=2)
        )
        once("smoke")
        response = requests.post(
            plan["url"].rstrip("/") + "/api/hosted/execute",
            json={
                "plan": signed,
                "approval_hash": quote["plan_sha256"],
                "allowance_usd": quote["allowance_usd"],
                "agreed": True,
            },
            timeout=180,
        )
        response.raise_for_status()
        receipt = response.json()
        evidence = {
            "provenance": "actual_hosted_pair",
            "approved_deployment_plan_sha256": plan_hash,
            "recorded_at": datetime.now(UTC).isoformat(),
            "quality": "not_evaluated",
            "generated_code_executed": False,
            "receipt": receipt,
            "budget_after": public("/api/hosted/status"),
            "result_url": plan["url"].rstrip("/") + "/?hosted=" + quote["id"],
        }
        Path("docs/hosted-comparison-live-results.json").write_text(
            json.dumps(evidence, indent=2) + "\n"
        )
        assert (
            receipt["status"] == "completed"
        ), "Comparison stopped; saved receipt preserved. Do not retry."
        assert (
            receipt["comparison"]["complete"] is True
        ), "Incomplete output; receipt preserved. Do not retry."
        print(
            json.dumps(
                {
                    "id": quote["id"],
                    "status": receipt["status"],
                    "comparison": receipt["comparison"],
                    "budget_after": evidence["budget_after"],
                    "result_url": evidence["result_url"],
                }
            )
        )
    else:
        after = describe()
        baseline = json.loads(Path(plan["baseline_file"]).read_text())
        expected = copy.deepcopy(baseline["spec"]["template"]["spec"])
        expected["containers"][0]["image"] = image_ref()
        assert (
            after["spec"]["template"]["spec"] == expected
        ), "Unexpected runtime configuration change"
        for key in ("run.googleapis.com/minScale", "run.googleapis.com/maxScale"):
            assert after["metadata"]["annotations"].get(key) == baseline["metadata"][
                "annotations"
            ].get(key)
        assert after["spec"]["template"]["metadata"].get("annotations", {}) == baseline[
            "spec"
        ]["template"]["metadata"].get("annotations", {})
        revision = after["status"]["latestReadyRevisionName"]
        assert revision != plan["baseline_revision"]
        assert any(
            row.get("revisionName") == revision and row.get("percent") == 100
            for row in after["status"]["traffic"]
        )
        status = public("/api/hosted/status")
        assert (
            status["budget_usd"] == "4" and status["expires_at"] == plan["expires_at"]
        )
        assert public("/api/health")["deployment_mode"] == "hosted-live"
        page = requests.get(plan["url"], timeout=45)
        page.raise_for_status()
        assert (
            'id="hosted-run-note"' in page.text
            and 'id="hosted-consent"' not in page.text
            and 'id="hosted-compare"' in page.text
            and 'id="hosted-comparison"' in page.text
        )
        result = {
            "verified_at": datetime.now(UTC).isoformat(),
            "plan_sha256": plan_hash,
            "revision": revision,
            "image": image_ref(),
            "url": plan["url"],
            "budget": status,
            "runtime_preserved": True,
            "builds": 1,
            "service_updates": 1,
            "agent_generation_calls": 0,
            "agent_token_count_calls": 0,
            "repository_push": False,
            "submission_upload": False,
        }
        Path("docs/hosted-comparison-result.json").write_text(
            json.dumps(result, indent=2) + "\n"
        )
        print(json.dumps(result))


if __name__ == "__main__":
    main()
