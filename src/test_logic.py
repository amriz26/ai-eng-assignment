#!/usr/bin/env python3
"""
Logic-only test harness for Phase 2 of the Recipe Enhancement Pipeline.
Validates multi-modification, rating-sorted selection, and enriched ChangeRecords.
"""

import json
import sys
import tempfile
from pathlib import Path

# Ensure the src directory is on the path
_SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_SCRIPT_DIR))

from llm_pipeline.models import (
    ChangeRecord,
    ModificationApplied,
    ModificationEdit,
    ModificationObject,
    Recipe,
    Review,
    SourceReview,
    ExtractionResult
)
from llm_pipeline.pipeline import LLMAnalysisPipeline
from llm_pipeline.recipe_modifier import RecipeModifier
from llm_pipeline.tweak_extractor import TweakExtractor
from llm_pipeline.enhanced_recipe_generator import EnhancedRecipeGenerator

PASS = "\033[92m✓ PASS\033[0m"
FAIL = "\033[91m✗ FAIL\033[0m"

def report(name: str, condition: bool, detail: str = ""):
    status = PASS if condition else FAIL
    msg = f"  {status}  {name}"
    if detail: msg += f" — {detail}"
    print(msg)
    return condition

# ---------------------------------------------------------------------------
# Test 1: select_top_reviews sorts by rating (Bug 2 Phase 2 fix)
# ---------------------------------------------------------------------------
def test_review_selection_sorting():
    print("\n[1] select_top_reviews sorts by rating descending")
    extractor = TweakExtractor(api_key="fake")
    
    reviews = [
        Review(text="Good", rating=3, has_modification=True),
        Review(text="Best", rating=5, has_modification=True),
        Review(text="Okay", rating=4, has_modification=True),
        Review(text="No Mod", rating=5, has_modification=False),
    ]
    
    selected = extractor.select_top_reviews(reviews, limit=2)
    
    ok = True
    ok &= report("Selected 2 reviews", len(selected) == 2)
    ok &= report("Highest rating first", selected[0].text == "Best")
    ok &= report("Second highest next", selected[1].text == "Okay")
    ok &= report("Filtered non-modification reviews", all(r.has_modification for r in selected))
    return ok

# ---------------------------------------------------------------------------
# Test 2: ExtractionResult handles multiple modifications
# ---------------------------------------------------------------------------
def test_extraction_result_model():
    print("\n[2] ExtractionResult Pydantic model validation")
    
    data = {
        "modifications": [
            {
                "modification_type": "addition",
                "reasoning": "Reason 1",
                "edits": [{"target": "ingredients", "operation": "replace", "find": "A", "replace": "B"}]
            },
            {
                "modification_type": "removal",
                "reasoning": "Reason 2",
                "edits": [{"target": "instructions", "operation": "remove", "find": "Step 1"}]
            }
        ]
    }
    
    try:
        result = ExtractionResult(**data)
        ok = report("ExtractionResult parsed successfully", len(result.modifications) == 2)
        ok &= report("Correct types preserved", result.modifications[0].modification_type == "addition")
    except Exception as e:
        ok = report("ExtractionResult parsing failed", False, str(e))
    return ok

# ---------------------------------------------------------------------------
# Test 3: apply_modifications_batch preserves history
# ---------------------------------------------------------------------------
def test_batch_modification():
    print("\n[3] RecipeModifier.apply_modifications_batch handles multiple mods")
    modifier = RecipeModifier(similarity_threshold=0.6)
    
    recipe = Recipe(
        recipe_id="test", title="Test", 
        ingredients=["1 cup sugar", "1 cup flour"], 
        instructions=["Bake."]
    )
    
    mods = [
        ModificationObject(
            modification_type="quantity_adjustment",
            reasoning="Less sugar",
            edits=[ModificationEdit(target="ingredients", operation="replace", find="1 cup sugar", replace="0.5 cup sugar")]
        ),
        ModificationObject(
            modification_type="addition",
            reasoning="Add salt",
            edits=[ModificationEdit(target="ingredients", operation="add_after", find="1 cup flour", add="1 tsp salt")]
        )
    ]
    
    new_recipe, records = modifier.apply_modifications_batch(recipe, mods)
    
    ok = True
    ok &= report("Recipe updated: ingredients count", len(new_recipe.ingredients) == 3)
    ok &= report("First mod applied", "0.5 cup sugar" in new_recipe.ingredients)
    ok &= report("Second mod applied", "1 tsp salt" in new_recipe.ingredients)
    ok &= report("Records created for all edits", len(records) == 2)
    ok &= report("Records include reasoning", records[0].reasoning == "Less sugar")
    return ok

