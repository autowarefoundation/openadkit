# Open AD Kit: Remote Simulation

- **autoware**: Autoware container for development and deployment.
- **scenario-simulator**: Simulation container for Autoware scenario testing.
- **visualizer**: RViz-based remote operation and visualization container for Autoware.
- **zenoh-bridge**: Bridge container to create efficient DDS messaging pipeline between edge and cloud (WIP).

To Run:

```bash
docker-compose -f docker-compose-cloud.yaml up -d # Runs on cloud
docker-compose -f docker-compose-edge.yaml up -d # Runs on edge
```

![oadkit](https://github.com/user-attachments/assets/0172eed1-c2cf-4f8d-b94c-91ed092e421c)