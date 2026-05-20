ARG SIMULATOR_IMAGE=ghcr.io/autowarefoundation/openadkit:simulator-amd64-humble
FROM ${SIMULATOR_IMAGE} AS carla-interface

ARG CARLA_PYTHON_VERSION=0.9.16

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update \
  && apt-get install -y --no-install-recommends \
    ros-humble-compressed-image-transport \
    ros-humble-topic-tools \
  && python3 -m pip install --no-cache-dir \
    carla==${CARLA_PYTHON_VERSION} \
    transforms3d \
  && rm -rf /var/lib/apt/lists/*

# CARLA can crash when the interface reloads the same visible map during
# startup. Preload Town01 in the launcher, then skip only this redundant
# load_world call while preserving map reloads for other maps.
RUN python3 - <<'PY'
from pathlib import Path

matches = list(Path('/opt/autoware').glob('**/autoware_carla_interface/carla_autoware.py'))
if not matches:
    raise SystemExit('autoware_carla_interface/carla_autoware.py not found under /opt/autoware')

path = matches[0]
text = path.read_text()
old = '''        client.load_world(self.carla_map)

        # Wait for the world to be fully loaded
        # This is critical for non-default maps that need time to load
        time.sleep(2.0)

        self.world = client.get_world()
'''
new = '''        current_world = client.get_world()
        current_map = current_world.get_map().name
        if not current_map.endswith("/" + self.carla_map):
            client.load_world(self.carla_map)
            time.sleep(2.0)
        self.world = client.get_world()
'''
if old not in text:
    raise SystemExit('autoware_carla_interface load_world block not found')
path.write_text(text.replace(old, new, 1))
PY
