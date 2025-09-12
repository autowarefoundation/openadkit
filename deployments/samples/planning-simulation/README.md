# Autoware Planning Simulation

This sample deployment shows how to run the planning simulation deployment sample.

- **autoware**: Autoware monolithic container for development and deployment.
- **visualizer**: RViz-based remote operation and visualization container for Autoware.

## Requirements

In order to run the planning simulation sample deployment, you need to have the planning **sample map**. You can download it by running the following command:

### Sample Planning Map

Download and unpack a sample map that is used in this sample.

- You can also download [the map](https://drive.google.com/file/d/1499_nsbUbIeturZaDj7jhUownh5fvXHd/view?usp=sharing) manually.

```bash
gdown -O ~/autoware_map/ 'https://docs.google.com/uc?export=download&id=1499_nsbUbIeturZaDj7jhUownh5fvXHd'
unzip -d ~/autoware_map ~/autoware_map/sample-map-planning.zip
```

> **Note**: This sample map(Copyright 2020 TIER IV, Inc.) is only for demonstration purposes. You can use your own map by following the [How-to Guide](https://autowarefoundation.github.io/autoware-documentation/main/how-to-guides/integrating-autoware/creating-maps/).

## Run the Deployment

1. Start the deployment by running the following command:

    ```bash
    docker-compose -f docker-compose.yaml up -d
    ```

2. Open a browser to visualize the simulation and navigate to:

    ```bash
    http://localhost:6080
    ```

    Use the default password `openadkit` to access the visualizer. **It can take a few seconds to visualizer to start.**

    > If your machine is on a remote server, you can access the visualizer by using the the public IP address:
    >
    > ```bash
    > http://<your-server-public-ip>:6080/vnc.html
    > ```

3. After you see the visualizer, you can start to simulate the autonomous driving scenario by following the [planning simulation instructions](https://autowarefoundation.github.io/autoware-documentation/main/tutorials/ad-hoc-simulation/planning-simulation/#2-set-an-initial-pose-for-the-ego-vehicle) in the Autoware documentation.

## Stop the Deployment

```bash
docker-compose -f docker-compose.yaml down
```
