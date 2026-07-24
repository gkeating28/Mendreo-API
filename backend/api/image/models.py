from django.db import models

from ..utils.Fields import CharIDField
from ..utils.Models import SmartModel


class Image(SmartModel):
    """
    Model instance for storing a reference to an image uploaded to the platform.
    The image itself is stored on AWS S3 bucket.
    """

    id = CharIDField(primary_key=True, prefix="img_")

    created_by = models.ForeignKey("api.User", related_name="images", on_delete=models.CASCADE)

    # ability to store a textual representation of the image that can be shown as a placeholder during loading
    # a potential library for generating these: https://github.com/woltapp/blurhash
    blur_hash = models.CharField(max_length=255, null=True)

    original = models.CharField(max_length=255)

    name = models.CharField(max_length=255)

    width = models.PositiveIntegerField()
    height = models.PositiveIntegerField()

    uploaded = models.BooleanField(default=True)

    extension = models.CharField(max_length=50, null=True)
    size = models.CharField(max_length=255, null=True)

    token = models.TextField(null=True)

    def __str__(self):
        """Return a human readable representation of the model instance."""
        return "Image: {}".format(self.id)


    @staticmethod
    def generate(prompt: str, user, aspect_ratio="16:9"):
        from ..utils.AI import AI
        from ..utils.File import upload
        import uuid
        
        image_data = AI.generate_image(prompt, aspect_ratio)

        filename = f"{uuid.uuid4()}.png"
        path = f"/admins/{user.id}/images/{filename}"

        image = Image.objects.create(
            created_by=user,
            name=filename,
            width=1920,
            height=1080,
            extension="png",
            uploaded=False,
            original=path
        )

        upload(data=image_data, full_path=path, content_type='image/png')
        image.uploaded = True
        image.save()

        return image
