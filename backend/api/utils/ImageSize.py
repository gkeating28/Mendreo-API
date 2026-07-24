from PIL import Image
from ..utils import File
from io import BytesIO

BANNER = [800, 450]
MOBILE = [600, 337.5]
THUMBNAIL = [400, 225]
ICON = [100, 100]
FAVICON = [32, 32]


def greater_than_or_equal(file, width, height):
    image = Image.open(file)

    if image.size[0] < width:
        return False
    elif image.size[1] < height:
        return False
    else:
        return True


def resize(file=None, size=None, return_memory_file=True):

    image = Image.open(file)

    if size is None:
        size = image.size

    width_percent = size[0] / float(image.size[0])
    height = int(float(image.size[1]) * float(width_percent))

    image = image.resize((size[0], height), Image.ANTIALIAS)

    if not return_memory_file:
        return image

    extension = File.get_extension(file)
    if extension == "jpg":
        extension = "jpeg"

    memory_file = BytesIO()

    image.save(memory_file, extension)

    return memory_file.getvalue()

