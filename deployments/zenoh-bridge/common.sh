#!/bin/bash

# Color definitions
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
# shellcheck disable=SC2034 # Used by cloud.sh after sourcing this file.
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# Read one simple dotenv assignment without evaluating it as shell code.
# Exported variables take precedence, matching Docker Compose interpolation.
read_dotenv_value() {
    local name="$1"
    local file="${2:-.env}"
    local line value

    [[ "$name" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] || return 2
    if [[ -v "$name" ]]; then
        printf '%s\n' "${!name}"
        return 0
    fi
    [[ -f "$file" ]] || return 1

    while IFS= read -r line || [[ -n "$line" ]]; do
        line="${line%$'\r'}"
        if [[ "$line" =~ ^[[:space:]]*${name}[[:space:]]*=(.*)$ ]]; then
            value="${BASH_REMATCH[1]}"
            value="${value#"${value%%[![:space:]]*}"}"
            value="${value%"${value##*[![:space:]]}"}"
            if [[ ${#value} -ge 2 ]]; then
                if [[ "${value:0:1}" == '"' && "${value: -1}" == '"' ]] \
                    || [[ "${value:0:1}" == "'" && "${value: -1}" == "'" ]]; then
                    value="${value:1:${#value}-2}"
                fi
            fi
            printf '%s\n' "$value"
            return 0
        fi
    done < "$file"
    return 1
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
    local args="$*"

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
