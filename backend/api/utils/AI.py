from html import escape
from typing import Type

from google.genai import types
from pydantic import BaseModel, Field
from pydantic_ai import Agent

from ..utils import Constants
from ..utils.AiProviderFactory import (
    build_google_genai_client,
    build_pydantic_model,
    get_google_provider_for_images,
    run_with_failover,
)


class ArticleResponse(BaseModel):
    """Response model for AI-generated article content"""
    title: str = Field(description="Engaging article title")
    subtitle: str = Field(description="Compelling subtitle")
    body: str = Field(description="Full article content with proper formatting")
    image_prompt: str = Field(description="Prompt for generating article image")


class SummaryAiResponse(BaseModel):
    detailed: str = Field(description="Notes on user")
    observations: str = Field(description="Observations intended to be read by user")
    next_steps: str = Field(description="Next steps you deem necessary for user")


class SessionAiResponse(BaseModel):
    subject: str
    rating: float
    rating_reason: str
    risk_level: str = Field(description="One of: low, moderate, high, critical")


class AI:
    @staticmethod
    def ask(
        prompt: str,
        schema: Type[BaseModel],
        model: str | None = None,
        temperature: float = 0.3,
    ) -> dict:
        """
        Send a prompt to the configured default AI provider (with failover)
        and return structured output as a dict.
        """

        def _run(provider) -> dict:
            pydantic_model, model_settings = build_pydantic_model(provider, model)
            agent_kwargs = {"output_type": schema}
            if model_settings is not None:
                agent_kwargs["model_settings"] = model_settings

            agent: Agent = Agent(pydantic_model, **agent_kwargs)
            result = agent.run_sync(user_prompt=prompt)
            output = result.output
            if isinstance(output, BaseModel):
                return output.model_dump()
            return dict(output)

        data, _provider = run_with_failover(_run, model_name=model)
        return data

    @staticmethod
    def generate_image(prompt: str, aspect_ratio: str = "16:9") -> bytes:
        """
        Generate an image using Google Imagen via an enabled Google AiProvider.
        """
        provider = get_google_provider_for_images()
        client = build_google_genai_client(provider)

        try:
            response = client.models.generate_images(
                model=Constants.AI_PROVIDER_IMAGE_MODEL,
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

        result = AI.ask(prompt=prompt, schema=ArticleResponse)
        return ArticleResponse(**result)
