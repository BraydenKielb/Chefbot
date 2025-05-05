How to run:
pip install requests
run chefbot.py lol

How Chefbot works:

Configuration: 
It loads questions from questions.json and supplementary tagging keywords from tag_keywords.json. It also uses my hardcoded USDA API key.

Initial Questions (Phase 1): 
It asks the user a set of preliminary questions (marked "phase": "initial" in questions.json), like meal type (breakfast, lunch, dinner). It also asks for an optional keyword (e.g., "chicken").

API Search: 
It combines the positive answers from Phase 1 and the optional keyword into a search query. It sends this query to the USDA API, specifically searching within the "Foundation" foods dataset and requesting up to 10 results.

Processing API Results: 
If the API returns results, the program processes each food item:

   - It extracts the food's name, FDC ID, and category.
   - It derives a set of tags using the _derive_tags_from_api function. This function primarily uses the food's category provided by the API (splitting it into tags) and supplements this by checking the food's description against the keywords loaded from tag_keywords.json.
   - It creates a Food object for each valid result.

Secondary Questions (Phase 2):
It asks the remaining questions (marked "phase": "secondary"), like taste preferences (sweet, savory) or dietary needs (vegetarian).

Scoring: 
As the user answers "yes" or "no" to secondary questions, the program adjusts the score for each Food object retrieved from the API. A "yes" generally increases the score for matching foods, while a "no" generally decreases it.
Recommendation: After all secondary questions, it identifies the Food object(s) with the highest score.

    - If there's a clear winner with a non-negative score, it recommends that item.
    - If there's a tie among items with non-negative scores, it lists them and randomly suggests one.
    - If all scores are negative or zero, it suggests the item with the highest (least negative) score as the "closest option."


Major Limitations ATM:
- Single Food Item Only: 
	- The biggest limitation is that it only recommends one food item, not a complete meal or combinations of foods.
- Basic Tagging: 
	- The tag derivation (_derive_tags_from_api) is still quite basic. It relies heavily on the API category and simple keyword spotting. It doesn't understand context, nuances, or complex food characteristics well. Many foods might lack relevant tags or get inaccurate ones.

- Limited Search Strategy: 
	- The initial search relies solely on combining tags from the first few questions and an optional keyword. This might be too broad or too narrow, potentially missing good candidates or returning irrelevant ones.

Other Limitations:
- No Nutrient Awareness: 
	- It fetches food names and categories but completely ignores the rich nutritional data (calories, protein, fat, vitamins, etc.) available in the USDA database. Recommendations could be based on health goals if we wanna make it more advanced
- Static questions:
	- The questions are predefined and don't adapt based on previous answers (beyond skipping categories).
- Error handling could be better


