"""A `ros2 launch` option that records every process that dies.

`ros2 launch` keeps running when one of its nodes dies, so the container stays
up. This option adds one event handler to whatever is launched: a process that
exits with a non-zero code is appended to /tmp/openadkit/died, and the
service's healthcheck fails while that file exists. A clean exit does not
count, nor does a process that dies while the launch shuts down.

The image entrypoint puts this directory on PYTHONPATH, and `ros2 launch` finds
the option through the entry point in openadkit_health-1.0.dist-info. It
rebuilds /tmp/openadkit on every start, so a restarted service starts healthy.
"""

from launch import LaunchDescription
from launch.actions import RegisterEventHandler
from launch.event_handlers import OnProcessExit
from ros2launch.option import OptionExtension

MARKER = "/tmp/openadkit/died"


def record(event, context):
    if event.returncode == 0 or context.is_shutdown:
        return
    try:
        with open(MARKER, "a", encoding="utf-8") as marker:
            marker.write(f"{event.process_name} died with exit code {event.returncode}\n")
    except OSError:
        # Recording a death must never end the launch that still runs the others.
        pass


class HealthOption(OptionExtension):
    def prelaunch(self, launch_description, args):
        handler = RegisterEventHandler(OnProcessExit(on_exit=record))
        return (LaunchDescription([handler, launch_description]),)
