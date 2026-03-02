# Recipe Enhancement Platform — Quality Assessment

**Author**: Engineering Assessment Review  
**Date**: 2026-03-01  
**Pipeline Version**: 1.0.0

---

## 1. Codebase Summary

### What each file does

| File | Purpose |
|------|---------|
| `src/llm_pipeline/models.py` | Pydantic v2 models for the entire data flow: `ModificationEdit`, `ModificationObject`, `Recipe`, `Review`, `ChangeRecord`, `ModificationApplied`, `EnhancementSummary`, `EnhancedRecipe` |
| `src/llm_pipeline/prompts.py` | LLM prompt templates (`SYSTEM_PROMPT`, `EXTRACTION_PROMPT`), few-shot examples, and two builder functions (`build_simple_prompt`, `build_few_shot_prompt`) |
| `src/llm_pipeline/tweak_extractor.py` | **Step 1** — Sends a review + recipe to GPT-4o-mini and parses the `ModificationObject` JSON response. Has retry logic on JSON/validation failures |
| `src/llm_pipeline/recipe_modifier.py` | **Step 2** — Applies a `ModificationObject` to a recipe using fuzzy string matching (`difflib.SequenceMatcher`). Supports `replace`, `add_after`, `remove` operations |
| `src/llm_pipeline/enhanced_recipe_generator.py` | **Step 3** — Combines the modified recipe with attribution data to produce an `EnhancedRecipe`, saves to JSON |
| `src/llm_pipeline/pipeline.py` | **Orchestrator** — Loads JSON, parses `Recipe` + `Review` objects, drives Steps 1–3, saves output, generates summary report |
| `src/test_pipeline.py` | CLI entry point: `single` (chocolate chip cookies) or `all` (all 6 recipes) |
| `src/test_logic.py` | *(New)* Logic test harness — validates all non-LLM components without requiring an API key |
| `src/scraper_v2.py` | BeautifulSoup + requests scraper for AllRecipes.com (not part of the enhancement pipeline) |

---

## 2. Data Schema

### Input: Recipe JSON (`data/recipe_<id>_<slug>.json`)

```json
{
  "recipe_id": "10813",
  "title": "Best Chocolate Chip Cookies",
  "description": "...",
  "ingredients": ["1 cup butter, softened", "..."],
  "instructions": ["Preheat oven to 350°F", "..."],
  "servings": "48",
  "preptime": "PT20M",
  "cooktime": "PT10M",
  "totaltime": "PT30M",
  "rating": { "value": "4.6", "count": "19353" },
  "featured_tweaks": [
    {
      "text": "I added an extra egg yolk...",
      "rating": 5,
      "has_modification": true,
      "is_featured": true
    }
  ],
  "reviews": [ ... ]
}
```

**Key distinction**: `featured_tweaks` are curated `has_modification: true` entries with an `is_featured` flag. The plain `reviews` array may contain the same texts but is noisier.

### A review with `has_modification: true`

```json
{
  "text": "I used a half cup of sugar and one-and-a-half cups of brown sugar...",
  "rating": 5,
  "has_modification": true,
  "is_featured": true
}
```

### Output: Enhanced Recipe JSON (`data/enhanced/enhanced_<id>_<slug>.json`)

```json
{
  "recipe_id": "10813_enhanced",
  "original_recipe_id": "10813",
  "title": "Best Chocolate Chip Cookies (Community Enhanced)",
  "ingredients": ["1 cup butter, softened", "0.5 cup white sugar", ...],
  "instructions": [...],
  "modifications_applied": [
    {
      "source_review": { "text": "...", "reviewer": null, "rating": 5 },
      "modification_type": "quantity_adjustment",
      "reasoning": "Increases brown sugar for chewier texture",
      "changes_made": [
        { "type": "ingredient", "from_text": "1 cup white sugar",
          "to_text": "0.5 cup white sugar", "operation": "replace" }
      ]
    }
  ],
  "enhancement_summary": {
    "total_changes": 2,
    "change_types": ["quantity_adjustment"],
    "expected_impact": "Chewier texture..."
  },
  "created_at": "2026-03-01T19:22:00",
  "pipeline_version": "1.0.0"
}
```

---

## 3. Pipeline Flow

