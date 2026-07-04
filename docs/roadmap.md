# Roadmap

Open AD Kit matures in stages. We start with a trustworthy foundation and layer on validation, security, and automation until the full pipeline is proven end to end.

```mermaid
flowchart LR
    subgraph "2026"
        v20["v2.0.0<br/>Jul 2026"]
        v21["v2.1.0<br/>Sep 2026"]
        v22["v2.2.0<br/>Oct 2026"]
        v23["v2.3.0<br/>Nov 2026"]
    end
    subgraph "2027"
        ces["CES 2027<br/>Jan 6–9"]
        v24["v2.4.0<br/>Late Jan–Feb"]
        v25["v2.5.0<br/>Mar 2027"]
        v30["v3.0.0<br/>May 2027"]
    end
    v20 --> v21 --> v22 --> v23 --> ces --> v24 --> v25 --> v30
```

## Release ladder

| Release | Target | Scope |
| :--- | :--- | :--- |
| **v2.0.0** | Jul 2026 | **Trustworthy release**<br>Pinned images, scans, bundles, compose validation, CARLA 0.9.16 |
| **v2.1.0** | Sep 2026 | **Compatibility MVP**<br>Lockfiles, manifests, validation, platform matrix |
| **v2.2.0** | Oct 2026 | **Readiness + gating**<br>Scenario V2 CI gate, health readiness, restart path |
| **v2.3.0** | Nov 2026 | **Trust signals**<br>SBOM, provenance, cosign signing, vulnerability policy |
| **CES 2027** | Jan 6–9 | **Flagship demo**<br>VisionPilot + Safety Island + CARLA (event, not a release gate) |
| **v2.4.0** | Late Jan–Feb | **Platform profiles**<br>AutoSD/Podman, BlueChi, Zenoh split, S-Core analysis |
| **v2.5.0** | Mar 2027 | **Update/rollback beta**<br>Staged apply, health promotion, verified rollback |
| **v3.0.0** | May 2027 | **Closed loop**<br>Build → deploy → test → observe → update → rollback |

## See also

- [Getting Started](getting-started/index.md) — Set up your environment
- [Development](development/index.md) — Build from source and contribute
- [Releases](releases/index.md) — Current release status
