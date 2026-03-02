"""
Step 3: Enhanced Recipe Generation & Attribution

This module generates the final enhanced recipe JSON, including full attribution
to the original reviewers and a summary of all modifications applied.
"""

import json
import os
from datetime import datetime
from typing import List, Tuple

from loguru import logger

from .models import (
    ChangeRecord,
    EnhancedRecipe,
    EnhancementSummary,
    ModificationApplied,
    ModificationObject,
    Recipe,
    Review,
    SourceReview,
)


class EnhancedRecipeGenerator:
    """Generates the final enhanced recipe with attribution and summary informatics."""

    def __init__(self, version: str = "2.0.0"):
        """
        Initialize the EnhancedRecipeGenerator.

        Args:
            version: Pipeline version to include in output
        """
        self.version = version
        logger.info(f"Initialized EnhancedRecipeGenerator v{version}")

    def generate_enhanced_recipe(
        self,
        original_recipe: Recipe,
        modified_recipe: Recipe,
        all_modifications: List[Tuple[ModificationObject, Review, List[ChangeRecord]]],
    ) -> EnhancedRecipe:
        """
        Generate a complete EnhancedRecipe object.

        Args:
            original_recipe: The recipe before any changes
            modified_recipe: The recipe after all changes applied
            all_modifications: List of (ModificationObject, SourceReview, applied_ChangeRecords)

        Returns:
            Fully populated EnhancedRecipe object
        """
        modifications_applied = []
        all_change_types = set()
        total_successful_changes = 0
        total_failed_matches = 0
        all_reasoning = []
        
        # Track which reviews contributed
        contributing_reviews = set()

        for mod_obj, source_review_obj, changes in all_modifications:
            contributing_reviews.add(source_review_obj.text)
            
            # Create the ModificationApplied record for this specific modification
            applied = ModificationApplied(
                source_review=SourceReview(
                    text=source_review_obj.text,
                    reviewer=source_review_obj.username,
                    rating=source_review_obj.rating,
                ),
                modification_type=mod_obj.modification_type,
                reasoning=mod_obj.reasoning,
                changes_made=changes,
                confidence_score=self._calculate_confidence(changes)
            )
            modifications_applied.append(applied)
            
            # Aggregate for the summary
            all_change_types.add(mod_obj.modification_type)
            all_reasoning.append(mod_obj.reasoning)
            
            total_successful_changes += sum(1 for c in changes if c.matched)
            total_failed_matches += sum(1 for c in changes if not c.matched)

        # Create the summary
        summary = EnhancementSummary(
            total_changes=total_successful_changes,
            failed_matches=total_failed_matches,
            change_types=list(all_change_types),
            expected_impact="; ".join(all_reasoning),
            confidence_score=self._calculate_avg_confidence(modifications_applied),
            reviews_processed=len(contributing_reviews)
        )

        return EnhancedRecipe(
            recipe_id=f"{original_recipe.recipe_id}_enhanced",
            original_recipe_id=original_recipe.recipe_id,
            title=f"{original_recipe.title} (Community Enhanced)",
            ingredients=modified_recipe.ingredients,
            instructions=modified_recipe.instructions,
            modifications_applied=modifications_applied,
            enhancement_summary=summary,
            description=original_recipe.description,
            servings=original_recipe.servings,
            created_at=datetime.now().isoformat(timespec="seconds"),
            pipeline_version=self.version,
        )

    def _calculate_confidence(self, changes: List[ChangeRecord]) -> float:
        """Calculate confidence score for a single modification based on fuzzy match scores."""
        if not changes:
            return 0.0
        
        scores = []
        for c in changes:
            if c.operation == "add":
                # Additions are considered high confidence if matched anchor
                scores.append(1.0 if c.matched else 0.5)
            elif c.matched:
                scores.append(c.similarity_score or 1.0)
            else:
                scores.append(0.0)
        
        return sum(scores) / len(scores)

    def _calculate_avg_confidence(self, applied: List[ModificationApplied]) -> float:
        """Calculate average confidence across all applied modifications."""
        if not applied:
            return 0.0
        scores = [a.confidence_score for a in applied if a.confidence_score is not None]
        return sum(scores) / len(scores) if scores else 0.0

    def save_enhanced_recipe(self, recipe: EnhancedRecipe, output_path: str) -> bool:
        """
        Save the enhanced recipe to a JSON file.

        Args:
            recipe: EnhancedRecipe to save
            output_path: Target file path

        Returns:
            True if successful, False otherwise
        """
        try:
            # Bug 4 fix: check if directory exists before creating
            dir_name = os.path.dirname(output_path)
            if dir_name:
                os.makedirs(dir_name, exist_ok=True)

            with open(output_path, "w") as f:
                json.dump(recipe.model_dump(), f, indent=2)

            logger.info(f"Saved enhanced recipe to: {output_path}")
            return True
        except Exception as e:
            logger.error(f"Failed to save enhanced recipe: {e}")
            return False
