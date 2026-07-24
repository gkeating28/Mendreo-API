from rest_framework import serializers

from ..post.models import Post, Image, User

from ..tasks import generate_post

from ..utils import Constants


class AICreateSerializer(serializers.Serializer):

    theme = serializers.CharField(required=False)
    type = serializers.ChoiceField(choices=["article"])

    def create(self, validated_data):

        type_ = validated_data.pop("type")

        theme = validated_data.pop("theme", "")

        admin_user = User.objects.filter(type=Constants.USER_TYPE_ADMIN).first()
        if not admin_user:
            raise Exception("No admin user found")

        placeholder_image = Image.objects.create(
            width=360,
            height=360,
            created_by=admin_user,
            original="https://t4.ftcdn.net/jpg/06/57/37/01/360_F_657370150_pdNeG5pjI976ZasVbKN9VqH1rfoykdYU.jpg"
        )

        post = Post.objects.create(
            type=type_,
            created_by=admin_user,
            banner=placeholder_image,
            thumbnail=placeholder_image,
            status=Constants.POST_STATUS_GENERATING,
            title=f"AI {type_} Generating...",
            subtitle=f"This content will be replaced by AI generated content nce complete"
        )

        theme = f"Theme: {theme}" if theme else ""

        generate_post.delay_on_commit(post.id, theme)

        return post





