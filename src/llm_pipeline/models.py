"""
Pydantic data models for the LLM Analysis Pipeline.

These models define the structure for recipe modifications, enhanced recipes,
and all intermediate data formats used throughout the pipeline.
"""

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


class ModificationEdit(BaseModel):
    """Individual atomic edit operation for a recipe modification."""

    target: Literal["ingredients", "instructions"] = Field(
        description="Whether this edit applies to ingredients or instructions"
    )
    operation: Literal["replace", "add_after", "remove"] = Field(
        default="replace",
        description="Type of operation: replace text, add after target, or remove",
    )
    find: str = Field(description="Text to find in the recipe")
    replace: Optional[str] = Field(
        default=None, description="Replacement text (required for replace operations)"
    )
    add: Optional[str] = Field(
        default=None, description="Text to add (required for add_after operations)"
    )


class ModificationObject(BaseModel):
    """One discrete structured modification parsed from a review.

    A single review may contain multiple independent modifications (e.g.
    "I halved the sugar AND added an egg yolk AND raised the temp"). Each
    distinct change should be its own ModificationObject.
    """

    modification_type: Literal[
        "ingredient_substitution",
        "quantity_adjustment",
        "technique_change",
        "addition",
        "removal",
    ] = Field(description="Category of modification")

    reasoning: str = Field(description="Why this modification improves the recipe")

    edits: List[ModificationEdit] = Field(description="List of atomic edits to apply")


class ExtractionResult(BaseModel):
    """Wrapper returned by the LLM for a single review.

    Wraps a list of ModificationObjects so one review can yield multiple
    independent modifications (e.g. sugar change + egg addition are two
    separate modifications, not one).

    If the review contains no actionable recipe changes, ``modifications``
    must be an empty list — do NOT invent changes.
    """

    modifications: List[ModificationObject] = Field(
        description=(
            "All discrete modifications extracted from this review. "
            "One item per distinct change. Empty list if no real changes found."
        )
    )


class SourceReview(BaseModel):
    """Reference to the original review that suggested the modification."""

    text: str = Field(description="Full text of the original review")
    reviewer: Optional[str] = Field(default=None, description="Username of the reviewer")
    rating: Optional[int] = Field(default=None, description="Star rating given by reviewer")


class ChangeRecord(BaseModel):
    """Record of a specific change made to the recipe."""

    type: Literal["ingredient", "instruction"] = Field(
        description="Type of element that was changed"
    )
    from_text: str = Field(description="Original text before modification")
    to_text: str = Field(description="New text after modification")
    operation: Literal["replace", "add", "remove"] = Field(
        description="Type of operation performed"
    )
    # Whether the fuzzy matcher actually found a match
    matched: bool = Field(
        default=True,
        description="True if the edit was successfully applied to the recipe",
    )
    similarity_score: Optional[float] = Field(
        default=None,
        description="Fuzzy similarity score of the match (0-1); None for add operations",
    )
    reasoning: Optional[str] = Field(
        default=None, description="Why this specific change was made (from ModificationObject)"
    )


class ModificationApplied(BaseModel):
    """Full record of a modification that was applied to a recipe."""

    source_review: SourceReview = Field(
        description="Review that suggested this modification"
    )
    modification_type: str = Field(description="Category of modification")
    reasoning: str = Field(description="Why this modification was applied")
    changes_made: List[ChangeRecord] = Field(
        description="Detailed list of changes made (includes unmatched edits for auditability)"
    )
    confidence_score: Optional[float] = Field(
        default=None, description="Confidence score for this modification (0-1)"
    )


class EnhancementSummary(BaseModel):
    """Summary of all modifications applied to a recipe."""

    total_changes: int = Field(description="Total number of changes successfully applied")
    failed_matches: int = Field(
        default=0,
        description="Number of edits that could not be matched to recipe text",
    )
    change_types: List[str] = Field(description="Types of modifications applied")
    expected_impact: str = Field(
        description="Expected improvement from these modifications"
    )
    confidence_score: Optional[float] = Field(
        default=None, description="Average confidence score across all modifications (0-1)"
    )
    reviews_processed: int = Field(
        default=1,
        description="Number of community reviews incorporated into this enhanced recipe",
    )


class EnhancedRecipe(BaseModel):
    """Recipe with community modifications applied and full attribution."""

    recipe_id: str = Field(description="Enhanced recipe ID")
    original_recipe_id: str = Field(description="ID of the original recipe")
    title: str = Field(description="Enhanced recipe title")

    # Enhanced recipe content
    ingredients: List[str] = Field(description="Modified ingredients list")
    instructions: List[str] = Field(description="Modified instructions list")

    # Attribution and tracking
    modifications_applied: List[ModificationApplied] = Field(
        description="Full record of all modifications applied"
    )
    enhancement_summary: EnhancementSummary = Field(
        description="Summary of all enhancements"
    )

    # Optional metadata
    description: Optional[str] = Field(default=None, description="Enhanced recipe description")
    servings: Optional[str] = Field(default=None, description="Number of servings")
    prep_time: Optional[str] = Field(default=None, description="Preparation time")
    cook_time: Optional[str] = Field(default=None, description="Cooking time")
    total_time: Optional[str] = Field(default=None, description="Total time")

    # Generation metadata
    created_at: str = Field(description="When this enhanced recipe was created")
    pipeline_version: str = Field(
        default="2.0.0", description="Version of the pipeline that created this"
    )


class Recipe(BaseModel):
    """Base recipe model for input data."""

    recipe_id: str
    title: str
    ingredients: List[str]
    instructions: List[str]
    description: Optional[str] = None
    servings: Optional[str] = None
    rating: Optional[Dict[str, Any]] = None
    # Include other fields as needed


class Review(BaseModel):
    """Review model for input data."""

    text: str
    rating: Optional[int] = None
    username: Optional[str] = None
    has_modification: bool = False
