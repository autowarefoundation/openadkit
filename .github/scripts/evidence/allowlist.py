"""Check that every topic a split-host allowlist bridges exists in the running graph.

Autoware renames topics between releases; the Zenoh bridge would then stop
carrying the old name without any error. Each allowlist entry is a full-name
regular expression and must match at least one topic of either node's graph.
"""
import argparse
import re
import sys
from pathlib import Path


def allowed_topics(text):
    """The publisher entries of a zenoh-bridge-ros2dds JSON5 config."""
    text = re.sub(r"(^|\s)//[^\n]*", r"\1", text)
    block = re.search(r"\bpublishers:\s*\[(.*?)\]", text, re.DOTALL)
    if block is None:
        raise ValueError("no publishers list in the allowlist")
    return re.findall(r'"([^"]+)"', block.group(1))


def missing(entries, topics):
    return [entry for entry in entries if not any(re.fullmatch(entry, topic) for topic in topics)]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True, help="the deployment's config/zenoh.json5")
    parser.add_argument("--topics", type=Path, action="append", required=True,
                        help="a node's `ros2 topic list` output; repeat for each node")
    args = parser.parse_args()
    topics = {line.strip() for path in args.topics for line in path.read_text().splitlines() if line.strip()}
    entries = allowed_topics(args.config.read_text(encoding="utf-8"))
    gaps = missing(entries, topics)
    for entry in gaps:
        print(f"allowlisted topic is in neither graph: {entry}")
    print(f"allowlist: {len(entries) - len(gaps)}/{len(entries)} entries match {len(topics)} topics")
    return 1 if gaps else 0


if __name__ == "__main__":
    sys.exit(main())
