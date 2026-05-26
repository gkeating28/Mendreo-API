
from django.utils.text import slugify


def generate(model_instance, slugable_field_name, slug_field_name, unique_together_name=None, unique_together_key=None):
    """
    Takes a model instance, sluggable field name (such as 'title') of that
    model as string, slug field name (such as 'slug') of the model as string;
    returns a unique slug as string.
    Is this vulnerable to a Race Condition?
    """
    slug = slugify(getattr(model_instance, slugable_field_name))
    unique_slug = slug
    extension = 1
    ModelClass = model_instance.__class__

    data = {
        slug_field_name: unique_slug
    }

    if unique_together_name:
        data[unique_together_name] = getattr(model_instance, unique_together_name)
        if unique_together_key:
            data[unique_together_name] = getattr(data[unique_together_name], unique_together_key)

    while ModelClass._default_manager.filter(**data).exists():
        unique_slug = '{}-{}'.format(slug, extension)
        extension += 1

        data[slug_field_name] =unique_slug

    return unique_slug