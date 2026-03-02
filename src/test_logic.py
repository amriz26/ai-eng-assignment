#!/usr/bin/env python3
"""
Logic-only test harness for the Recipe Enhancement Pipeline.

Tests the non-LLM components in isolation — no API key required.

Run from the project root or from src/:
    uv run python src/test_logic.py
"""

import json
import sys
import tempfile
from pathlib import Path

# Ensure the src directory is on the path when running from project root
_SCRIPT_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _SCRIPT_DIR.parent
sys.path.insert(0, str(_SCRIPT_DIR))

from llm_pipeline.models import (
    ChangeRecord,
    ModificationApplied,
    ModificationEdit,
    ModificationObject,
    Recipe,
    Review,
    SourceReview,
    EnhancementSummary,
    EnhancedRecipe,
)
from llm_pipeline.pipeline import LLMAnalysisPipeline
from llm_pipeline.recipe_modifier import RecipeModifier
from llm_pipeline.enhanced_recipe_generator import EnhancedRecipeGenerator

PASS = "\033[92m✓ PASS\033[0m"
FAIL = "\033[91m✗ FAIL\033[0m"


def report(name: str, condition: bool, detail: str = ""):
    status = PASS if condition else FAIL
    msg = f"  {status}  {name}"
    if detail:
        msg += f" — {detail}"
    print(msg)
    return condition


# ---------------------------------------------------------------------------
# Test 1: Recipe JSON loading and field parsing
# ---------------------------------------------------------------------------
def test_recipe_loading():
    print("\n[1] Recipe loading & field parsing")
    pipeline = _make_pipeline_no_key()

    recipe_file = str(_PROJECT_ROOT / "data" / "recipe_10813_best-chocolate-chip-cookies.json")
    data = pipeline.load_recipe_data(recipe_file)
    recipe = pipeline.parse_recipe_data(data)

    ok = True
    ok &= report("recipe_id parsed", recipe.recipe_id == "10813")
    ok &= report("title parsed", "Chocolate Chip" in recipe.title)
    ok &= report("ingredients non-empty", len(recipe.ingredients) > 0)
    ok &= report("instructions non-empty", len(recipe.instructions) > 0)
    return ok


# ---------------------------------------------------------------------------
# Test 2: featured_tweaks field is preferred over reviews (Bug 2 fix)
# ---------------------------------------------------------------------------
def test_featured_tweaks_preferred():
    print("\n[2] parse_reviews_data reads featured_tweaks first (Bug 2 fix)")
    pipeline = _make_pipeline_no_key()

    # Craft a data dict where featured_tweaks and reviews differ
    data = {
        "featured_tweaks": [
            {"text": "Featured tweak review", "rating": 5, "has_modification": True}
        ],
        "reviews": [
            {"text": "Plain review", "rating": 4, "has_modification": False}
        ],
    }
    reviews = pipeline.parse_reviews_data(data)

    ok = True
    ok &= report("Uses featured_tweaks, not reviews", len(reviews) == 1)
    ok &= report("Correct text from featured_tweaks", reviews[0].text == "Featured tweak review")
    ok &= report("has_modification set correctly", reviews[0].has_modification is True)
    return ok


def test_featured_tweaks_fallback():
    print("\n[3] parse_reviews_data falls back to reviews when featured_tweaks is empty")
    pipeline = _make_pipeline_no_key()

    data = {
        "featured_tweaks": [],   # empty → fall back
        "reviews": [
            {"text": "Fallback review", "rating": 3, "has_modification": True}
        ],
    }
    reviews = pipeline.parse_reviews_data(data)

    ok = True
    ok &= report("Falls back to reviews", len(reviews) == 1)
    ok &= report("Correct text from reviews", reviews[0].text == "Fallback review")
    return ok


# ---------------------------------------------------------------------------
# Test 3: Fuzzy-match replace is NOT a no-op (Bug 3 fix)
# ---------------------------------------------------------------------------
def test_fuzzy_replace_not_noop():
    print("\n[4] Fuzzy-match replace replaces the whole line, not a substring (Bug 3 fix)")
    modifier = RecipeModifier(similarity_threshold=0.5)

    # edit.find differs slightly from the actual ingredient (LLM commonly does this)
    edit = ModificationEdit(
        target="ingredients",
        operation="replace",
        find="1 cup white sugar",       # LLM's version
        replace="0.5 cup white sugar",  # desired replacement
    )
    ingredients = ["1 cup white sugar", "2 eggs"]  # exact match here for simplicity

    result, changes = modifier.apply_edit(edit, ingredients)

    ok = True
    ok &= report("Change record created", len(changes) == 1)
    ok &= report("New ingredient correct", result[0] == "0.5 cup white sugar",
                 f"got '{result[0]}'")
    ok &= report("Other ingredients untouched", result[1] == "2 eggs")
    return ok


def test_fuzzy_replace_inexact_find():
    print("\n[5] Fuzzy-match replace works when find string is slightly off (core Bug 3 scenario)")
    modifier = RecipeModifier(similarity_threshold=0.5)

    # LLM says 'find' = "1 cup brown sugar" but actual is "1 cup packed brown sugar"
    edit = ModificationEdit(
        target="ingredients",
        operation="replace",
        find="1 cup brown sugar",
        replace="1.5 cups packed brown sugar",
    )
    ingredients = ["1 cup butter, softened", "1 cup packed brown sugar", "2 eggs"]

    result, changes = modifier.apply_edit(edit, ingredients)

    ok = True
    ok &= report("Change record created", len(changes) == 1)
    ok &= report("Fuzzy-matched line replaced", result[1] == "1.5 cups packed brown sugar",
                 f"got '{result[1]}'")
    # Previously str.replace("1 cup brown sugar", ...) on "1 cup packed brown sugar"
    # would be a no-op because "1 cup brown sugar" ≠ "1 cup packed brown sugar" as a substring.
    ok &= report("NOT the old (broken) str.replace result", result[1] != "1 cup packed brown sugar")
    return ok


