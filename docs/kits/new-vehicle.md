# A New Vehicle

Autoware finds a vehicle and its sensors by package name. With
`VEHICLE_MODEL=my_vehicle` and `SENSOR_MODEL=my_sensor_kit`, its launch files
read four packages:

| Package | Holds |
| --- | --- |
| `my_vehicle_description` | `vehicle_info.param.yaml`, the simulator model and the vehicle's URDF and mesh |
| `my_vehicle_launch` | `vehicle_interface.launch.xml`, which starts your vehicle interface |
| `my_sensor_kit_description` | The sensor calibration files and the sensor kit's URDF |
| `my_sensor_kit_launch` | The sensor launch files and the sensor kit's diagnostics configuration |

1. Put the four packages in `overlay_ws/src`. Autoware's
   `sample_vehicle_description`, `sample_vehicle_launch`,
   `sample_sensor_kit_description` and `sample_sensor_kit_launch` are the
   templates: copy them and replace the names in every file.
2. Set `VEHICLE_MODEL` and `SENSOR_MODEL` in the kit's `settings.env`, so every
   deployment of the kit runs your vehicle.
3. Point `MAP_PATH` at your map and name its files. In the kit's
   `settings.env` this applies to every deployment of the kit:

    ```bash
    MAP_PATH=${OPENADKIT_KIT}/map
    LANELET2_MAP_FILE=my_town.osm
    POINTCLOUD_MAP_FILE=my_town.pcd
    ```

    A map too large for the kit's repository stays outside it: give its
    absolute path in the host settings file instead. The CLI uses a map
    directory of yours as it is
    ([Downloaded Data](../getting-started/cli.md#downloaded-data)).
4. Build and run: `openadkit build`, then `openadkit run --verify`. The base's
   verify step drives the sample map's route, so on your own map give the
   deployment a verify step of its own.

Every service sources the workspace, so planning, control, the simulator and
the visualizer all read the same vehicle. All four packages must exist: the
vehicle and system services look up the two `_launch` packages on every start.
`validate` does not check for them. When one is missing, `run` reports the
service that failed, and `openadkit logs <service>` names the package. Every
release tests this path: the example kit drives with four such packages.

Autoware's defaults describe a passenger car. Review these for your vehicle.
The first two are in your packages. The others belong to Autoware packages, so
change them with [config overrides](kit-guide.md#2-config-overrides); their package and
path depend on the release's Autoware version, so look them up in its images and
check `run`'s override warnings.

| Parameters | File | Why |
| --- | --- | --- |
| Dimensions, `wheel_base`, `max_steer_angle` | `vehicle_info.param.yaml` of your vehicle description | Planning and control use them as limits; a steering limit above the vehicle's makes control ask for angles it cannot reach. |
| Sensor poses | your sensor kit's `sensor_kit_calibration.yaml` and `sensors_calibration.yaml` | A wrong sign or offset shows up as a localization error of the same size. |
| `nominal_latency`, `assumed_limit_acc` | `control_validator.param.yaml` | Your actuation latency and achievable braking. With car values a slower or weaker vehicle fails validation and triggers an MRM. |
| `pose_measurement.pose_gate_dist` | `ekf_localizer.param.yaml` | The Mahalanobis gate for pose updates. A start pose far from the truth can be rejected for good. |
| Velocity, acceleration, jerk and steering-rate limits | `vehicle_cmd_gate.param.yaml` | The last limits before the vehicle interface. |
