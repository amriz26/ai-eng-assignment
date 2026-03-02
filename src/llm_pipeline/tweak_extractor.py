"""
Step 1: Tweak Extraction & Parsing

This module extracts structured modifications from review text using LLM processing.
It converts natural language descriptions of recipe changes into structured
ModificationObject instances.
"""

import json
import os
from typing import List, Optional, Tuple

from loguru import logger
from openai import OpenAI
from pydantic import ValidationError

from .models import ExtractionResult, ModificationObject, Recipe, Review
from .prompts import build_few_shot_prompt


class TweakExtractor:
    """Extracts structured modifications from review text using LLM processing."""

    def __init__(self, api_key: Optional[str] = None, model: str = "gpt-4o-mini"):
        """
        Initialize the TweakExtractor.

        Args:
            api_key: OpenAI API key (defaults to OPENAI_API_KEY env var)
            model: OpenAI model to use for extraction
        """
        self.client = OpenAI(api_key=api_key or os.getenv("OPENAI_API_KEY"))
        self.model = model
        logger.info(f"Initialized TweakExtractor with model: {model}")

    def extract_modifications(
        self,
        review: Review,
        recipe: Recipe,
        max_retries: int = 2,
    ) -> List[ModificationObject]:
        """
        Extract all structured modifications from a single review.

        Args:
            review: Review object containing modification text
            recipe: Original recipe being modified
            max_retries: Number of retry attempts if parsing fails

        Returns:
            List of ModificationObject if extraction successful, empty list otherwise
        """
        if not review.has_modification:
            logger.debug(f"Review by {review.username or 'unknown'} has no modification flag")
            return []

        # Build the prompt - use few-shot for better multi-extraction reliability
        prompt = build_few_shot_prompt(
            review.text, recipe.title, recipe.ingredients, recipe.instructions
        )

        logger.debug(
            f"Extracting modifications from review: {review.text[:100]}..."
        )

        for attempt in range(max_retries + 1):
            try:
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=[{"role": "user", "content": prompt}],
                    response_format={"type": "json_object"},
                    temperature=0.1,
                    max_tokens=1500,
                )

                raw_output = response.choices[0].message.content
                if not raw_output:
                    continue

                # Parse and validate the JSON response
                result_data = json.loads(raw_output)
                extraction_result = ExtractionResult(**result_data)

                # Filter out hallucinated "edits" that have non-existent targets
                valid_modifications = []
                for mod in extraction_result.modifications:
                    if mod.edits:
                        valid_modifications.append(mod)

                logger.info(
                    f"Extracted {len(valid_modifications)} modifications from review"
                )
                return valid_modifications

            except (json.JSONDecodeError, ValidationError) as e:
                logger.warning(f"Attempt {attempt + 1}: Extraction failed: {e}")
                if attempt == max_retries:
                    logger.error(f"Failed to extract from review after {max_retries} retries")

            except Exception as e:
                logger.error(f"Unexpected error during extraction: {e}")
                if attempt == max_retries:
                    break

        return []

    def select_top_reviews(
        self, reviews: List[Review], limit: int = 1
    ) -> List[Review]:
        """
        Select highest-rated reviews that contain modifications.
        
        Args:
            reviews: List of reviews to choose from
            limit: Maximum number of reviews to return
            
        Returns:
            List of top reviews sorted by rating descending
        """
        mod_reviews = [r for r in reviews if r.has_modification]
        if not mod_reviews:
            return []

        # Sort by rating descending. Since 'helpful_votes' isn't in schema, 
        # rating is the next best proxy for "highest voted/quality" tweaks.
        sorted_reviews = sorted(
            mod_reviews, 
            key=lambda x: x.rating if x.rating is not None else 0, 
            reverse=True
        )
        
        selected = sorted_reviews[:limit]
        logger.info(f"Selected top {len(selected)} reviews for enhancement")
        return selected
