# Supported Platforms

[Deployments](../deployments/index.md) run on Ubuntu with Docker Compose for
development and simulation. **Platforms** are edge targets on automotive
operating systems such as AutoSD.

Open AD Kit is the first [SOAFEE](https://www.soafee.io/) blueprint, co-developed
with SOAFEE and the [eSync Alliance](https://esyncalliance.org/); DENSO's AVP
blueprint and Red Hat's AutoSD blueprint build on it.

<div class="oak-card-grid" markdown="1">

<div class="oak-card" markdown="1">

:material-server:{ .oak-card-icon }

<p class="oak-card-title" role="heading" aria-level="3">AutoSD</p>
<p>The upstream preview of Red Hat In-Vehicle OS. Containers run under Podman and systemd with mixed-criticality partitions.</p>
<a href="autosd/" class="md-button md-button--primary">AutoSD</a>
</div>

<div class="oak-card" markdown="1">

:material-cloud-outline:{ .oak-card-icon }

<p class="oak-card-title" role="heading" aria-level="3">EWAOL</p>
<p>Arm's container-centric Yocto framework and the original SOAFEE reference. Background only; not an Open AD Kit target.</p>
<a href="ewaol/" class="md-button">EWAOL</a>
</div>

</div>

## Support Matrix

A path that fails its build or validation gate is dropped or marked here, not
documented as if it worked. Individual boards are listed on the
[Hardware](hardware/index.md) page.

| Path | Tier | Notes |
|------|------|-------|
| Ubuntu 22.04 and 24.04 + Docker Compose deployments | **Committed** | Compose validated in CI; CARLA runs on 22.04 only |
| Component images, amd64 + arm64 | **Committed** | `sensing-perception-cuda` and `carla-interface` are amd64-only |
| Jazzy images | **Best-effort** | Published where the builds pass; Humble is the default |
| CARLA deployment | **Experimental** | Humble, amd64, NVIDIA GPU |
| AutoSD planning-simulator demo | **Experimental** | Uses upstream Autoware images, not the component images |
| EWAOL | **Unsupported** | No assets in this repository |

Other Linux distributions may work but are not tested.
