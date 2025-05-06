**Chefbotv3:**
- Uses themealdb.com API instead of USDA database API
- spacy for natural language processing
- preference_map.json for configuration data (keywords, dietary lists)

**Issues:**
- Besides limitations to the mealdb, lemme know when you find them


**Detailed explanation:**
 **TheMealDB API Interaction (call_mealdb_api, fetch_mealdb_lists, get_meal_details):**
        - The program communicates with TheMealDB API (https://www.themealdb.com/api.php) to:
            - Fetch lists of available cuisines (areas), main ingredients, and categories at the start.
            - Search for meals based on a primary filter (cuisine, ingredient, or category).
            - Get detailed information for specific meals (like ingredients, instructions, etc.).
        - It includes basic error handling for API calls (timeouts, connection issues).

  - **Preference Map (preference_map.json - crucial external file):**
        - This JSON file defines:
            - Keywords and synonyms for different preference types (e.g., "italian" cuisine might have keywords like "pasta", "pizza").
            - Mappings for dietary restrictions (e.g., what ingredients make a dish non-vegetarian or non-gluten-free).
            - Lists of known meats, dairy, and gluten-containing items for accurate dietary filtering.
        - The bot uses this map to understand your input and to perform detailed checks on meal ingredients.
        
   - **Natural Language Processing (parse_input_nlp):**
        - It uses the spaCy library for basic Natural Language Processing.
        - When you type something, this function tries to:
            - Identify your intent (e.g., stating a preference, asking a question, expressing a dislike).
            - Extract key entities (like "chicken", "mexican", "vegetarian") from your input.
            - Map these entities to the preference types defined in preference_map.json.
            - Detect simple negations (e.g., "no chicken" or "without mushrooms").
        - It has a two-pass system: first looking for multi-word phrases defined in your preference map, then individual tokens. It also prioritizes matching based on the current question the bot is asking.

   - Dialogue Management (State Machine - chatbot_state_machine):
        - The core of the interaction is a state machine. The bot transitions through different states:
            - FETCHING_LISTS: Loads initial data from TheMealDB.
            - ASKING_CUISINE_INGREDIENT: Asks for primary preferences.
            - ASKING_CATEGORY, ASKING_DISLIKES, ASKING_DIETARY: Gathers more details (the "flavor" question was recently removed).
            - HANDLE_NEGATION: Processes dislikes or negated preferences.
            - CLARIFY_PREFERENCE: Asks for clarification if input is ambiguous for certain preference types.
            - READY_TO_SEARCH: Summarizes preferences and confirms before searching.
            - SEARCHING:
                - Constructs a list of search attempts (prioritizing cuisine, then ingredient, then category).
                - Calls TheMealDB API for each attempt.
                - Passes results to filter_meal_results.
                - If no results, suggests random meals (also filtered).
            - FILTERING (withinfilter_meal_resultsfunction):
                - Fetches detailed information for each meal.
                - Checks against all stated preferences:
                    - check_dislikes: Ensures no disliked items.
                    - check_dietary_restrictions: Ensures dietary needs are met.
                    - Performs secondary checks for cuisine, category, or ingredient if they weren't the primary API search filter. For instance, if the API search was by "cuisine: Mexican", this step ensures that if you also specified "ingredient: chicken", only Mexican dishes with chicken are kept.
            - SHOWING_RESULTS: Displays suitable meal ideas.
            - GETTING_DETAILS: Allows selection of a meal for its full recipe.
            - EXITING: Ends the conversation.
            E- RROR_STATE: Handles unexpected errors.

   - User Interaction:
        - The bot uses command-line prompts and input.
        - Users can type "skip", "any", "no", "none" to bypass questions, or "quit" to exit.

**Example Flow:**
    Welcome & Initial Question: Bot asks for cuisine/ingredient.
        You: "mexican and chicken"
    Gathering More Preferences: Bot asks about category, dislikes, dietary needs.
        You might skip some or provide answers like "no mushrooms" or "vegetarian".
    Confirmation: Bot summarizes preferences and asks to search.
        You: "yes"
    Search & Filter:
        Bot tries searching TheMealDB (e.g., first by "cuisine: mexican").
        It then filters these results to ensure they also contain "chicken" and meet other criteria.
        If the first attempt (e.g., by cuisine) + filtering yields no results, it might try another primary search (e.g., by "ingredient: chicken") and then filter those for "mexican" cuisine.
    Show Results: Bot lists matching meals.
    Details: You can ask for a specific meal's recipe.
