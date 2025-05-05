**Chefbotv3:**
- Uses themealdb.com API instead of USDA database API
- spacy for natural language processing
- preference_map.json for configuration data (keywords, dietary lists)

**Issues:**
- When selecting multiple filters (category, main ingredient, cuisine) the program attempts to compare each API search, but each list does not always have an intersection of meals, so it will often return "0 meals in intersection" if you use multiple filters


**Detailed explanation:**
Libraries:
- requests: Used to make HTTP requests to TheMealDB API to fetch meal data.
- spacy: A Natural Language Processing library used in parse_input_nlp to process user input (tokenize words, find base forms/lemmas, analyze sentence structure/dependencies for negation).
- json: Used to load the configuration data (keywords, dietary lists) from the preference_map.json file.
- re: The regular expression module, used extensively for pattern matching when checking keywords in text (e.g., ensuring "fat" isn't matched within "fatty", checking for exceptions like "gluten-free").
- sys, time, random: Standard libraries for system functions (like exiting), pausing execution, and making random choices.

Configuration (preference_map.json):
- This external JSON file stores crucial data:
- Mappings from preference keys (like "italian") to lists of keywords ("italian", "pasta", "pizza").
- Lists of known meat, dairy, and gluten-containing ingredients used for dietary filtering.
- Loading this at the start (load_preference_map) makes the bot's knowledge easily configurable.

API Interaction (call_mealdb_api, fetch_mealdb_lists, get_meal_details):
- These functions handle communication with TheMealDB.
- fetch_mealdb_lists: Gets the initial lists of valid categories, areas (cuisines), and ingredients from the API.
- call_mealdb_api: A general function to send requests to different API endpoints (like filter.php for searching or lookup.php for details), including basic error handling (timeouts, connection issues, HTTP errors) and parsing the JSON response.
- get_meal_details: Specifically calls the lookup.php endpoint to get full recipe details for a given meal ID.

NLP Parsing (parse_input_nlp):
- Takes the user's raw text input.
- Uses spaCy to process the text into tokens and analyze grammatical dependencies.
- Intent Recognition: Performs basic checks (e.g., for question marks or starting question words) to guess if the user is asking a question or stating a preference/negation.
- Entity/Keyword Extraction: Matches lemmas (base forms of words) against the keywords loaded from preference_map.json.
- Negation Handling: Uses spaCy's dependency parse to detect negation words ("not", "no") or prepositions ("without") linked to keywords, marking those preferences as 'negated'.
- Returns a structured dictionary containing the detected intent and the extracted entities (positive preferences, negated terms).

State Machine (chatbot_state_machine, DialogueState):
- The core logic controlling the conversation flow.
- DialogueState defines the possible stages of the conversation (e.g., ASKING_CUISINE, SEARCHING, SHOWING_RESULTS).
- The chatbot_state_machine function loops, executing code based on the current_state.
- Transitions between states are determined by user input (parsed intent/entities), whether clarification is needed, or whether all questions in the defined QUESTION_ORDER have been asked.

Preference Management:
- The preferences dictionary stores the user's choices throughout the conversation (e.g., {'cuisine': ['mexican'], 'dislikes': ['olives']}).
- The CLARIFY_PREFERENCE state handles ambiguity if the user mentions multiple primary options (cuisine, ingredient, category) at once.

Search Strategy (SEARCHING state):
- Implements a prioritized approach:
- Tries an Intersection search if multiple single primary criteria are given (e.g., search 'pasta' and 'italian' separately and find common meals).
- Falls back to a Single Primary Filter search based on Ingredient > Category > Cuisine order.
- Uses a Random search as a final fallback.

Filtering Logic (filter_meal_results, check_dietary_restrictions, check_dislikes):
- Takes the initial list of meals from the API search.
- Optimized Detail Fetching: Crucially, it only calls get_meal_details (which is slow) if necessary – specifically, if the user has mentioned dislikes or dietary restrictions, or if secondary filtering (like checking cuisine/category/flavor against details) is required.
- Applies filters based on dislikes and dietary needs by checking ingredients against the detailed lists in preference_map.json (including basic exception handling like "gluten-free soy sauce").
- Also filters based on secondary criteria (like cuisine or flavor tags) if details were fetched.