# ---------------------------------------------------------------------------
# Test 4: Enriched ChangeRecord features
# ---------------------------------------------------------------------------
def test_enriched_change_records():
    print("\n[4] ChangeRecords include similarity scores and match status")
    modifier = RecipeModifier(similarity_threshold=0.8)
    
    # Fuzzy match scenario
    edit = ModificationEdit(target="ingredients", operation="replace", find="1 cup brown sugar", replace="1.5 cups")
    ingredients = ["1 cup packed brown sugar"]
    
    _, records = modifier._apply_to_list(edit, ingredients, "Fuzzy test")
    
    ok = True
    ok &= report("Record marked as matched", records[0].matched is True)
    ok &= report("Similarity score populated", records[0].similarity_score > 0.8)
    
    # Failed match scenario
    edit_fail = ModificationEdit(target="ingredients", operation="replace", find="Something else", replace="None")
    _, records_fail = modifier._apply_to_list(edit_fail, ingredients, "Fail test")
    
    ok &= report("Record marked as unmatched", records_fail[0].matched is False)
    ok &= report("Low similarity score recorded", records_fail[0].similarity_score < 0.5)
    
    return ok

# ---------------------------------------------------------------------------
# Test 5: Summary report generation
# ---------------------------------------------------------------------------
def test_pipeline_summary_stats():
    print("\n[5] Pipeline correctly tracks and summaries multiple modifications")
    
    import os
    os.environ["OPENAI_API_KEY"] = "fake"
    pipeline = LLMAnalysisPipeline()
    
    # Mocking some successful runs
    pipeline.processing_stats["total_recipes"] = 1
    pipeline.processing_stats["successful_enhancements"] = 1
    pipeline.processing_stats["total_modifications_applied"] = 3
    pipeline.processing_stats["recipe_details"].append({"title": "Test", "modifications_count": 3, "success": True})
    
    with tempfile.TemporaryDirectory() as tmpdir:
        pipeline.output_dir = Path(tmpdir)
        pipeline.save_summary_report()
        
        report_file = Path(tmpdir).parent / "pipeline_summary_report.json"
        
        ok = True
        if report_file.exists():
            data = json.loads(report_file.read_text())
            ok &= report("Summary report JSON structure", "stats" in data)
            ok &= report("Correct successful count", data["stats"]["successful"] == 1)
            ok &= report("Correct mods count", data["stats"]["total_modifications_applied"] == 3)
        else:
            ok = report("Summary report file exists", False)
            
    return ok

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    print("=" * 60)
    print("Recipe Enhancement Pipeline — Phase 2 Logic Tests")
    print("=" * 60)

    tests = [
        test_review_selection_sorting,
        test_extraction_result_model,
        test_batch_modification,
        test_enriched_change_records,
        test_pipeline_summary_stats,
    ]

    results = [t() for t in tests]
    passed = sum(results)
    total = len(results)

    print(f"\n{'=' * 60}")
    if passed == total:
        print(f"\033[92mAll {total} Phase 2 test suites passed!\033[0m")
    else:
        print(f"\033[91m{passed}/{total} test suites passed.\033[0m")
        sys.exit(1)

if __name__ == "__main__":
    main()
