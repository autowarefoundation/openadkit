#!/usr/bin/env bash
set -euo pipefail

# Copy into a runtime image's install tree the packages a build stage has and
# the image does not, and nothing else: rewriting a package the image already
# has, even unchanged, would store it once more in this layer. Strips the
# copied libraries and drops their build-only files.
#
# RViz plugins are left out unless --with-visualization is given: only the
# visualizer runs RViz, and its Qt and OpenGL stack would otherwise reach every
# image. A plugin is a package that builds on rviz_common.
#
# Usage: install-packages.sh [--with-visualization] <build-tree> <runtime-tree>

with_visualization=false
if [ "${1:-}" = --with-visualization ]; then
    with_visualization=true
    shift
fi
source=${1:?usage: install-packages.sh [--with-visualization] <build-tree> <runtime-tree>}
target=${2:?usage: install-packages.sh [--with-visualization] <build-tree> <runtime-tree>}

is_visualization() {
    grep -qE '<(build_)?depend>rviz_(common|rendering|default_plugins)</' "$1/share/$(basename "$1")/package.xml" 2>/dev/null
}

mkdir -p "${target}"
# The tree's own setup scripts, the same in every build stage.
find "${source}" -maxdepth 1 -type f -exec cp -an {} "${target}/" \;
for package in "${source}"/*/; do
    package=${package%/}
    name=$(basename "${package}")
    [ -e "${target}/${name}" ] && continue
    [ -f "${package}/share/${name}/package.xml" ] || continue
    if [ "${with_visualization}" = false ] && is_visualization "${package}"; then
        echo "left out RViz plugin: ${name}"
        continue
    fi
    cp -a "${package}" "${target}/${name}"
    find "${target}/${name}" -name '*.so' -exec strip --strip-unneeded {} +
    find "${target}/${name}" -type f \( -name '*.a' -o -name '*.o' \) -delete
    rm -rf "${target}/${name}/include"
done
