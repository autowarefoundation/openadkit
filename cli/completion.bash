# Bash completion for openadkit and its short name, adkit.
#
# `openadkit install` links this file as both commands into
# ~/.local/share/bash-completion/completions, where bash-completion loads it on
# the first Tab. Deployment names come from `list --json` of the kit or release
# in the current directory, as the command itself would resolve them.
# test_openadkit_cli.py checks that every subcommand and option is listed.

_openadkit_deployments() {
    "$1" list --json 2>/dev/null | python3 -c '
import json, sys
try:
    print(" ".join(item["name"] for item in json.load(sys.stdin)["deployments"]))
except (ValueError, KeyError, TypeError):
    pass
' 2>/dev/null
}

_openadkit() {
    local cur=${COMP_WORDS[COMP_CWORD]} prev=${COMP_WORDS[COMP_CWORD - 1]}
    local command=${COMP_WORDS[1]:-}
    local commands="install upgrade setup uninstall list version validate fetch run build-overlay clean status logs record stop"
    COMPREPLY=()

    if ((COMP_CWORD == 1)); then
        mapfile -t COMPREPLY < <(compgen -W "${commands} --version --help" -- "${cur}")
        return
    fi

    # Option values.
    case ${prev} in
        --ros-distro)
            mapfile -t COMPREPLY < <(compgen -W "humble jazzy" -- "${cur}")
            return ;;
        --pull)
            mapfile -t COMPREPLY < <(compgen -W "missing always never" -- "${cur}")
            return ;;
        --output | --destination)
            mapfile -t COMPREPLY < <(compgen -d -- "${cur}")
            return ;;
        --node)
            return ;;
        --version)
            [[ ${command} == install ]] && return ;;
    esac

    local options=""
    case ${command} in
        install) options="--version --destination --force --help" ;;
        upgrade) options="--check --help" ;;
        setup) options="--gpu --verify --help" ;;
        uninstall) options="--all --help" ;;
        list | version) options="--json --help" ;;
        validate) options="--ros-distro --gpu --node --data --json --help" ;;
        fetch) options="--ros-distro --force --help" ;;
        run) options="--ros-distro --gpu --node --pull --no-visualizer --help" ;;
        build-overlay) options="--ros-distro --help" ;;
        clean) options="--data --help" ;;
        status | stop) options="--node --help" ;;
        logs) options="--node --follow --help" ;;
        record) options="--node --all --output --help" ;;
    esac
    if [[ ${cur} == -* ]]; then
        mapfile -t COMPREPLY < <(compgen -W "${options}" -- "${cur}")
        return
    fi

    # The deployment is the first word after the command that is neither an
    # option nor an option's value.
    case ${command} in
        validate | fetch | run | build-overlay | clean | status | logs | record | stop) ;;
        *) return ;;
    esac
    local index word
    for ((index = 2; index < COMP_CWORD; index++)); do
        word=${COMP_WORDS[index]}
        case ${word} in
            --ros-distro | --node | --pull | --output) ((index++)) ;;
            -*) ;;
            *) return ;;
        esac
    done
    mapfile -t COMPREPLY < <(compgen -W "$(_openadkit_deployments "${COMP_WORDS[0]}")" -- "${cur}")
}

complete -F _openadkit openadkit adkit
