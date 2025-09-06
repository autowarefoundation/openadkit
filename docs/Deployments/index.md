# Deployment

## Zenoh-bridge

The `zenoh-bridge` provides the communication backbone for the OpenADKit's distributed architecture. It demonstrates a "Cloud-Edge" deployment model by seamlessly bridging two isolated ROS 2 environments, decoupling compute-intensive components from lightweight visualization tools.

In this model, the core `autoware` stack runs on an **edge device** (e.g., a vehicle or server), while the `visualizer` can be accessed remotely from a user's machine (the **cloud side**).
