# EWAOL

!!! abstract ""
    EWAOL is a standards-based, container-centric framework for deploying and orchestrating edge workloads. It was the original SOAFEE reference implementation, extending cloud-native methods to automotive with an emphasis on real-time execution and deterministic behavior.

## Status

<span class="oak-badge oak-badge--neutral">Upstream reference</span>

!!! note "Not a committed Open AD Kit target"
    EWAOL is retained as upstream SOAFEE background. Open AD Kit's committed SOAFEE-aligned target is the **Arm Automotive Solutions reference stack / RD-1 AE FVP**. EWAOL-specific deployment assets are **not yet present** in this repository; this page is a pointer to the upstream project, not a validated Open AD Kit deployment path.

## What is EWAOL?

EWAOL is delivered via the `meta-ewaol` Yocto layer and provides a container-native edge runtime (Docker and K3s, with optional Xen virtualization for mixed-criticality separation). It offers runtime parity between edge hardware (ADLINK AVA with Arm Neoverse N1) and cloud instances (AWS Graviton), making it suited to hybrid development and deployment workflows.

## Documentation

For installation and runtime instructions, see the upstream documentation:

- [EWAOL User Guide](https://ewaol.docs.arm.com/en/kirkstone-dev/user_guide/reproduce.html)

## Related

- [Supported Platforms overview](../index.md)
- [AutoSD platform](../autosd/index.md)
