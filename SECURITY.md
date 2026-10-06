# Security policy

## Reporting a vulnerability

Use GitHub's [private vulnerability report form](https://github.com/autowarefoundation/openadkit/security/advisories/new)
for suspected vulnerabilities in Open AD Kit. Reports are handled privately by
the repository's authorized maintainers. **Do not disclose exploit details in
public issues, pull requests or Discord.**

Include:

- Affected Open AD Kit version or source commit, image digest, deployment,
  ROS distro and host architecture
- Impact and the conditions required to exploit the issue
- Reproduction steps or a minimal proof of concept
- Any known mitigation; omit credentials, personal data and vehicle secrets

Maintainers assess the report, coordinate fixes and upstream notifications,
and agree on disclosure with the reporter. Confirmed issues can be published
as GitHub Security Advisories after coordination. This is community-maintained
software; no response-time or remediation SLA is promised.

Repository administrators and security managers should subscribe to the
repository's **Security alerts** notifications and monitor private reports.
Enabling the reporting form alone does not establish an incident-response team.

## Supported versions

The latest stable release receives security fixes in a new release. Older
releases are not patched separately. Until the first stable release, source
checkouts and release candidates are development previews. See [SUPPORT.md](SUPPORT.md).

Vulnerabilities in Autoware, ROS, simulators or other upstream dependencies
should also be coordinated with their maintainers. Report the affected Open
AD Kit image digest here when our packaging or configuration is involved.

## Security boundaries

Digest pins, vulnerability scans and signed provenance improve traceability;
they do not prove that software is vulnerability-free or safe for a vehicle.
Test Result attestations are runtime test claims, not security certification.

Run only trusted kits and images: a kit can launch additional containers and
load custom code. Host networking and mounted host directories are not a
sandbox against malicious workloads. Keep Zenoh and remote-access ports on
trusted networks, restrict access, and never commit credentials or include
them in release artifacts. Integrators own the security of their custom
layers and operational environment.
