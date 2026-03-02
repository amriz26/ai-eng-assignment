"""
Step 2: Recipe Modification & Fuzzy Matching

This module applies structured modifications to recipes using fuzzy string matching
to ensure edits are correctly mapped to original recipe text.
"""

from difflib import SequenceMatcher
from typing import List, Tuple

from loguru import logger

from .models import ChangeRecord, ModificationEdit, ModificationObject, Recipe


class RecipeModifier:
    """Applies structured modifications to recipes using fuzzy string matching."""

    def __init__(self, similarity_threshold: float = 0.6):
        """
        Initialize the RecipeModifier.

        Args:
            similarity_threshold: Minimum similarity score for fuzzy matching (0-1)
        """
        self.similarity_threshold = similarity_threshold
        logger.info(
            f"Initialized RecipeModifier with similarity threshold: {similarity_threshold}"
        )

    def apply_modifications_batch(
        self, recipe: Recipe, modifications: List[ModificationObject]
    ) -> Tuple[Recipe, List[ChangeRecord]]:
        """
        Apply a batch of modifications to a recipe.

        Args:
            recipe: Original recipe to modify
            modifications: List of structured modifications to apply

        Returns:
            Tuple of (Modified Recipe, List of ChangeRecords)
        """
        current_recipe = recipe.model_copy(deep=True)
        all_change_records = []

        for modification in modifications:
            logger.info(f"Applying modification: {modification.reasoning}")
            for edit in modification.edits:
                # Apply the edit or record a failure
                new_recipe, records = self.apply_edit(edit, current_recipe, modification.reasoning)
                current_recipe = new_recipe
                all_change_records.extend(records)

        return current_recipe, all_change_records

    def apply_edit(
        self, edit: ModificationEdit, recipe: Recipe, reasoning: str = ""
    ) -> Tuple[Recipe, List[ChangeRecord]]:
        """
        Apply a single atomic edit to a recipe.

        Args:
            edit: Atomic edit operation to apply
            recipe: Recipe to modify
            reasoning: Why the edit is being made (for the change record)

        Returns:
            Tuple of (Modified Recipe, List of ChangeRecords)
        """
        target_list = (
            recipe.ingredients if edit.target == "ingredients" else recipe.instructions
        )
        new_list, change_records = self._apply_to_list(edit, target_list, reasoning)

        # Update the recipe with the modified list
        if edit.target == "ingredients":
            recipe.ingredients = new_list
        else:
            recipe.instructions = new_list

        return recipe, change_records

    def _apply_to_list(
        self, edit: ModificationEdit, items: List[str], reasoning: str = ""
    ) -> Tuple[List[str], List[ChangeRecord]]:
        """
        Apply an edit to a list of strings (ingredients or instructions).
        """
        new_items = list(items)
        change_records = []

        # Find the best match for the edit's find text
        best_match_idx = -1
        best_match_score = 0.0

        if edit.operation != "add_after":
             # For replace and remove, we need an exact or fuzzy match
            for i, item in enumerate(items):
                score = SequenceMatcher(None, edit.find.lower(), item.lower()).ratio()
                if score > best_match_score:
                    best_match_score = score
                    best_match_idx = i

        # Perform the operation based on the best match found
        if edit.operation == "replace":
            if best_match_score >= self.similarity_threshold:
                original_text = new_items[best_match_idx]
                new_text = edit.replace or ""
                new_items[best_match_idx] = new_text
                
                logger.info(f"Replaced '{original_text}' with '{new_text}' (score: {best_match_score:.2f})")
                change_records.append(ChangeRecord(
                    type="ingredient" if "ingredient" in str(edit.target) else "instruction",
                    from_text=original_text,
                    to_text=new_text,
                    operation="replace",
                    matched=True,
                    similarity_score=best_match_score,
                    reasoning=reasoning
                ))
            else:
                logger.warning(f"Could not find a good match for replace: '{edit.find}' (best score: {best_match_score:.2f})")
                change_records.append(ChangeRecord(
                    type="ingredient" if "ingredient" in str(edit.target) else "instruction",
                    from_text=edit.find,
                    to_text=edit.replace or "",
                    operation="replace",
                    matched=False,
                    similarity_score=best_match_score,
                    reasoning=reasoning
                ))

        elif edit.operation == "remove":
            if best_match_score >= self.similarity_threshold:
                removed_text = new_items.pop(best_match_idx)
                logger.info(f"Removed '{removed_text}' (score: {best_match_score:.2f})")
                change_records.append(ChangeRecord(
                    type="ingredient" if "ingredient" in str(edit.target) else "instruction",
                    from_text=removed_text,
                    to_text="",
                    operation="remove",
                    matched=True,
                    similarity_score=best_match_score,
                    reasoning=reasoning
                ))
            else:
                logger.warning(f"Could not find a good match for remove: '{edit.find}' (best score: {best_match_score:.2f})")
                change_records.append(ChangeRecord(
                    type="ingredient" if "ingredient" in str(edit.target) else "instruction",
                    from_text=edit.find,
                    to_text="",
                    operation="remove",
                    matched=False,
                    similarity_score=best_match_score,
                    reasoning=reasoning
                ))

        elif edit.operation == "add_after":
            # For add_after, we also use fuzzy match to find the anchor
            for i, item in enumerate(items):
                score = SequenceMatcher(None, edit.find.lower(), item.lower()).ratio()
                if score > best_match_score:
                    best_match_score = score
                    best_match_idx = i

            if best_match_score >= self.similarity_threshold:
                new_text = edit.add or ""
                new_items.insert(best_match_idx + 1, new_text)
                logger.info(f"Added '{new_text}' after '{new_items[best_match_idx]}'")
                change_records.append(ChangeRecord(
                    type="ingredient" if "ingredient" in str(edit.target) else "instruction",
                    from_text=f"After: {new_items[best_match_idx]}",
                    to_text=new_text,
                    operation="add",
                    matched=True,
                    similarity_score=best_match_score,
                    reasoning=reasoning
                ))
            else:
                # Fallback: if we can't find the anchor, just append to the end
                new_text = edit.add or ""
                new_items.append(new_text)
                logger.warning(f"Could not find anchor for add_after: '{edit.find}'. Appended to end.")
                change_records.append(ChangeRecord(
                    type="ingredient" if "ingredient" in str(edit.target) else "instruction",
                    from_text=f"Anchor not found: {edit.find}",
                    to_text=new_text,
                    operation="add",
                    matched=False,
                    similarity_score=best_match_score,
                    reasoning=reasoning
                ))

        return new_items, change_records