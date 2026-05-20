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

path = Path('/opt/autoware/lib/python3.10/site-packages/autoware_carla_interface/carla_autoware.py')
text = path.read_text()
old = '        client.load_world(self.carla_map)\n        self.world = client.get_world()\n'
new = '''        current_world = client.get_world()
        current_map = current_world.get_map().name
        if not current_map.endswith("/" + self.carla_map):
            client.load_world(self.carla_map)
        self.world = client.get_world()
'''
if old not in text:
    raise SystemExit('autoware_carla_interface load_world block not found')
path.write_text(text.replace(old, new, 1))
PY
