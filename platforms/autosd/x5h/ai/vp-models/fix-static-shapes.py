#!/usr/bin/env python3
"""Pin the batch dimension of the VisionPilot models to 1.

The pinned VP models declare a symbolic `batch_size` on every graph input and
output. The NNAC frontend needs concrete shapes: with a symbolic dim 0 the
converter fails late, inside legalization, on a shape it cannot resolve. Fixing
dim 0 on the inputs alone is not enough -- the outputs carry the same symbol and
the frontend reads them too.

Only dim 0 is touched. Intermediate value_info is left alone: ONNX Runtime
re-infers it from the pinned inputs, and rewriting it by hand is how stale
shapes get baked in.

Usage: fix-static-shapes.py <src-dir> <dst-dir> [model.onnx ...]
"""
import pathlib
import sys

import onnx


def pin_batch(tensor, batch=1):
    """Set dim 0 of a ValueInfoProto to `batch`. Returns True if it changed."""
    dim = tensor.type.tensor_type.shape.dim
    if not dim:
        return False
    if dim[0].HasField("dim_value") and dim[0].dim_value == batch:
        return False
    dim[0].ClearField("dim_param")
    dim[0].dim_value = batch
    return True


def main():
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    src, dst = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2])
    names = sys.argv[3:] or sorted(p.name for p in src.glob("*.onnx"))
    if not names:
        sys.exit(f"STATIC_SHAPES_FAIL no .onnx models in {src}")
    dst.mkdir(parents=True, exist_ok=True)
    for name in names:
        model = onnx.load(str(src / name))
        changed = sum(pin_batch(t) for t in list(model.graph.input) + list(model.graph.output))
        onnx.checker.check_model(model)
        onnx.save(model, str(dst / name))
        shapes = {
            t.name: [d.dim_value or d.dim_param for d in t.type.tensor_type.shape.dim]
            for t in list(model.graph.input) + list(model.graph.output)
        }
        print(f"  {name}: pinned={changed} {shapes}")
    print(f"STATIC_SHAPES_OK models={len(names)} out={dst}")


if __name__ == "__main__":
    main()
