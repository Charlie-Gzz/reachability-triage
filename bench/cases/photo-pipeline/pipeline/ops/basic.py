def resize(img, width, height):
    return img.resize((int(width), int(height)))


def grayscale(img):
    return img.convert("L")
