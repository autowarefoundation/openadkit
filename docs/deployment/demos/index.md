# Demos

Demo deployments showcase **advanced use cases and distributed architectures** that go beyond single-machine simulations. They demonstrate how Open AD Kit components can be orchestrated across multiple machines, networks, and environments.

## Available Demos

<div class="oak-card-grid" markdown="1">

<div class="oak-card" markdown="1">

:material-lan-connect:{ .oak-card-icon }

<h3>Zenoh Bridge</h3>
<p>Distributed cloud-edge visualization. Run compute-intensive Autoware components on an edge server while remotely visualizing and controlling the stack from a lightweight cloud machine using Zenoh protocol bridging.</p>
<p><span class="oak-badge oak-badge--neutral">Multi-Machine</span> <span class="oak-badge oak-badge--neutral">Advanced</span></p>
<a href="zenoh-bridge/" class="md-button">Explore Zenoh Bridge Demo</a>
</div>

</div>

## Demo vs Sample

| Aspect | Samples | Demos |
|--------|---------|-------|
| **Scope** | Single workflow on one machine | Distributed architecture across machines |
| **Purpose** | Learn a specific Autoware feature | Validate production deployment patterns |
| **Complexity** | Low — run a few commands | Medium-High — network configuration, multi-machine orchestration |
| **Hardware** | Laptop or workstation | Edge server + cloud/client machine |

## Architecture Patterns

Demos illustrate real-world deployment patterns:

- **Cloud-Edge Separation** — Compute-intensive perception and planning run on vehicle or edge hardware; lightweight visualization and control run remotely
- **Network Bridging** — Zenoh bridges isolated ROS 2 domains over TCP, enabling secure cross-network communication
- **Mixed Criticality** — Safety-critical components on certified hardware, monitoring on standard platforms

## Next Steps

- [Zenoh Bridge Demo](zenoh-bridge/index.md) — Learn distributed deployment with ROS 2 bridging
- [Sample Deployments](../samples/index.md) — Start with single-machine simulations
- [Container Image Tags](../../getting-started/image-tags.md) — Choose the right image for your deployment
