from html import escape
import json
from google import genai
from google.genai import types
from pydantic import BaseModel, Field
from ..utils import Api, Constants

class ArticleResponse(BaseModel):
    """Response model for AI-generated article content"""
    title: str = Field(description="Engaging article title")
    subtitle: str = Field(description="Compelling subtitle")
    body: str = Field(description="Full article content with proper formatting")
    image_prompt: str = Field(description="Prompt for generating article image")

ARTICLE_SCHEMA = types.Schema(
    type=types.Type.OBJECT,
    properties={
        "title": types.Schema(type=types.Type.STRING, description="Engaging article title, 4-5 words max"),
        "subtitle": types.Schema(type=types.Type.STRING, description="Compelling subtitle"),
        "body": types.Schema(type=types.Type.STRING, description="Full article content with proper formatting"),
        "image_prompt": types.Schema(type=types.Type.STRING, description="Prompt for generating article image")
    },
    required=["title", "subtitle", "body", "image_prompt"]
)


class AI:
    @staticmethod
    def ask(prompt: str, schema, model="gemini-2.5-flash", temperature=0.3) -> {}:
        """
        Sends a prompt to Gemini and returns the raw text response.
        """
        client = genai.Client(api_key=Api.GOOGLE_API_KEY)

        response = client.models.generate_content(
            model=model,
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                temperature=temperature,
                response_schema=schema
            )
        )

        data = json.loads(response.text)
        return data

    @staticmethod
    def generate_image(prompt: str, aspect_ratio: str = "16:9") -> bytes:
        """
        Generate an image using Google's Imagen API.
        """
        client = genai.Client(api_key=Api.GOOGLE_API_KEY)
        
        try:
            response = client.models.generate_images(
                model='imagen-4.0-generate-001',
                prompt=prompt,
                config=types.GenerateImagesConfig(
                    number_of_images=1,
                    aspect_ratio=aspect_ratio,
                    safety_filter_level='block_low_and_above',
                    person_generation='allow_adult',
                )
            )
            
            if response.generated_images:
                return response.generated_images[0].image.image_bytes
            else:
                raise Exception("No image was generated")
                
        except Exception as e:
            raise Exception(f"Image generation failed: {str(e)}")

    @staticmethod
    def generate_article(optional_extra: str = "") -> ArticleResponse:
        from ..post.models import Post 
        existing_articles = Post.objects.filter(
            type=Constants.POST_TYPE_ARTICLE,
            status=Constants.POST_STATUS_PUBLISHED
        ).order_by('-impressions_no')[:10]

        examples_xml = "\n".join([
            f"""
            <article>
                <title>{escape(a.title)}</title>
                <subtitle>{escape(a.subtitle)}</subtitle>
                <views>{a.views_no}</views>
                <impressions>{a.impressions_no}</impressions>
            </article>
            """ for a in existing_articles
        ])

        prompt = f"""
<articles>
{examples_xml}
</articles>

Create a NEW mental wellness article that is different from all examples but compliments them and is likely to be popular based on the example articles views/impressions.
{optional_extra}
"""

        result = AI.ask(prompt=prompt, schema=ARTICLE_SCHEMA)
        return ArticleResponse(**result)