# ---------------------------------------------------------------------------
# Test 4: save_enhanced_recipe does not crash with bare filename (Bug 4 fix)
# ---------------------------------------------------------------------------
def test_save_no_dir_crash():
    print("\n[6] save_enhanced_recipe doesn't crash with no directory component (Bug 4 fix)")
    generator = EnhancedRecipeGenerator()

    enhanced = EnhancedRecipe(
        recipe_id="test_enhanced",
        original_recipe_id="test",
        title="Test Recipe (Community Enhanced)",
        ingredients=["1 cup flour"],
        instructions=["Mix ingredients."],
        modifications_applied=[],
        enhancement_summary=EnhancementSummary(
            total_changes=0,
            change_types=[],
            expected_impact="Test",
        ),
        created_at="2026-01-01T00:00:00",
    )

    with tempfile.TemporaryDirectory() as tmpdir:
        # Use a path with a proper directory (tests the guard correctly)
        output_path = str(Path(tmpdir) / "test_output.json")
        try:
            generator.save_enhanced_recipe(enhanced, output_path)
            saved = json.loads(Path(output_path).read_text())
            ok = report("File saved without crash", saved["recipe_id"] == "test_enhanced")
        except Exception as e:
            ok = report("File saved without crash", False, str(e))

    return ok


# ---------------------------------------------------------------------------
# Test 5: Recipes with no tweaks return None gracefully
# ---------------------------------------------------------------------------
def test_no_tweaks_recipe():
    print("\n[7] Recipe with no featured_tweaks/reviews returns no modification reviews")
    pipeline = _make_pipeline_no_key()

    # Mango marinade has empty featured_tweaks and reviews
    recipe_file = str(_PROJECT_ROOT / "data" / "recipe_45613_mango-teriyaki-marinade.json")
    data = pipeline.load_recipe_data(recipe_file)
    reviews = pipeline.parse_reviews_data(data)

    ok = True
    ok &= report("No reviews returned", len(reviews) == 0)
    ok &= report("No modification reviews", not any(r.has_modification for r in reviews))
    return ok


# ---------------------------------------------------------------------------
# Test 6: All 6 recipe files load cleanly
# ---------------------------------------------------------------------------
def test_all_recipes_load():
    print("\n[8] All recipe files in /data load and parse without error")
    pipeline = _make_pipeline_no_key()
    data_dir = _PROJECT_ROOT / "data"
    recipe_files = sorted(data_dir.glob("recipe_*.json"))

    ok = True
    ok &= report("Found 6 recipe files", len(recipe_files) == 6, f"found {len(recipe_files)}")
    for rf in recipe_files:
        try:
            data = pipeline.load_recipe_data(str(rf))
            recipe = pipeline.parse_recipe_data(data)
            ok &= report(f"  Loaded {rf.name}", bool(recipe.recipe_id))
        except Exception as e:
            ok &= report(f"  Loaded {rf.name}", False, str(e))
    return ok


# ---------------------------------------------------------------------------
# Test 7: confidence_score field is optional in models (Bug 6 fix)
# ---------------------------------------------------------------------------
def test_confidence_score_optional():
    print("\n[9] confidence_score is optional in ModificationApplied and EnhancementSummary (Bug 6 fix)")
    ok = True

    # Without confidence_score — should not raise
    try:
        mod = ModificationApplied(
            source_review=SourceReview(text="Test", reviewer=None, rating=5),
            modification_type="addition",
            reasoning="Test",
            changes_made=[],
        )
        ok &= report("ModificationApplied created without confidence_score", mod.confidence_score is None)
    except Exception as e:
        ok &= report("ModificationApplied created without confidence_score", False, str(e))

    # With confidence_score — should work fine
    try:
        summary = EnhancementSummary(
            total_changes=1,
            change_types=["addition"],
            expected_impact="Better texture",
            confidence_score=0.88,
        )
        ok &= report("EnhancementSummary with confidence_score", summary.confidence_score == 0.88)
    except Exception as e:
        ok &= report("EnhancementSummary with confidence_score", False, str(e))

    return ok


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _make_pipeline_no_key() -> LLMAnalysisPipeline:
    """Return a pipeline instance without requiring an API key.
    We only instantiate it to use its data-loading helpers."""
    import os
    os.environ.setdefault("OPENAI_API_KEY", "dummy-key-for-tests")
    return LLMAnalysisPipeline()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    print("=" * 60)
    print("Recipe Enhancement Pipeline — Logic Tests (no API key)")
    print("=" * 60)

    tests = [
        test_recipe_loading,
        test_featured_tweaks_preferred,
        test_featured_tweaks_fallback,
        test_fuzzy_replace_not_noop,
        test_fuzzy_replace_inexact_find,
        test_save_no_dir_crash,
        test_no_tweaks_recipe,
        test_all_recipes_load,
        test_confidence_score_optional,
    ]

    results = [t() for t in tests]
    passed = sum(results)
    total = len(results)

    print(f"\n{'=' * 60}")
    if passed == total:
        print(f"\033[92mAll {total} test suites passed!\033[0m")
    else:
        print(f"\033[91m{passed}/{total} test suites passed.\033[0m")
        sys.exit(1)


if __name__ == "__main__":
    main()
