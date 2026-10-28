# Town01 Lanelet2 Map

`lanelet2_map.osm` is CARLA's Town01 vector map from
[carla-simulator/autoware-contents](https://bitbucket.org/carla-simulator/autoware-contents/src/062f94b5322e679ee0430e2daa6995dca9f7f0ea/maps/vector_maps/lanelet2/Town01.osm)
with one line added after the `<osm>` element:

```xml
<MetaInfo format_version="1" map_version="1" />
```

Autoware's route handler rejects a map without a format version, so a goal
cannot be routed on the upstream file. `deployment.json` installs this copy
(`"source"`) and checks its sha256.
