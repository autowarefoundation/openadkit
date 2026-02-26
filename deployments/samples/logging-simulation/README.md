# Autoware Open AD Kit Logging Simulation

This sample deployment shows how to run Autoware Open AD Kit **logging simulation**.

## Requirements

In order to run the logging simulation, you need to have the logging simulation **sample map** and **rosbag**. You can download them by running the following commands:

### Sample Logging Map

Download and unpack a logging simulation sample map that is used in this sample.

- You can also download [the map](https://drive.google.com/file/d/1499_nsbUbIeturZaDj7jhUownh5fvXHd/view?usp=sharing) manually.

```bash
gdown -O ~/autoware_map/ 'https://docs.google.com/uc?export=download&id=1A-8BvYRX3DhSzkAnOcGWFw5T30xTlwZI'
unzip -d ~/autoware_map/ ~/autoware_map/sample-map-rosbag.zip
```

> **Note**: This sample map(Copyright 2020 TIER IV, Inc.) is only for demonstration purposes. You can use your own map by following the [How-to Guide](https://autowarefoundation.github.io/autoware-documentation/main/how-to-guides/integrating-autoware/creating-maps/).

### Sample Rosbag

Download and unpack a sample rosbag that is used for **sensor simulation** in this sample.

- You can also download [the rosbag](https://drive.google.com/file/d/1499_nsbUbIeturZaDj7jhUownh5fvXHd/view?usp=sharing) manually.

```bash
gdown -O ~/autoware_map/ 'https://docs.google.com/uc?export=download&id=1sU5wbxlXAfHIksuHjP3PyI2UVED8lZkP'
unzip -d ~/autoware_map/ ~/autoware_map/sample-rosbag.zip
```

> **Note**: Due to privacy concerns, the rosbag(Copyright 2020 TIER IV, Inc.) does not contain image data, which will cause: Traffic light recognition functionality cannot be tested with this sample rosbag. Object detection accuracy is decreased.

## Run the Deployment

1. Start the deployment by running the following command:

    ```bash
    docker compose --env-file logging-simulation.env up -d
    ```

2. Wait for the deployment to start for about 10 seconds and then open a browser to visualize the simulation and navigate to:

    ```bash
    http://localhost:6080/vnc.html
    ```

    Use the default password `openadkit` to access the visualizer. **It can take a few seconds to visualizer to start.**

    > If your machine is on a remote server, you can access the visualizer by using its accessible IP address:
    >
    > ```bash
    > http://<your-server-ip>:6080/vnc.html
    > ```

3. To start the logging simulation, you should run the following command to play the rosbag:

    ```bash
    docker compose --env-file logging-simulation.env up rosbag -d
    ```

## Stop the Deployment

Stop the deployment by running the following command:

```bash
docker compose --env-file logging-simulation.env --profile rosbag down
```
