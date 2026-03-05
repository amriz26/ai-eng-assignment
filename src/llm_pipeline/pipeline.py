"""
Recipe Enhancement Pipeline — Application Orchestrator

This is the main entry point for the Recipe Enhancement Platform.
It coordinates the 3-step LLM-based analysis and modification pipeline.
"""

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from dotenv import load_dotenv
from loguru import logger

from .enhanced_recipe_generator import EnhancedRecipeGenerator
from .models import EnhancedRecipe, Recipe, Review
from .recipe_modifier import RecipeModifier
from .tweak_extractor import TweakExtractor


class LLMAnalysisPipeline:
    """Orchestrates the complete recipe enhancement pipeline."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        output_dir: Optional[str] = None,
        model: str = "gpt-4o-mini",
    ):
        """
        Initialize the pipeline.

        Args:
            api_key: OpenAI API key
            output_dir: Directory for storing enhanced recipes
            model: Model to use for tweak extraction
        """
        # Load .env from project root
        project_root = Path(__file__).resolve().parent.parent.parent
        load_dotenv(project_root / ".env")

        self.tweak_extractor = TweakExtractor(api_key=api_key, model=model)
        self.recipe_modifier = RecipeModifier(similarity_threshold=0.6)
        self.enhanced_generator = EnhancedRecipeGenerator(version="2.0.0")

        # Bug 5 fix: resolve output_dir relative to project root
        if output_dir:
            self.output_dir = Path(output_dir).resolve()
        else:
            self.output_dir = project_root / "data" / "enhanced"

        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        # Tracking for summary report
        self.processing_stats = {
            "total_recipes": 0,
            "successful_enhancements": 0,
            "failed_enhancements": 0,
            "total_modifications_applied": 0,
            "recipe_details": []
        }

        logger.info(f"Initialized LLM Analysis Pipeline v2.0.0")
        logger.info(f"Output directory: {self.output_dir}")

    def load_recipe_data(self, recipe_file: str) -> Dict[str, Any]:
        """Load raw recipe JSON data."""
        with open(recipe_file, "r") as f:
            return json.load(f)

    def parse_recipe_data(self, recipe_data: Dict[str, Any]) -> Recipe:
        """Parse raw dictionary into Recipe model."""
        return Recipe(
            recipe_id=recipe_data.get("recipe_id", "unknown"),
            title=recipe_data.get("title", "Unknown Recipe"),
            ingredients=recipe_data.get("ingredients", []),
            instructions=recipe_data.get("instructions", []),
            description=recipe_data.get("description"),
            servings=recipe_data.get("servings"),
            rating=recipe_data.get("rating"),
        )

    def parse_reviews_data(self, recipe_data: Dict[str, Any]) -> List[Review]:
        """
        Parse raw review data into Review objects.
        Prefers featured_tweaks over generic reviews.
        """
        raw_reviews = recipe_data.get("featured_tweaks") or recipe_data.get("reviews", [])
        reviews = []
        for review_data in raw_reviews:
            if review_data.get("text"):
                reviews.append(Review(
                    text=review_data["text"],
                    rating=review_data.get("rating"),
                    username=review_data.get("username"),
                    has_modification=review_data.get("has_modification", False),
                ))
        return reviews

    def process_single_recipe(
        self, recipe_file: str, save_output: bool = True
    ) -> Optional[EnhancedRecipe]:
        """
        Process a single recipe through the complete pipeline.
        Includes Phase 2: multi-review, multi-modification processing.
        """
        self.processing_stats["total_recipes"] += 1
        recipe_title = "Unknown"
        
        try:
            logger.info(f"Processing recipe file: {recipe_file}")
            recipe_data = self.load_recipe_data(recipe_file)
            recipe = self.parse_recipe_data(recipe_data)
            recipe_title = recipe.title
            
            reviews = self.parse_reviews_data(recipe_data)
            logger.info(f"Loaded recipe: {recipe.title}. Found {len(reviews)} reviews.")

            # Step 1: Select top reviews (Rating-sorted descending)
            top_reviews = self.tweak_extractor.select_top_reviews(reviews, limit=3)
            
            if not top_reviews:
                logger.warning(f"No reviews with modifications found for {recipe.title}")
                self.processing_stats["failed_enhancements"] += 1
                return None

            # Step 2: Extract and apply modifications from each top review
            all_applied_data = [] # List of (mod_obj, review, changes)
            current_modified_recipe = recipe.model_copy(deep=True)
            
            for review in top_reviews:
                logger.debug(f"Extracting from review by {review.username or 'anonymous'}")
                modifications = self.tweak_extractor.extract_modifications(review, current_modified_recipe)
                
                for mod in modifications:
                    # Apply all edits inside this modification
                    change_records = []
                    for edit in mod.edits:
                        new_modified_recipe, records = self.recipe_modifier.apply_edit(
                            edit, current_modified_recipe, mod.reasoning
                        )
                        current_modified_recipe = new_modified_recipe
                        change_records.extend(records)
                    
                    all_applied_data.append((mod, review, change_records))
                    self.processing_stats["total_modifications_applied"] += 1

            if not all_applied_data:
                logger.warning(f"No actionable modifications extracted for {recipe.title}")
                self.processing_stats["failed_enhancements"] += 1
                return None

            # Step 3: Generate final enhanced recipe
            enhanced_recipe = self.enhanced_generator.generate_enhanced_recipe(
                recipe, current_modified_recipe, all_applied_data
            )

            if save_output:
                filename = f"enhanced_{recipe.recipe_id}_{recipe.title.lower().replace(' ', '-')[:30]}.json"
                self.enhanced_generator.save_enhanced_recipe(enhanced_recipe, str(self.output_dir / filename))

            self.processing_stats["successful_enhancements"] += 1
            self.processing_stats["recipe_details"].append({
                "recipe_id": recipe.recipe_id,
                "title": recipe.title,
                "modifications_count": len(all_applied_data),
                "success": True
            })
            return enhanced_recipe

        except Exception as e:
            logger.error(f"Failed to process recipe {recipe_file}: {e}")
            self.processing_stats["failed_enhancements"] += 1
            self.processing_stats["recipe_details"].append({
                "recipe_file": recipe_file,
                "title": recipe_title,
                "error": str(e),
                "success": False
            })
            return None

    def process_recipe_directory(self, data_dir: Optional[str] = None):
        """Process all recipes in the specified directory."""
        if not data_dir:
            project_root = Path(__file__).resolve().parent.parent.parent
            data_dir = project_root / "data"
        else:
            data_dir = Path(data_dir).resolve()

        recipe_files = sorted(list(data_dir.glob("recipe_*.json")))
        logger.info(f"Processing {len(recipe_files)} recipes from {data_dir}")

        for recipe_file in recipe_files:
            self.process_single_recipe(str(recipe_file))

        self.save_summary_report()

    def save_summary_report(self):
        """Generate and save the pipeline summary report."""
        report_path = self.output_dir.parent / "pipeline_summary_report.json"
        
        # Summary calculations
        report = {
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "pipeline_version": "2.0.0",
            "stats": {
                "total_recipes": self.processing_stats["total_recipes"],
                "successful": self.processing_stats["successful_enhancements"],
                "failed": self.processing_stats["failed_enhancements"],
                "total_modifications_applied": self.processing_stats["total_modifications_applied"]
            },
            "recipes": self.processing_stats["recipe_details"]
        }
        
        with open(report_path, "w") as f:
            json.dump(report, f, indent=2)
            
        logger.info(f"Pipeline summary report saved to: {report_path}")
