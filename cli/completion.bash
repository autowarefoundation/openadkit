# Bash completion for openadkit.
#
# `openadkit install` links this file into
# ~/.local/share/bash-completion/completions, where bash-completion loads it on
# the first Tab. Deployment names come from `list --json`: the kit around the
# current directory, or else the active release, as the command resolves them.
# test_openadkit_cli.py checks that every subcommand and option is listed.

_openadkit_deployments() {
    "$1" list --json 2>/dev/null | python3 -I -c '
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
    local commands="install upgrade setup uninstall list version new validate config settings fetch run build clean status logs restart shell record stop"
    COMPREPLY=()

    if ((COMP_CWORD == 1)); then
        mapfile -t COMPREPLY < <(compgen -W "${commands} --help" -- "${cur}")
        return
    fi

    # Option values.
    case ${prev} in
        --ros-distro)
            mapfile -t COMPREPLY < <(compgen -W "humble jazzy" -- "${cur}")
            return ;;
        --output | --ws)
            mapfile -t COMPREPLY < <(compgen -d -- "${cur}")
            return ;;
        --role | --service | --set | --unset)
            return ;;
        --version)
            [[ ${command} == install ]] && return ;;
    esac

    local options=""
    case ${command} in
        install) options="--version --force --help" ;;
        upgrade) options="--check --help" ;;
        setup) options="--gpu --no-check --help" ;;
        uninstall) options="--all --help" ;;
        list | version) options="--json --verbose --help" ;;
        validate) options="--ros-distro --gpu --role --ws --data --json --verbose --help" ;;
        config) options="--ros-distro --gpu --role --ws --verbose --help" ;;
        settings) options="--ros-distro --gpu --role --ws --service --set --unset --verbose --help" ;;
        fetch) options="--force --verbose --help" ;;
        run) options="--ros-distro --gpu --role --ws --no-visualizer --verify --verbose --help" ;;
        build) options="--ros-distro --verbose --help" ;;
        new) options="--base --verbose --help" ;;
        clean) options="--yes --verbose --help" ;;
        status | stop | shell) options="--role --verbose --help" ;;
        restart) options="--role --all --verbose --help" ;;
        logs) options="--role --follow --verbose --help" ;;
        record) options="--role --all --output --verbose --help" ;;
    esac
    if [[ ${cur} == -* ]]; then
        mapfile -t COMPREPLY < <(compgen -W "${options}" -- "${cur}")
        return
    fi

    # build takes a workspace directory.
    if [[ ${command} == build ]]; then
        mapfile -t COMPREPLY < <(compgen -d -- "${cur}")
        return
    fi

    # The deployment is the first word after the command that is neither an
    # option nor an option's value. The commands that act on the running
    # deployment take no name.
    case ${command} in
        validate | config | settings | fetch | run | clean) ;;
        *) return ;;
    esac
    local index word
    for ((index = 2; index < COMP_CWORD; index++)); do
        word=${COMP_WORDS[index]}
        case ${word} in
            --ros-distro | --role | --output | --ws | --service | --set | --unset) ((index++)) ;;
            -*) ;;
            *) return ;;
        esac
    done
    mapfile -t COMPREPLY < <(compgen -W "$(_openadkit_deployments "${COMP_WORDS[0]}")" -- "${cur}")
}

complete -F _openadkit openadkit
