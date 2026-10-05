"""Runtime acceptance checks for examples/custom-kit (inside the API image)."""
import subprocess


def main():
    expected = {
        "use_emergency_handling": "Boolean value is: False",
        "nominal.vel_lim": "Double value is: 8.0",
        "stop_hold_acceleration": "Double value is: -1.5",
    }
    for parameter, value in expected.items():
        result = subprocess.run(
            ["ros2", "param", "get", "/control/vehicle_cmd_gate", parameter],
            capture_output=True, text=True, timeout=30, check=False,
        )
        print(f"{parameter}: {result.stdout.strip()}", flush=True)
        if result.returncode != 0 or result.stdout.strip() != value:
            print(result.stderr, flush=True)
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
