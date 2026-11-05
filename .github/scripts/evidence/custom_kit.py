"""Runtime acceptance checks for deployments/custom-kit (inside the API image)."""
import subprocess


def main():
    expected = {
        "update_rate": "Double value is: 20.0",
        "boundary_departure_checker": "Boolean value is: True",
    }
    for parameter, value in expected.items():
        result = subprocess.run(
            ["ros2", "param", "get", "/control/trajectory_follower/lane_departure_checker_node", parameter],
            capture_output=True, text=True, timeout=30, check=False,
        )
        print(f"{parameter}: {result.stdout.strip()}", flush=True)
        if result.returncode != 0 or result.stdout.strip() != value:
            print(result.stderr, flush=True)
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
