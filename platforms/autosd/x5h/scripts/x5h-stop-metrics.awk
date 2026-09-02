#!/usr/bin/awk -f
# Stop-distance metrics for x5h-stack-smoke.sh's drive mode. Two modes, one
# file so the board stages a single artifact next to the smoke script:
#
#   awk -v mode=t0 -v pat=<record-regex> -f x5h-stop-metrics.awk <capture>
#     Finds the FIRST `ros2 topic echo` record matching pat and prints its
#     stamp (first `sec:`/`nanosec:` pair in the record) as one float,
#     epoch seconds. Exit 0 on a stamped match, 1 otherwise. Used to anchor
#     t=0 at the injected fault (or, fallback, at the availability drop).
#
#   awk -v t0=<epoch-seconds-float> -f x5h-stop-metrics.awk <kinematic.txt>
#     Integrates the ego's path length from the first sample at/after t0 to
#     rest -- the first sample after which speed stays below REST_V for the
#     remainder of the capture. Prints
#       stop_distance_m=<d> rest_x=<x> rest_y=<y>
#     and exits 0. On failure it exits 1 printing one of two distinct
#     strings -- no_stop_metrics (fewer than two in-window samples) or
#     never_rested (the ego's speed never stayed below REST_V through the
#     end of the capture) -- but the distinction does not reach an operator:
#     x5h-stack-smoke.sh's caller only matches the stop_distance_m=* success
#     line and maps every other output, both of these included, to its own
#     single reason=mrm_no_stop_metrics.
#
# Path length, not straight-line displacement, so a stop that begins in a
# curve compares fairly across runs. The parser is indentation-anchored to
# the YAML `ros2 topic echo` prints for nav_msgs/Odometry and is pinned by
# components/nodes/test_stop_metrics.py against captured samples; if a ROS
# release changes the echo layout, the fixtures fail first.
BEGIN {
    RS = "---"
    REST_V = 0.05
    count = 0
    found = 0
}

mode == "t0" {
    if (found || $0 !~ pat) next
    n = split($0, L, "\n")
    s = ""; ns = ""
    for (i = 1; i <= n; i++) {
        if (s == "" && L[i] ~ /^ *sec: -?[0-9]/) {
            sub(/^ *sec: */, "", L[i]); s = L[i]
        } else if (ns == "" && L[i] ~ /^ *nanosec: [0-9]/) {
            sub(/^ *nanosec: */, "", L[i]); ns = L[i]
        }
    }
    if (s != "") {
        printf "%.9f\n", s + (ns == "" ? 0 : ns) / 1e9
        found = 1
    }
    next
}

mode != "t0" {
    sec = ""; nsec = ""; px = ""; py = ""; v = ""
    ctx = ""
    n = split($0, L, "\n")
    for (i = 1; i <= n; i++) {
        line = L[i]
        if (line ~ /^header:/) ctx = "hdr"
        else if (ctx == "hdr" && line ~ /^  stamp:/) ctx = "stamp"
        else if (ctx == "stamp" && line ~ /^    sec: /) sec = substr(line, 10)
        else if (ctx == "stamp" && line ~ /^    nanosec: /) { nsec = substr(line, 14); ctx = "" }
        else if (line ~ /^pose:/) ctx = "pose"
        else if (ctx == "pose" && line ~ /^  pose:/) ctx = "pose2"
        else if (ctx == "pose2" && line ~ /^    position:/) ctx = "pos"
        else if (ctx == "pos" && line ~ /^      x: /) px = substr(line, 10)
        else if (ctx == "pos" && line ~ /^      y: /) { py = substr(line, 10); ctx = "" }
        else if (line ~ /^twist:/) ctx = "twist"
        else if (ctx == "twist" && line ~ /^  twist:/) ctx = "twist2"
        else if (ctx == "twist2" && line ~ /^    linear:/) ctx = "lin"
        else if (ctx == "lin" && line ~ /^      x: /) { v = substr(line, 10); ctx = "" }
    }
    if (sec == "" || px == "" || py == "" || v == "") next
    t = sec + (nsec == "" ? 0 : nsec) / 1e9
    if (t < t0 + 0) next
    count++
    X[count] = px + 0
    Y[count] = py + 0
    vn = v + 0
    V[count] = (vn < 0) ? -vn : vn
}

END {
    if (mode == "t0") exit !found
    if (count < 2) { print "no_stop_metrics"; exit 1 }
    rest = 0
    for (k = count; k >= 1; k--) {
        if (V[k] >= REST_V) { rest = k + 1; break }
    }
    if (rest == 0) rest = 1
    if (rest > count) { print "never_rested"; exit 1 }
    d = 0
    for (i = 2; i <= rest; i++) {
        dx = X[i] - X[i-1]; dy = Y[i] - Y[i-1]
        d += sqrt(dx * dx + dy * dy)
    }
    printf "stop_distance_m=%.2f rest_x=%.2f rest_y=%.2f\n", d, X[rest], Y[rest]
}
