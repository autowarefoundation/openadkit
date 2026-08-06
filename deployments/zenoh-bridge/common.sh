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
    local arg

    for arg in "$@"; do
        case "$arg" in
            -d|--detach|--build|--no-build|--no-deps|--force-recreate|--remove-orphans) ;;
            *)
                echo -e "${RED}[Error]${NC} Invalid or unsafe flag: $arg"
                echo "Allowed flags: -d --detach --build --no-build --no-deps --force-recreate --remove-orphans"
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
    if [[ $# -gt 0 ]]; then
        shift
    fi
    local -a args=("$@")
    local -a services
    read -r -a services <<< "$target_services"

    echo -e "${YELLOW}[${context_name}]${NC} Target Services: ${GREEN}${target_services}${NC}"

    case "$cmd" in
        "up")
            echo -e "${YELLOW}[${context_name}]${NC} Starting services..."
            validate_args "${args[@]}"
            docker compose up "${args[@]}" "${services[@]}"
            ;;

        "down")
            echo -e "${RED}[${context_name}]${NC} Stopping and removing services (with volumes)..."
            docker compose stop "${services[@]}"
            docker compose rm -f -v "${services[@]}"
            ;;

        "dry-run")
            echo -e "${YELLOW}[${context_name}]${NC} [Dry Run] Would start services: ${GREEN}${target_services}${NC}"
            echo -e "${YELLOW}[${context_name}]${NC} Validating compose configuration..."
            docker compose config -q
            ;;

        "config")
            echo -e "${YELLOW}[${context_name}]${NC} Validating compose configuration..."
            docker compose config -q
            ;;

        *)
            echo -e "${YELLOW}[${context_name}]${NC} Executing: docker compose $cmd ${args[*]} ..."
            docker compose "$cmd" "${args[@]}" "${services[@]}"
            ;;
    esac
}
