from pipeline.ops.basic import grayscale, resize
from pipeline.ops.expressions import apply_expression

OPS = {"resize": resize, "grayscale": grayscale, "expr": apply_expression}
