"""
LLM prompts and examples for recipe modification extraction.

This module contains carefully crafted prompts for extracting structured
modifications from user review text.
"""

SYSTEM_PROMPT = """You are an expert recipe analyst. Your job is to extract structured recipe modifications from user reviews.

When a user shares their experience modifying a recipe, you need to:
1. Identify ALL discrete changes they made (ingredients, amounts, steps, etc.)
2. Understand why they made those changes
3. Convert their modifications into structured edit operations

One review may contain multiple independent modifications. For example:
"I halved the sugar AND added an egg yolk AND raised the oven temp."
This contains THREE discrete modifications:
1. Quantity adjustment (sugar)
2. Addition (egg yolk)
3. Technique change (oven temp)

You must output valid JSON that matches the ExtractionResult schema.

Categories for modification_type:
- "ingredient_substitution": Replacing one ingredient with another
- "quantity_adjustment": Changing amounts of existing ingredients
- "technique_change": Altering cooking method, temperature, time
- "addition": Adding new ingredients or steps
- "removal": Removing ingredients or steps

Edit operations:
- "replace": Find existing text and replace it with new text
- "add_after": Add new text after finding target text
- "remove": Remove text that matches the find pattern

Guidelines:
- If the review says "perfect as written" or has no actionable modifications, return an empty list of modifications.
- Be precise with text matching - use the exact text from the original recipe in the "find" field.
- If a change is mentioned as a suggestion but not actually performed, do NOT extract it.
- Focus on concrete changes."""

EXTRACTION_PROMPT = """Original Recipe:
Title: {title}
Ingredients: {ingredients}
Instructions: {instructions}

User Review: "{review_text}"

Extract all recipe modifications from this review.

Output a JSON object with this structure:
{{
    "modifications": [
        {{
            "modification_type": "category",
            "reasoning": "Brief explanation",
            "edits": [
                {{
                    "target": "ingredients|instructions",
                    "operation": "replace|add_after|remove",
                    "find": "exact text from recipe",
                    "replace": "new text",
                    "add": "new text"
                }}
            ]
        }}
    ]
}}

If no modifications are found, return {{"modifications": []}}."""

FEW_SHOT_EXAMPLES = [
    {
        "review": "I halved the white sugar and used 1.5 cups brown sugar instead. Also added an extra egg yolk. Turned out perfectly chewy!",
        "ingredients": [
            "1 cup white sugar",
            "1 cup packed brown sugar",
            "2 eggs"
        ],
        "expected_output": {
            "modifications": [
                {
                    "modification_type": "quantity_adjustment",
                    "reasoning": "Adjusts sugar ratio for better texture",
                    "edits": [
                        {
                            "target": "ingredients",
                            "operation": "replace",
                            "find": "1 cup white sugar",
                            "replace": "0.5 cup white sugar"
                        },
                        {
                            "target": "ingredients",
                            "operation": "replace",
                            "find": "1 cup packed brown sugar",
                            "replace": "1.5 cups packed brown sugar"
                        }
                    ]
                },
                {
                    "modification_type": "addition",
                    "reasoning": "Extra egg yolk makes the cookies chewier",
                    "edits": [
                        {
                            "target": "ingredients",
                            "operation": "replace",
                            "find": "2 eggs",
                            "replace": "2 eggs plus 1 egg yolk"
                        }
                    ]
                }
            ]
        }
    },
    {
        "review": "Followed it exactly as written, delicious!",
        "ingredients": ["1 cup flour"],
        "expected_output": {
            "modifications": []
        }
    }
]

def build_few_shot_prompt(
    review_text: str, title: str, ingredients: list, instructions: list
) -> str:
    """Build a few-shot prompt with examples for better extraction accuracy."""
    
    examples_text = "\n\n".join([
        f"Example {i+1}:\n"
        f"Ingredients: {ex['ingredients']}\n"
        f"Review: \"{ex['review']}\"\n"
        f"Output: {ex['expected_output']}"
        for i, ex in enumerate(FEW_SHOT_EXAMPLES)
    ])

    prompt = f"""{SYSTEM_PROMPT}

{examples_text}

Now extract from this review:

{EXTRACTION_PROMPT.format(
    title=title,
    ingredients=ingredients,
    instructions=instructions,
    review_text=review_text
)}"""
    return prompt

def build_simple_prompt(
    review_text: str, title: str, ingredients: list, instructions: list
) -> str:
    """Build a simple prompt with structured instructions."""
    return f"""{SYSTEM_PROMPT}

Original Recipe:
Title: {title}
Ingredients: {ingredients}
Instructions: {instructions}

User Review: "{review_text}"

Extract all recipe modifications from this review.

Output a JSON object with this structure:
{{
    "modifications": [
        {{
            "modification_type": "category",
            "reasoning": "Brief explanation",
            "edits": [
                {{
                    "target": "ingredients|instructions",
                    "operation": "replace|add_after|remove",
                    "find": "exact text from recipe",
                    "replace": "new text",
                    "add": "new text"
                }}
            ]
        }}
    ]
}}

If no modifications are found, return {{"modifications": []}}."""
