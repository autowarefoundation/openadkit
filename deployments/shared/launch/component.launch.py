"""Launch an autoware_launch component with use_sim_time as a global parameter.

Upstream's simulator and map component launches ignore use_sim_time, while
the other components load it with the global parameters. Their nodes then run
on wall time against simulation-time TF and never clear their TF buffers when
a new scenario resets the clock. Remove this file once the pinned Autoware
release has https://github.com/autowarefoundation/autoware_launch/pull/2023.
Usage:

    ros2 launch component.launch.py component:=tier4_simulator_component \
        use_sim_time:=true <component arguments>

A component is a file of autoware_launch's launch/components; a path such as
planning_simulator/perception_simulation names a file under launch/ instead.
"""

import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import IncludeLaunchDescription, OpaqueFunction
from launch.launch_description_sources import AnyLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import SetParameter


def include_component(context):
    # Command-line arguments reach an include only when passed explicitly.
    arguments = dict(context.launch_configurations)
    component = arguments.pop("component")
    path = os.path.join(
        get_package_share_directory("autoware_launch"),
        "launch",
        component if "/" in component else os.path.join("components", component),
    ) + ".launch.xml"
    return [
        SetParameter(name="use_sim_time", value=LaunchConfiguration("use_sim_time")),
        IncludeLaunchDescription(
            AnyLaunchDescriptionSource(path), launch_arguments=arguments.items()
        ),
    ]


def generate_launch_description():
    return LaunchDescription([OpaqueFunction(function=include_component)])
