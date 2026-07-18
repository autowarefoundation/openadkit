# Remaining Review Findings

No verified findings remain from the July 2026 review of PR #90 in the current
worktree.

The release pipeline now resolves and records immutable upstream image inputs,
release promotion requires an exact Autoware release tag, runtime images retain
package-manager integrity, and the visualizer runs as the unprivileged `aw`
user. Deployment defaults and launchers now provide loopback-only DDS, pinned
third-party release images, verified CARLA assets and rollback, and bounded
rosbag and Zenoh readiness checks.

The previous `diagnostic_graph_aggregator` entry was removed because the pinned
Autoware source implements the availability publisher. An unavailable RViz Auto
button must be diagnosed from the published availability and diagnostic graph
state rather than bypassed with a fabricated availability message.