```
Input JSON file
      │
      ▼
[parse_recipe_data] → Recipe object
[parse_reviews_data] ─┐
  • reads featured_tweaks first │ → List[Review]
  • falls back to reviews       ┘
      │
      ▼ filter: has_modification == true
      │
      ▼ random.choice (one review selected)
      │
  ┌───────────────────────────────────────────────┐
  │  Step 1: TweakExtractor                       │
  │  build_simple_prompt(review, recipe) → LLM   │
  │  GPT-4o-mini (JSON mode, temp=0.1)            │
  │  parse → ModificationObject                   │
  └───────────────────────────────────────────────┘
      │
      ▼
  ┌───────────────────────────────────────────────┐
  │  Step 2: RecipeModifier                       │
  │  For each ModificationEdit:                   │
  │    fuzzy match edit.find against recipe lines │
  │    apply: replace / add_after / remove        │
  │  Returns: modified Recipe + List[ChangeRecord]│
  └───────────────────────────────────────────────┘
      │
      ▼
  ┌───────────────────────────────────────────────┐
  │  Step 3: EnhancedRecipeGenerator             │
  │  Combines modified recipe + source citation   │
  │  Returns: EnhancedRecipe with attribution    │
  └───────────────────────────────────────────────┘
      │
      ▼
Save: data/enhanced/enhanced_<id>_<slug>.json
```

---

## 4. Bugs Found & Fixed

### Bug 1 — Wrong LLM Model *(High)*
**File**: `tweak_extractor.py:24`  
**Fix**: Changed default from `"gpt-3.5-turbo"` → `"gpt-4o-mini"`.  
**Impact**: Without this fix, every LLM call used the wrong (cheaper, less capable) model, producing lower-quality extractions inconsistent with the spec.

---

### Bug 2 — Pipeline Ignored `featured_tweaks`, Read `reviews` Instead *(Critical)*
**File**: `pipeline.py:parse_reviews_data()`  
**Root Cause**: `recipe_data.get("reviews", [])` — the raw `reviews` list lacks the `is_featured` curation and has a different signal-to-noise ratio. The platform's purpose is to process "Featured Tweaks" specifically.  
**Fix**: Now prefers `featured_tweaks`; falls back to `reviews` only when absent. This also means `parse_reviews_data` always returns reviews that have `has_modification: true` set, since `featured_tweaks` entries all have it.

---

### Bug 3 — Fuzzy-Match `replace` Was Silently a No-op *(Critical)*
**File**: `recipe_modifier.py:apply_edit()`  
**Root Cause**: After fuzzy-matching to find the closest recipe line, the code ran `original_text.replace(edit.find, edit.replace)` — Python's `str.replace()`, which requires an **exact substring**. But since fuzzy matching found a *similar-but-not-identical* line, the substring wasn't present, so `str.replace` returned the unchanged original. The line was written back unmodified, no error raised, no log warning.

Example:
```
edit.find = "1 cup brown sugar"          ← LLM's version
actual line = "1 cup packed brown sugar" ← actual recipe
# str.replace finds no match → silently returns "1 cup packed brown sugar"
```

**Fix**: After a successful fuzzy match, replace the **entire matched list element** with `edit.replace`. This is semantically correct: the fuzzy match identifies *which line to swap*, and the replacement is the new full line value.

---

### Bug 4 — `save_enhanced_recipe` Crashed When No Directory in Path *(High)*
**File**: `enhanced_recipe_generator.py:save_enhanced_recipe()`  
**Root Cause**: `os.makedirs(os.path.dirname(output_path))` — `os.path.dirname("filename.json")` returns `""`, and `os.makedirs("", exist_ok=True)` raises `FileNotFoundError`.  
**Fix**: Guard: `if dir_name: os.makedirs(dir_name, exist_ok=True)`.

---

### Bug 5 — Output Saved to Wrong Directory *(Medium)*
**Files**: `pipeline.py`, `test_pipeline.py`  
**Root Cause**: `output_dir` defaulted to the relative string `"data/enhanced"`, which resolves relative to the CWD. When `test_pipeline.py` is run from `src/`, this creates `src/data/enhanced/` instead of the project-root `data/enhanced/`. Separately, `test_pipeline.py` used `"../data"` as a relative path which only works from `src/`.  
**Fix**: Both files now resolve all paths relative to their `__file__` location using `Path(__file__).resolve().parent`, making them CWD-independent.

