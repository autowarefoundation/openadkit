#!/bin/bash

# Color definitions
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# Load .env into the environment. Call before parsing flags so that
# command-line options override .env values.
load_env() {
    # shellcheck disable=SC1091
    [ -f .env ] && { set -a; . ./.env; set +a; }
    return 0
}

validate_args() {
    local args="$1"
    local allowed_flags="-d --detach --build --no-build --no-deps --force-recreate --remove-orphans"

    for arg in $args; do
        case " $allowed_flags " in
            *" $arg "*) ;;
            *)
                echo -e "${RED}[Error]${NC} Invalid or unsafe flag: $arg"
                echo "Allowed flags: $allowed_flags"
                exit 1
                ;;
        esac
    done
}

run_compose() {
    local context_name="$1"
    shift
    local target_services="$1"
    shift

    local cmd="${1:-up}"
    shift
    local args="$@"

    echo -e "${YELLOW}[${context_name}]${NC} Target Services: ${GREEN}${target_services}${NC}"

    case "$cmd" in
        "up")
            echo -e "${YELLOW}[${context_name}]${NC} Starting services..."
            validate_args "$args"
            # shellcheck disable=SC2086 # word-splitting is intentional: $args and
            # $target_services each expand to multiple compose flags/services.
            docker compose up $args $target_services
            ;;

        "down")
            echo -e "${RED}[${context_name}]${NC} Stopping and removing services (with volumes)..."
            # shellcheck disable=SC2086 # $target_services expands to multiple services.
            docker compose stop $target_services
            # shellcheck disable=SC2086
            docker compose rm -f -v $target_services
            ;;

        "dry-run")
            echo -e "${YELLOW}[${context_name}]${NC} [Dry Run] Would start services: ${GREEN}${target_services}${NC}"
            echo -e "${YELLOW}[${context_name}]${NC} Validating compose configuration..."
            docker compose config
            ;;

        *)
            echo -e "${YELLOW}[${context_name}]${NC} Executing: docker compose $cmd $args ..."
            # shellcheck disable=SC2086 # word-splitting is intentional.
            docker compose "$cmd"${args:+ $args} $target_services
            ;;
    esac
}
