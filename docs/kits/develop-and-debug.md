# Develop and Debug

The loop for a package in your kit's `overlay_ws`, how long it takes, and how
to look into a running deployment.

## The Development Loop

```bash
openadkit build                 # compiles what changed, in the release's devel image
openadkit restart <service>     # recreates the service that runs it
```

`build` compiles only what changed, and `restart <service>` recreates only that
service; [CLI & Maintenance](../getting-started/cli.md#runtime-controls) says what
`restart` without a name recreates.

Give a service of your own `init: true`, as the Autoware services have. Without
it the node is PID 1 and ignores the stop signal, and every stop and restart
waits 10 seconds for Docker to kill it.

### How Long It Takes

One changed C++ file in the example kit on Planning Simulation, measured on an
AMD Ryzen 7 250 (16 threads) with 30 GB of RAM, Ubuntu 24.04 and the Humble
images:

| Step | Time |
| --- | --- |
| `openadkit build` | 5 s |
| `openadkit restart <service>` | 22 s |
| First message of the changed node | 2 s |
| **Total** | **29 s** |

Of the restart, about 10 seconds wait for the service's healthcheck and 10
seconds check that the services stay up. The first build of the workspace,
with its five packages, took 9 seconds.

## Look Into a Running Deployment

```bash
openadkit status
openadkit logs my-node --follow
openadkit shell my-node ros2 node list
openadkit shell api ros2 topic echo --once /my/topic
openadkit record /my/topic /tf
```

See [Runtime Controls](../getting-started/cli.md#runtime-controls) for each
command; `record` writes to `~/openadkit-output/<deployment>/recordings`.

## Attach a Debugger

The images carry no debugger. Attach gdb from a second container that joins the
service's process namespace; the service and its image stay as they are.

1. Build with debug symbols and restart the service:

    ```bash
    openadkit build -- --cmake-args -DCMAKE_BUILD_TYPE=RelWithDebInfo
    openadkit restart <service>
    ```

2. Find the service's container in the `CONTAINER` column of
   `openadkit status`. An Autoware service is `autoware-<service>`; a service
   of your kit is `openadkit-<deployment>-<service>-1`.

3. Start gdb beside it. `my_node` is the name of the executable:

    ```bash
    docker run --rm -it --pid container:<container> --cap-add SYS_PTRACE ubuntu:22.04 bash -c '
      apt-get update -qq && apt-get install -y -qq gdb &&
      pid=$(pidof my_node) &&
      gdb -ex "set sysroot /proc/$pid/root" -ex "attach $pid"'
    ```

    Use `ubuntu:22.04` for the Humble images and `ubuntu:24.04` for the Jazzy
    ones, so that gdb matches the C library of the process.

`set sysroot` makes gdb read the binary and its libraries from the service's
own filesystem. A backtrace then shows your source lines, such as
`main (...) at /openadkit/overlay_ws/src/my_package/src/my_node.cpp:24`.

The Autoware services share one process namespace, so `autoware-map` as the
container reaches the processes of all of them. The visualizer keeps its own
namespace, so name its own container for it.