---

### Bug 6 — Schema Mismatch: `confidence_score` in Output, Missing from Models *(Low)*
**File**: `models.py`  
**Fix**: Added `confidence_score: Optional[float] = None` to both `ModificationApplied` and `EnhancementSummary`. Existing output files now deserialise without issues.

---

### Bug 7 — `Optional` Fields Without `default=None` (Latent) *(Medium)*
**File**: `models.py:EnhancedRecipe`  
**Root Cause**: `description`, `servings`, `prep_time`, `cook_time`, `total_time` were typed `Optional[str]` but had no `default`, so Pydantic v2 still required them to be passed at construction. Any code constructing `EnhancedRecipe` without these fields would raise a `ValidationError`.  
**Fix**: Added `default=None` to all five fields.

---

## 5. Design Assessment & Improvement Recommendations

### 5.1 Non-determinism
The pipeline calls `random.choice()` to select one review per recipe. This means:
- Repeated runs produce different outputs from the same input
- Integration tests are flaky
- Debugging is harder

**Recommendation**: Accept the review selection as a parameter, or sort by rating descending and pick the top review. A `seed` argument could be added for reproducibility in testing.

### 5.2 Processing Only One Review per Recipe
The current pipeline extracts a single modification from one randomly-chosen review. The `featured_tweaks` for the chocolate chip cookies recipe has 4 highly-rated, multi-point tweaks that the platform currently throws away.

**Recommendation**: For each recipe, apply *all* `featured_tweaks` modifications sequentially using the existing `apply_modifications_batch()` method (already implemented in `RecipeModifier` but not called by the pipeline). This would require accumulating multiple `ModificationApplied` records.

### 5.3 Prompt Uses Only 2 of 4 Few-Shot Examples
`build_few_shot_prompt()` slices `FEW_SHOT_EXAMPLES[:2]` but 4 examples are defined. The `build_simple_prompt()` (which is what the pipeline actually uses) has zero examples.

**Recommendation**: Either commit to standard few-shot prompting (`build_few_shot_prompt`) or consider structured output via the OpenAI `response_format` with a Pydantic schema, which is more robust than asking the model to match a JSON schema described in text.

### 5.4 No Rate Limiting or Backoff
`TweakExtractor` makes synchronous OpenAI calls with only 2 retries and no exponential backoff. At scale this will hit rate limits.

**Recommendation**: Add `tenacity` with exponential backoff for transient API errors. For large batches, consider async processing with `asyncio` + `openai.AsyncOpenAI`.

### 5.5 Similarity Threshold Is a Magic Number
`RecipeModifier` is initialised with `similarity_threshold=0.6`. This is hardcoded and untested against real LLM output patterns.

**Recommendation**: Lower thresholds accept false positive matches; higher thresholds reject valid ones. A threshold of `0.6` is arbitrarily low — a proper calibration study against LLM extraction results would be valuable. In the meantime, raising it to `0.75` and logging all fuzzy matches below `0.9` would surface quality issues.

### 5.6 Scalability Path
For a production system scaling beyond the 5 sample recipes:
1. **Parallelism**: Process recipes concurrently using `asyncio.gather()` or `concurrent.futures.ProcessPoolExecutor`
2. **Persistence**: Store results in a database (SQLite → Postgres) instead of flat JSON files
3. **Idempotency**: Check if an enhanced version already exists before reprocessing
4. **Observability**: Structured logging with correlation IDs per recipe; track LLM token spend per recipe
5. **Prompt versioning**: Pin prompt templates to versions so recipe outputs remain reproducible after prompt changes

---

## 6. Deliverables Summary

| Item | Status |
|------|--------|
| Bug 1: Wrong model name | ✅ Fixed |
| Bug 2: Wrong review source field | ✅ Fixed |
| Bug 3: Fuzzy-match replace no-op | ✅ Fixed |
| Bug 4: `makedirs("")` crash | ✅ Fixed |
| Bug 5: CWD-relative paths | ✅ Fixed |
| Bug 6: `confidence_score` schema mismatch | ✅ Fixed |
| Bug 7: `Optional` fields missing `default=None` | ✅ Fixed |
| `.env.example` template | ✅ Added |
| Logic test harness (`test_logic.py`) | ✅ Added (9/9 passing) |
| Quality assessment document | ✅ This document |
