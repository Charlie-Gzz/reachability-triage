from PIL import ImageMath


def apply_expression(img, formula):
    return ImageMath.eval(formula, a=img.convert("L"))
