"""Enforce release policy on *successfully verified* gh attestation output.

This does not verify signatures. The caller must first use gh attestation verify
with the repository, trusted signer workflow, predicate type and source ref.
One complete PASSED statement must cover this exact build; statements are never
unioned to fill missing subjects or cells. Quarantine is not a release bypass.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import validation_matrix  # noqa: E402
from evidence.subjects import build_subjects  # noqa: E402

PREDICATE_TYPE = "https://in-toto.io/attestation/test-result/v0.1"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def expected_cells(source_root: Path) -> dict[str, dict[str, str]]:
    runtime = validation_matrix.load_runtime(source_root)
    matrix = validation_matrix.evidence_cells(runtime, source_root)
    matrix.extend(validation_matrix.example_kit_cells(runtime, source_root))
    cells = {validation_matrix.evidence_cell_name(cell): cell for cell in matrix}
    require(bool(cells), "release has no required evidence cells")
    require(len(cells) == len(matrix), "duplicate required evidence cell names")
    return cells


def statement_report(
    statement: dict[str, Any], metadata: dict[str, Any], source_root: Path,
    default_distro: str, repository: str,
) -> dict[str, Any]:
    require(isinstance(statement, dict), "invalid statement")
    require(statement.get("_type") == "https://in-toto.io/Statement/v1", "invalid statement type")
    require(statement.get("predicateType") == PREDICATE_TYPE, "wrong predicate type")
    subjects = statement.get("subject")
    if not isinstance(subjects, list) or not subjects:
        raise ValueError("missing attested subjects")
    actual_subjects = []
    for subject in subjects:
        require(isinstance(subject, dict), "invalid subject")
        digest = subject.get("digest")
        require(isinstance(digest, dict), "invalid subject digest")
        actual_subjects.append((digest.get("sha256"), subject.get("name")))
    # Comparing lists also rejects duplicate subjects, not just missing subjects.
    expected_subjects = build_subjects(metadata, source_root)
    require(
        sorted(actual_subjects, key=lambda pair: str(pair[1])) == expected_subjects,
        "attested subjects differ from the release build/source",
    )

    predicate = statement.get("predicate")
    if not isinstance(predicate, dict):
        raise ValueError("missing Test Result predicate")
    require(predicate.get("result") == "PASSED", f"evidence result is {predicate.get('result', 'UNKNOWN')}; release requires PASSED")
    require(predicate.get("failedTests") == [], "failedTests must be empty")
    require(predicate.get("warnedTests") == [], "warnedTests must be empty; quarantine cannot bypass release policy")
    expected = expected_cells(source_root)
    passed = predicate.get("passedTests")
    if not isinstance(passed, list) or not all(isinstance(name, str) for name in passed):
        raise ValueError("invalid passedTests")
    require(sorted(passed) == sorted(expected), "passedTests do not cover exactly the required cells")
    configuration = predicate.get("configuration")
    if not isinstance(configuration, list):
        raise ValueError("missing cell configuration")
    names: list[str] = []
    for cell in configuration:
        if not isinstance(cell, dict) or not isinstance(cell.get("name"), str):
            raise ValueError("invalid cell identity")
        names.append(cell["name"])
    require(sorted(names) == sorted(expected), "configuration does not cover exactly the required cells")

    runtime = validation_matrix.load_runtime(source_root)
    kit = runtime.load_kit(source_root)
    require(default_distro == kit.default_ros_distro, "default distro must match the release source manifest")
    require(any(cell["distro"] == default_distro for cell in expected.values()), "default distro has no required runtime evidence")
    cells = []
    for cell in sorted(configuration, key=lambda item: item["name"]):
        row = expected[cell["name"]]
        annotations = cell.get("annotations")
        require(isinstance(annotations, dict), f"{cell['name']}: missing annotations")
        identity = {
            "deployment": row["deployment"], "rosDistro": row["distro"],
            "node": row.get("node") or None, "platform": "linux/amd64",
            "kit": row.get("kit") or None,
            "buildTag": metadata["build_tag"], "sourceSha": metadata["openadkit_sha"],
        }
        require(all(annotations.get(key) == value for key, value in identity.items()), f"{cell['name']}: cell does not match the build/matrix")
        levels = annotations.get("levels")
        require(isinstance(levels, dict) and all(levels.get(level) is True for level in ("L0", "L1", "L2")), f"{cell['name']}: L0-L2 must all pass")
        if row.get("kit"):
            require(annotations.get("overlayConformant") is True, f"{cell['name']}: example overlay must conform")
        cells.append({
            "name": cell["name"], "deployment": row["deployment"],
            "distro": row["distro"], "node": row.get("node") or "",
            "kit": row.get("kit") or "", "platform": "linux/amd64", "result": "PASSED",
            "levels": levels, "overlayConformant": annotations.get("overlayConformant"),
            "ready_s": annotations.get("readyS"), "arrival_s": annotations.get("arrivalS"),
            "peak_mib": annotations.get("peakMib"),
        })
    canonical = json.dumps(statement, sort_keys=True, separators=(",", ":")).encode()
    return {
        "schemaVersion": 1, "result": "PASSED", "build_tag": metadata["build_tag"],
        "source_sha": metadata["openadkit_sha"], "predicateType": PREDICATE_TYPE,
        "signerWorkflow": f"{repository}/.github/workflows/evidence.yaml",
        "sourceRef": "refs/heads/main", "url": predicate.get("url"),
        "statementSha256": hashlib.sha256(canonical).hexdigest(),
        "defaultRosDistroDecision": {
            "selected": default_distro, "source": "openadkit.json",
            "policy": "explicit-manifest-with-passing-evidence",
        },
        "exempt": validation_matrix.evidence_exemptions(runtime, source_root),
        "cells": cells, "statement": statement,
    }


def verified_report(
    verified: Any, metadata: dict[str, Any], source_root: Path,
    default_distro: str, repository: str,
) -> dict[str, Any]:
    require(isinstance(verified, list) and bool(verified), "no verified evidence statements")
    problems = []
    for entry in verified:
        try:
            statement = entry["verificationResult"]["statement"]
            return statement_report(statement, metadata, source_root, default_distro, repository)
        except (ValueError, KeyError, TypeError) as error:
            problems.append(str(error))
    raise ValueError("no complete PASSED evidence statement for this release: " + "; ".join(problems))


def validate_report(report: dict[str, Any], metadata: dict[str, Any], source_root: Path, default_distro: str) -> None:
    """Recheck the validated input before embedding it in an immutable plan."""
    signer = report.get("signerWorkflow", "")
    require(isinstance(signer, str) and signer.endswith("/.github/workflows/evidence.yaml"), "invalid evidence signer")
    repository = signer.removesuffix("/.github/workflows/evidence.yaml")
    require(bool(repository), "missing evidence repository")
    expected = statement_report(report.get("statement", {}), metadata, source_root, default_distro, repository)
    require(report == expected, "evidence report differs from its validated statement/source")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verified", type=Path, required=True)
    parser.add_argument("--build-metadata", type=Path, required=True)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--default-ros-distro", required=True)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        report = verified_report(
            json.loads(args.verified.read_text()), json.loads(args.build_metadata.read_text()),
            args.source_root.resolve(), args.default_ros_distro, args.repository,
        )
        args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    except (OSError, ValueError, KeyError, TypeError) as error:
        parser.exit(1, f"evidence gate: {error}\n")
    print(f"evidence gate: PASSED ({len(report['cells'])} required cells)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
