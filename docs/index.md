---
hide:
  - toc
---

# Open AD Kit

<p class="oak-hero-lead">
The deployment layer for the <a href="https://github.com/autowarefoundation/autoware">Autoware</a> ecosystem: packaging its software into reproducible deployments, built for the path from simulation to in-vehicle systems.
</p>

Autoware provides the autonomy stack; Open AD Kit makes it deployable. It splits
the stack along the driving pipeline into focused container images, so a
deployment runs only what its task needs, and keeps each deployment the same
from one host to the next. A [release](releases/index.md) ships the CLI, the
pinned component images and a catalog of ready-to-run
[deployments](deployments/index.md). A [kit](kits/create-a-kit.md) holds your
packages, config overrides and services on top of one of them.

It also integrates [Autoware Safety Island](https://autowarefoundation.github.io/autoware-safety-island/),
which runs on real-time operating systems and automotive hardware in a vehicle;
Safety Island Simulation runs its POSIX build in a container. Open AD Kit is not
an OTA service, a Kubernetes stack or a fork of upstream workloads, and it makes
no ASIL or NCAP certification claim.

![Planning Simulation as separate containers that talk over ROS 2](assets/images/readme-hero-light.svg#only-light)
![Planning Simulation as separate containers that talk over ROS 2](assets/images/readme-hero-dark.svg#only-dark)

## Start Here { .oak-eyebrow }

<div class="oak-card-grid oak-card-grid--start" markdown="1">

<div class="oak-card" markdown="1">

:material-rocket-launch-outline:{ .oak-card-icon }

<p class="oak-card-title" role="heading" aria-level="3">Try it locally</p>
<p>Run Planning Simulation on Ubuntu in about 10 minutes. No GPU, no build from source.</p>
<a href="getting-started/" class="md-button md-button--primary">Quickstart</a>
</div>

<div class="oak-card" markdown="1">

:material-cube-outline:{ .oak-card-icon }

<p class="oak-card-title" role="heading" aria-level="3">Run a deployment</p>
<p>Five ready-to-run simulations: planning, scenario, logging, CARLA and Safety Island.</p>
<a href="deployments/" class="md-button">Deployments</a>
</div>

<div class="oak-card" markdown="1">

:material-layers-plus:{ .oak-card-icon }

<p class="oak-card-title" role="heading" aria-level="3">Start your own kit</p>
<p>A kit holds your packages, parameters and services on top of a deployment. One CLI builds, runs and restarts it.</p>
<a href="kits/create-a-kit/" class="md-button">Create a Kit</a>
</div>

<div class="oak-card" markdown="1">

:material-server-outline:{ .oak-card-icon }

<p class="oak-card-title" role="heading" aria-level="3">Run on a platform</p>
<p>Support tiers, host requirements and boards, and AutoSD images.</p>
<a href="platforms/" class="md-button">Platforms</a>
</div>

</div>
