import requests
import random
import re
import json
import sys
import time
import spacy # Import spaCy
from collections import Counter # Not used currently, but potentially useful later

# --- Constants ---
MEALDB_API_BASE = "https://www.themealdb.com/api/json/v1/1/"
PREFERENCE_MAP_FILE = "preference_map.json" # Make sure this points to the v2 file content
# Load spaCy model (ensure it's downloaded: python -m spacy download en_core_web_sm)
try:
    NLP = spacy.load("en_core_web_sm")
except OSError:
    print("Spacy model 'en_core_web_sm' not found.")
    print("Please run: python -m spacy download en_core_web_sm")
    sys.exit(1)

# Define basic question words
QUESTION_WORDS = {"what", "who", "where", "when", "why", "how", "is", "are", "do", "does", "can", "could", "should", "would", "which"}

# --- Helper Functions ---

def load_preference_map(filepath=PREFERENCE_MAP_FILE):
    """Loads the preference map from a JSON file."""
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            data = json.load(f)
            if not isinstance(data, dict):
                 print(f"Error: JSON data in '{filepath}' is not a dictionary.")
                 return None
            expected_keys = ["cuisine", "ingredient", "category", "flavor", "dietary", "dislikes", "known_meats", "known_dairy", "known_gluten"]
            if not all(key in data for key in expected_keys):
                 print(f"Warning: '{filepath}' is missing some expected top-level keys.")
            return data
    except FileNotFoundError:
        print(f"Error: Preference map file '{filepath}' not found.")
        return None
    except json.JSONDecodeError:
        print(f"Error: Could not decode JSON from '{filepath}'. Check the file format.")
        return None
    except Exception as e:
        print(f"An unexpected error occurred while loading preference map: {e}")
        return None

def parse_input_nlp(text, preference_map, available_lists=None):
    """
    Parses user input using spaCy (including dependency parsing for negation)
    and maps found entities/tokens to preferences. Identifies basic intent.
    Returns a dict: {'intent': '...', 'entities': {'cuisine': [...], 'negated': [...], ...}}
    """
    # --- (Implementation from previous version - No changes needed here for this request) ---
    if not preference_map: return {'intent': 'unknown', 'entities': {}}
    if available_lists is None: available_lists = {}
    text_original_case = text; text_lower = text.lower(); doc = NLP(text_lower)
    intent = "preference"; first_token = doc[0].text if len(doc) > 0 else ""
    if text_lower.endswith("?") or first_token in QUESTION_WORDS: return {'intent': 'question', 'entities': {}}
    extracted_entities = {key: [] for key in preference_map if not key.startswith("known_")}; extracted_entities['negated'] = []; extracted_entities['attributes'] = {}
    for sent in doc.sents:
        for token in sent:
            token_text = token.lemma_; token_dep = token.dep_; token_head = token.head.lemma_
            is_negated = any(child.dep_ == "neg" for child in token.children) or (token_dep == "pobj" and token.head.lemma_ in ["without", "except", "excluding"])
            matched_type = None; matched_key = None; matched_keyword = None
            for pref_type, mapping in preference_map.items():
                if pref_type.startswith("known_"): continue
                for key, keywords in mapping.items():
                    # Use token.text for keyword matching to preserve original form if needed
                    # but lemma (token_text) is generally better for consolidation
                    if token.text.lower() in keywords or token_text in keywords:
                         matched_type = pref_type; matched_key = key; matched_keyword = token.text.lower(); break
                if matched_key: break
            if matched_key:
                target_list = extracted_entities['negated'] if is_negated else extracted_entities[matched_type]
                if matched_key not in target_list: target_list.append(matched_key)
                if is_negated and intent == 'preference': intent = 'dislike_statement' if matched_type == 'dislikes' else 'negation'
            if token.pos_ == "NOUN":
                 ingredient_key = next((key for key, keywords in preference_map.get("ingredient", {}).items() if token_text in keywords), None)
                 if ingredient_key:
                      for child in token.children:
                           if child.dep_ == "amod":
                                adj_lemma = child.lemma_; attr_key = None
                                for key, keywords in preference_map.get("flavor", {}).items():
                                     if adj_lemma in keywords: attr_key = key; break
                                if not attr_key:
                                     # Assuming texture map might exist in preference_map
                                     for key, keywords in preference_map.get("texture", {}).items():
                                          if adj_lemma in keywords: attr_key = key; break
                                if attr_key:
                                     if ingredient_key not in extracted_entities['attributes']: extracted_entities['attributes'][ingredient_key] = []
                                     if attr_key not in extracted_entities['attributes'][ingredient_key]: extracted_entities['attributes'][ingredient_key].append(attr_key)
    for key in extracted_entities:
         if isinstance(extracted_entities[key], list): extracted_entities[key] = list(set(extracted_entities[key]))
         elif isinstance(extracted_entities[key], dict):
              for sub_key in extracted_entities[key]: extracted_entities[key][sub_key] = list(set(extracted_entities[key][sub_key]))
    final_entities = {k: v for k, v in extracted_entities.items() if v}
    if 'negated' in final_entities and intent == 'preference': intent = 'negation'
    if 'dislikes' in final_entities and intent == 'preference': intent = 'dislike_statement'
    return {'intent': intent, 'entities': final_entities}


def call_mealdb_api(endpoint, params=None):
    """Helper function to call TheMealDB API with error handling."""
    # --- (Implementation from previous version - No changes needed here) ---
    url = MEALDB_API_BASE + endpoint; params = params or {}
    try:
        response = requests.get(url, params=params, timeout=15)
        if response.status_code == 429: time.sleep(5); response = requests.get(url, params=params, timeout=15)
        response.raise_for_status()
        data = response.json()
        if endpoint.startswith("list.php") and not data.get('meals'): return []
        return data.get('meals')
    except requests.exceptions.Timeout: print(f"API Error: Timeout calling {endpoint}."); return None
    except requests.exceptions.ConnectionError: print(f"API Error: Connection error for {endpoint}."); return None
    except requests.exceptions.HTTPError as e:
         if endpoint.startswith("filter.php") and response.status_code == 404: return []
         print(f"API Error: HTTP Error {response.status_code} for {endpoint}: {e}"); return None
    except requests.exceptions.RequestException as e: print(f"API Error: Request error for {endpoint}: {e}"); return None
    except json.JSONDecodeError: print(f"API Error: JSON decode error from {endpoint}."); return None
    except Exception as e: print(f"Unexpected API error for {endpoint}: {e}"); return None

def fetch_mealdb_lists():
    """Fetches available categories, areas (cuisines), and ingredients from TheMealDB."""
    # --- (Implementation from previous version - No changes needed here) ---
    print("Fetching available lists from TheMealDB...")
    lists = {"categories": None, "areas": None, "ingredients": None}
    try:
        cat_data = call_mealdb_api("list.php?c=list"); area_data = call_mealdb_api("list.php?a=list"); ing_data = call_mealdb_api("list.php?i=list")
        if cat_data is not None: lists["categories"] = {item['strCategory'].lower() for item in cat_data if item and 'strCategory' in item and item['strCategory']}
        else: print("  - Failed to load categories.")
        if area_data is not None: lists["areas"] = {item['strArea'].lower() for item in area_data if item and 'strArea' in item and item['strArea']}
        else: print("  - Failed to load areas.")
        if ing_data is not None: lists["ingredients"] = {item['strIngredient'].lower() for item in ing_data if item and 'strIngredient' in item and item['strIngredient']}
        else: print("  - Failed to load ingredients.")
    except Exception as e: print(f"An error occurred while fetching lists: {e}")
    print(f"  - Loaded {len(lists.get('categories', set()))} categories, {len(lists.get('areas', set()))} areas, {len(lists.get('ingredients', set()))} ingredients.")
    return lists["categories"], lists["areas"], lists["ingredients"]

def get_meal_details(meal_id):
    """Fetches detailed information for a specific meal ID."""
    if not meal_id: return None
    return call_mealdb_api("lookup.php", {'i': meal_id})

# --- check_dietary_restrictions and check_dislikes remain the same (using refined keywords) ---
def check_dietary_restrictions(meal_detail, preferences, preference_map):
    """Checks if a meal detail violates dietary restrictions using refined keyword lists and basic exception handling."""
    # --- (Implementation from previous version - No changes needed here) ---
    if not meal_detail or not preference_map: return True # Cannot check
    dietary_prefs = preferences.get("dietary", [])
    if not dietary_prefs: return False
    ingredients_lower = set()
    for i in range(1, 21):
        ingredient = meal_detail.get(f'strIngredient{i}')
        if ingredient and ingredient.strip(): ingredients_lower.add(ingredient.strip().lower())
    meat_keywords = set().union(*preference_map.get("known_meats", {}).values())
    dairy_keywords = set().union(*preference_map.get("known_dairy", {}).values())
    egg_keywords = set(preference_map.get("ingredient", {}).get("eggs", []))
    gluten_keywords = set().union(*preference_map.get("known_gluten", {}).values())
    for ingredient_str in ingredients_lower:
        if "vegetarian" in dietary_prefs or "vegan" in dietary_prefs:
            if any(re.search(r'\b' + re.escape(meat_kw) + r'\b', ingredient_str) for meat_kw in meat_keywords):
                 if not re.search(r'\b(vegetarian|vegetable|veggie)\s+(broth|stock|bouillon)\b', ingredient_str): return True
        if "vegan" in dietary_prefs:
            if any(re.search(r'\b' + re.escape(dairy_kw) + r'\b', ingredient_str) for dairy_kw in dairy_keywords):
                 if not re.search(r'\bdairy[- ]?free\b', ingredient_str): return True
            if any(re.search(r'\b' + re.escape(egg_kw) + r'\b', ingredient_str) for egg_kw in egg_keywords): return True
        if "gluten_free" in dietary_prefs:
            if any(re.search(r'\b' + re.escape(gluten_kw) + r'\b', ingredient_str) for gluten_kw in gluten_keywords):
                 if not re.search(r'\bgluten[- ]?free\b', ingredient_str):
                      if "soy sauce" in ingredient_str and not re.search(r'\b(tamari|gluten[- ]?free soy sauce)\b', ingredient_str): return True
                      elif re.search(r'\b(oat|oats)\b', ingredient_str) and not re.search(r'\b(gluten[- ]?free oat|certified gluten[- ]?free)\b', ingredient_str): return True
                      elif not ("soy sauce" in ingredient_str or re.search(r'\b(oat|oats)\b', ingredient_str)): return True
        if "dairy_free" in dietary_prefs:
            if any(re.search(r'\b' + re.escape(dairy_kw) + r'\b', ingredient_str) for dairy_kw in dairy_keywords):
                 if not re.search(r'\bdairy[- ]?free\b|\blactose[- ]?free\b', ingredient_str): return True
    if "gluten_free" in dietary_prefs:
         meal_category = meal_detail.get('strCategory', '').lower(); meal_name = meal_detail.get('strMeal', '').lower(); meal_tags = meal_detail.get('strTags', '').lower() if meal_detail.get('strTags') else ''
         if any(re.search(r'\b' + re.escape(gluten_kw) + r'\b', text) for gluten_kw in gluten_keywords for text in [meal_category, meal_name]) and not re.search(r'\bgluten[- ]?free\b', meal_name) and not re.search(r'\bgluten[- ]?free\b', meal_tags): return True
    return False

def check_dislikes(meal_detail, preferences, preference_map):
    """Checks if a meal detail contains disliked ingredients."""
    # --- (Implementation from previous version - No changes needed here) ---
    if not meal_detail or not preference_map: return True
    dislikes_keys = preferences.get("dislikes", [])
    if not dislikes_keys: return False
    dislike_keywords = set().union(*(preference_map.get("dislikes", {}).get(key, []) for key in dislikes_keys))
    if not dislike_keywords: return False
    for i in range(1, 21):
        ingredient = meal_detail.get(f'strIngredient{i}')
        if ingredient and ingredient.strip():
            if any(re.search(r'\b' + re.escape(dislike_kw) + r'\b', ingredient.strip().lower()) for dislike_kw in dislike_keywords): return True
    return False

# --- *** MODIFIED Filtering Function Signature and Calls *** ---
def filter_meal_results(meals, preferences, preference_map, available_lists, force_detail_check=False):
    """
    Filters meals based on preferences.
    Optimized: Fetches details ONLY if dislikes/dietary prefs exist OR if force_detail_check is True.
    Adds filtering based on secondary criteria (cuisine, category, strTags) if details are fetched.
    Requires available_lists for validation.
    """
    if not meals: return []
    if not available_lists: # Cannot filter secondary criteria without lists
         print("Warning: Cannot perform secondary filtering without available API lists.")
         needs_detail_check = force_detail_check or any(preferences.get(key) for key in ["dislikes", "dietary"])
         if not needs_detail_check: return meals
    else:
        # Determine if a detailed check is absolutely necessary
        needs_detail_check = force_detail_check or any(preferences.get(key) for key in ["dislikes", "dietary"])
        secondary_cuisine = preferences.get("cuisine") if len(preferences.get("cuisine", [])) == 1 else None
        secondary_category = preferences.get("category") if len(preferences.get("category", [])) == 1 else None
        secondary_flavor = preferences.get("flavor")
        primary_search_keys = preferences.get("_primary_search_keys", [])
        if secondary_cuisine and "cuisine" not in primary_search_keys: needs_detail_check = True
        if secondary_category and "category" not in primary_search_keys: needs_detail_check = True
        if secondary_flavor: needs_detail_check = True

    if not needs_detail_check:
        # print("Filtering: No detailed checks required based on current preferences.") # Debug
        return meals # Return initial list

    print(f"\nFiltering {len(meals)} results (checking details)...")
    meals_to_keep = []
    checked_ids = set()
    details_cache = {} # Cache details within this filtering run

    for meal_summary in meals:
        meal_id = meal_summary.get('idMeal')
        if not meal_id or meal_id in checked_ids: continue
        checked_ids.add(meal_id)

        # --- Fetch Details (Only if needed and not cached) ---
        meal_detail_list = details_cache.get(meal_id)
        if not meal_detail_list:
            meal_detail_list = get_meal_details(meal_id)
            if meal_detail_list: details_cache[meal_id] = meal_detail_list
            else: print(f"Warning: Could not fetch details for meal ID {meal_id}. Excluding."); continue

        meal_detail = meal_detail_list[0]

        # --- Perform Checks using Details ---
        if check_dislikes(meal_detail, preferences, preference_map): continue
        if check_dietary_restrictions(meal_detail, preferences, preference_map): continue

        # Secondary Cuisine Check
        if secondary_cuisine and "cuisine" not in primary_search_keys:
            meal_area = meal_detail.get('strArea', '').lower()
            expected_areas = set()
            for key, keywords in preference_map.get("cuisine", {}).items():
                 if key == secondary_cuisine[0]:
                      expected_areas.update(kw for kw in keywords if kw in available_lists.get("areas", set()))
                      break
            if not expected_areas: expected_areas.add(secondary_cuisine[0])
            if meal_area not in expected_areas: continue

        # Secondary Category Check
        if secondary_category and "category" not in primary_search_keys:
            meal_cat = meal_detail.get('strCategory', '').lower()
            expected_cats = set()
            for key, keywords in preference_map.get("category", {}).items():
                 if key == secondary_category[0]:
                      expected_cats.update(kw for kw in keywords if kw in available_lists.get("categories", set()))
                      break
            if not expected_cats: expected_cats.add(secondary_category[0])
            if meal_cat not in expected_cats: continue

        # Flavor Check
        if secondary_flavor:
            meal_tags_str = meal_detail.get('strTags', '').lower() if meal_detail.get('strTags') else ''
            meal_name_lower = meal_detail.get('strMeal', '').lower()
            found_flavor = False
            for flavor_key in secondary_flavor:
                 flavor_keywords = preference_map.get("flavor", {}).get(flavor_key, [])
                 if any(re.search(r'\b' + re.escape(kw) + r'\b', meal_tags_str) for kw in flavor_keywords) or \
                    any(re.search(r'\b' + re.escape(kw) + r'\b', meal_name_lower) for kw in flavor_keywords):
                      found_flavor = True; break
            if not found_flavor: continue

        meals_to_keep.append(meal_summary) # Keep if all checks passed

    print(f"Finished filtering. {len(meals_to_keep)} meals remaining.")
    return meals_to_keep


# --- State Machine Dialogue Manager ---

class DialogueState:
    """Enum-like class for dialogue states."""
    START = "START"; FETCHING_LISTS = "FETCHING_LISTS"; ASKING_INITIAL = "ASKING_INITIAL"
    ASKING_CUISINE = "ASKING_CUISINE"; ASKING_INGREDIENT = "ASKING_INGREDIENT"
    ASKING_CATEGORY = "ASKING_CATEGORY"; ASKING_FLAVOR = "ASKING_FLAVOR"
    ASKING_DIETARY = "ASKING_DIETARY"; ASKING_DISLIKES = "ASKING_DISLIKES"
    CLARIFY_PREFERENCE = "CLARIFY_PREFERENCE"; HANDLE_NEGATION = "HANDLE_NEGATION"
    READY_TO_SEARCH = "READY_TO_SEARCH"; SEARCHING = "SEARCHING"
    # Removed refinement states for now, simplified flow
    SHOWING_RESULTS = "SHOWING_RESULTS"; GETTING_DETAILS = "GETTING_DETAILS"
    EXITING = "EXITING"; ERROR_STATE = "ERROR_STATE"

def chatbot_state_machine():
    """Main function using a state machine for dialogue."""

    preference_map = load_preference_map()
    if not preference_map: print("Critical error: Could not load preference map."); return

    preferences = {key: [] for key in preference_map if not key.startswith("known_")}
    current_state = DialogueState.START
    asked_this_session = set()
    clarification_data = None
    available_lists = {}
    last_results = []
    displayed_meals = []
    last_intent_data = {}
    # Removed refinement_history

    # Define the standard question order
    QUESTION_ORDER = [
        DialogueState.ASKING_CUISINE,
        DialogueState.ASKING_INGREDIENT,
        DialogueState.ASKING_CATEGORY,
        DialogueState.ASKING_DISLIKES,
        DialogueState.ASKING_DIETARY,
        DialogueState.ASKING_FLAVOR,
        DialogueState.READY_TO_SEARCH # Final state in sequence
    ]

    def get_next_question_state(current_asked_set):
        """Determines the next question state based on the defined order."""
        for state in QUESTION_ORDER:
            # Map state back to preference type key
            pref_type = None
            if state == DialogueState.ASKING_CUISINE: pref_type = "cuisine"
            elif state == DialogueState.ASKING_INGREDIENT: pref_type = "ingredient"
            elif state == DialogueState.ASKING_CATEGORY: pref_type = "category"
            elif state == DialogueState.ASKING_DISLIKES: pref_type = "dislikes"
            elif state == DialogueState.ASKING_DIETARY: pref_type = "dietary"
            elif state == DialogueState.ASKING_FLAVOR: pref_type = "flavor"

            if pref_type and pref_type not in current_asked_set:
                return state # Return the first state in order that hasn't been asked
        return DialogueState.READY_TO_SEARCH # Default if all asked

    while current_state != DialogueState.EXITING:
        # print(f"DEBUG: State: {current_state}, Prefs: {preferences}, Asked: {asked_this_session}") # Debugging

        user_input = "" # Reset input

        # --- State Actions ---
        if current_state == DialogueState.START: current_state = DialogueState.FETCHING_LISTS
        elif current_state == DialogueState.FETCHING_LISTS:
             categories, areas, ingredients = fetch_mealdb_lists()
             available_lists = {"categories": categories or set(), "areas": areas or set(), "ingredients": ingredients or set()}
             if not categories or not areas or not ingredients: print("\nWarning: Failed to load essential lists.")
             print("\nWelcome! ..."); print("Tell me what you're feeling like..."); print("You can also type 'skip' or 'any', or 'quit'.")
             current_state = DialogueState.ASKING_INITIAL
        elif current_state in [DialogueState.ASKING_INITIAL, DialogueState.ASKING_CUISINE, DialogueState.ASKING_INGREDIENT, DialogueState.ASKING_CATEGORY, DialogueState.ASKING_FLAVOR, DialogueState.ASKING_DIETARY, DialogueState.ASKING_DISLIKES]:
            # Determine question and pref_type based on state
            question_text = ""; current_pref_type = None; examples = []
            # ... (Assign question_text/current_pref_type based on state) ...
            if current_state == DialogueState.ASKING_INITIAL: question_text = "\nWhat kind of meal are you thinking about? Any initial thoughts?"
            elif current_state == DialogueState.ASKING_CUISINE: current_pref_type = "cuisine"; examples = random.sample(list(available_lists.get("areas", [])), min(len(available_lists.get("areas", [])), 5)); question_text = f"\nAny particular cuisine? (e.g., {', '.join(examples).title()})"
            elif current_state == DialogueState.ASKING_INGREDIENT: current_pref_type = "ingredient"; question_text = "\nAny main ingredient in mind? (e.g., Chicken, Beef, Tofu)"
            elif current_state == DialogueState.ASKING_CATEGORY: current_pref_type = "category"; examples = random.sample(list(available_lists.get("categories", [])), min(len(available_lists.get("categories", [])), 5)); question_text = f"\nAny specific category? (e.g., {', '.join(examples).title()})"
            elif current_state == DialogueState.ASKING_FLAVOR: current_pref_type = "flavor"; question_text = "\nWhat kind of tastes sound good? (Spicy, Sweet, Savory, etc.)"
            elif current_state == DialogueState.ASKING_DIETARY: current_pref_type = "dietary"; question_text = "\nAny dietary restrictions? (Vegetarian, Gluten-Free, etc.)"
            elif current_state == DialogueState.ASKING_DISLIKES: current_pref_type = "dislikes"; question_text = "\nAnything you really DON'T want?"

            print(question_text); user_input = input("Your answer: ").strip()
            if user_input.lower() == 'quit': current_state = DialogueState.EXITING; continue
            if user_input.lower() in ["skip", "any", "no", "none", ""]:
                if current_pref_type: asked_this_session.add(current_pref_type)
                # *** MODIFIED: Always transition to next question in sequence ***
                current_state = get_next_question_state(asked_this_session)
                continue

            parsed_data = parse_input_nlp(user_input, preference_map, available_lists)
            intent = parsed_data.get("intent", "unknown"); entities = parsed_data.get("entities", {}); last_intent_data = parsed_data

            if intent == "question": print("Sorry, I can search for meals, but I can't answer general questions yet."); continue
            elif intent == "negation" or intent == "dislike_statement": current_state = DialogueState.HANDLE_NEGATION; continue
            elif intent == "preference":
                if not entities: print("Hmm, I didn't catch a specific preference there."); continue
                else:
                     print(f"Okay, I noted: {entities}"); needs_clarification = False; clarify_key = None
                     for key, values in entities.items():
                          if key == 'negated' or key == 'attributes': continue
                          current_prefs = preferences.get(key, []); combined_prefs = list(set(current_prefs + values)); preferences[key] = combined_prefs
                          if key in ["cuisine", "ingredient", "category"] and len(combined_prefs) > 1:
                               clarification_data = {"type": key, "options": combined_prefs, "original_prefs": current_prefs}; needs_clarification = True; clarify_key = key; break
                          else: asked_this_session.add(key) # Mark as asked only if no clarification needed for this key
                     if needs_clarification: current_state = DialogueState.CLARIFY_PREFERENCE; continue
                     else: # Transition logic
                          if current_pref_type: asked_this_session.add(current_pref_type) # Mark current question type asked
                          # *** MODIFIED: Always transition to next question in sequence ***
                          current_state = get_next_question_state(asked_this_session)
                          continue
            else: print("Sorry, I didn't quite understand that."); continue

        elif current_state == DialogueState.HANDLE_NEGATION:
            # (Negation handling logic - same as previous version)
            negated_items = last_intent_data.get('entities', {}).get('negated', [])
            dislike_items = last_intent_data.get('entities', {}).get('dislikes', [])
            if negated_items:
                 print(f"Okay, noted you DON'T want: {', '.join(negated_items)}.")
                 for item in negated_items:
                      if item in preference_map.get("dislikes", {}): preferences["dislikes"].append(item)
                      for pref_type in ["cuisine", "ingredient", "category", "flavor"]:
                           if item in preferences.get(pref_type, []): preferences[pref_type].remove(item)
            if dislike_items: print(f"Okay, avoiding: {', '.join(dislike_items)}."); preferences["dislikes"] = list(set(preferences["dislikes"] + dislike_items))
            # *** MODIFIED: Always transition to next question in sequence ***
            current_state = get_next_question_state(asked_this_session)
            continue

        elif current_state == DialogueState.CLARIFY_PREFERENCE:
            # (Clarification logic - same as previous version)
            if clarification_data:
                pref_type = clarification_data["type"]; options = clarification_data["options"]; original_prefs = clarification_data.get("original_prefs", [])
                print(f"\nYou mentioned a few {pref_type}s: {', '.join(options)}."); print(f"Which one should I focus on?")
                user_input = input(f"Choose one {pref_type}: ").strip()
                if user_input.lower() == 'quit': current_state = DialogueState.EXITING; continue
                best_match = None; input_lower = user_input.lower()
                for option in options:
                     keywords = preference_map.get(pref_type, {}).get(option, [option])
                     if input_lower == option.lower() or input_lower in keywords: best_match = option; break
                if not best_match:
                     parsed_clarification = parse_input_nlp(user_input, preference_map, available_lists).get(pref_type, [])
                     for parsed_option in parsed_clarification:
                          if parsed_option in options: best_match = parsed_option; break
                if best_match:
                    print(f"Okay, focusing on {pref_type}: {best_match}."); preferences[pref_type] = [best_match]; asked_this_session.add(pref_type); clarification_data = None
                else:
                    print(f"Sorry, I didn't understand. Keeping previous options."); preferences[pref_type] = original_prefs; asked_this_session.add(pref_type); clarification_data = None
                # *** MODIFIED: Always transition to next question in sequence ***
                current_state = get_next_question_state(asked_this_session)
            else: print("Error: Clarification error."); current_state = DialogueState.ASKING_INITIAL
            continue

        elif current_state == DialogueState.READY_TO_SEARCH:
            # Now, only offer to search if we've cycled through questions
            print("\nOkay, I have your preferences:")
            for key, val in preferences.items():
                 if val: print(f"- {key.title()}: {', '.join(val)}")

            if not any(preferences.get(key) for key in ["ingredient", "category", "cuisine"]):
                 print("\nI still need a main ingredient, category, or cuisine to search effectively.")
                 # Go back to asking the first missing primary question
                 current_state = get_next_question_state(set()) # Start sequence over essentially
                 continue

            search_confirm = input("Ready to search for meals? (yes/no): ").strip().lower()
            if search_confirm == 'yes':
                current_state = DialogueState.SEARCHING
            elif search_confirm == 'quit':
                 current_state = DialogueState.EXITING
            else:
                # Allow adding more info - go back to initial prompt
                print("Okay, what else would you like to tell me?")
                current_state = DialogueState.ASKING_INITIAL
            continue

        elif current_state == DialogueState.SEARCHING:
            # --- (Search logic remains the same - uses intersection/single filter/fallback) ---
            primary_prefs = { k: v for k, v in preferences.items() if k in ["ingredient", "category", "cuisine"] and v }
            initial_meals = []; search_strategy_used = "None"; preferences["_primary_search_keys"] = []
            search_successful = False
            primary_keys_with_single_value = [k for k, v in primary_prefs.items() if len(v) == 1]

            # Strategy 1: Intersection
            if len(primary_keys_with_single_value) > 1:
                search_strategy_used = f"Intersection on {', '.join(primary_keys_with_single_value)}"
                print(f"\nSearching using Intersection for: {primary_prefs}")
                results_per_pref = {}; possible = True
                for pref_type in primary_keys_with_single_value:
                    primary_value = primary_prefs[pref_type][0]; param_map = {"ingredient": "i", "category": "c", "cuisine": "a"}; param_key = param_map[pref_type]; api_value = primary_value
                    if pref_type == "cuisine": # Map back
                        found_area = next((kw for key, keywords in preference_map.get("cuisine", {}).items() if key == primary_value for kw in keywords if kw in available_lists.get("areas", set())), None)
                        if found_area: api_value = found_area
                    search_param = {param_key: api_value}; print(f"  - Calling API for {pref_type}={api_value}...")
                    meals = call_mealdb_api("filter.php", search_param)
                    if meals: results_per_pref[pref_type] = {m['idMeal']: m for m in meals}; print(f"    Found {len(results_per_pref[pref_type])} matches.")
                    else: print(f"    No results for {pref_type}={api_value}. Intersection impossible."); possible = False; break
                if possible and results_per_pref:
                    intersecting_ids = set.intersection(*(set(ids.keys()) for ids in results_per_pref.values())); print(f"  - Found {len(intersecting_ids)} meals in intersection.")
                    if intersecting_ids: first_results_dict = next(iter(results_per_pref.values())); initial_meals = [first_results_dict[id] for id in intersecting_ids if id in first_results_dict]
                    if initial_meals: search_successful = True; preferences["_primary_search_keys"] = primary_keys_with_single_value

            # Strategy 2: Single Primary Filter
            if not initial_meals and len(primary_keys_with_single_value) <= 1 :
                search_order = ["ingredient", "category", "cuisine"]
                for pref_type in search_order:
                    if preferences.get(pref_type):
                        primary_value = preferences[pref_type][0]; param_map = {"ingredient": "i", "category": "c", "cuisine": "a"}; param_key = param_map[pref_type]; api_value = primary_value
                        if pref_type == "cuisine": # Map back
                            found_area = next((kw for key, keywords in preference_map.get("cuisine", {}).items() if key == primary_value for kw in keywords if kw in available_lists.get("areas", set())), None)
                            if found_area: api_value = found_area
                        search_param = {param_key: api_value}; search_strategy_used = f"Primary filter: {pref_type}={api_value}"
                        print(f"\nSearching TheMealDB by {search_strategy_used}...")
                        initial_meals = call_mealdb_api("filter.php", search_param)
                        if initial_meals: print(f"Found {len(initial_meals)} initial matches."); preferences["_primary_search_keys"] = [pref_type]; search_successful = True; break
                        else: print(f"No meals found matching {search_strategy_used}."); preferences["_primary_search_keys"] = []

            # --- Filtering ---
            if initial_meals:
                 # No refinement step here, filter directly
                 force_check = any(preferences.get(key) for key in ["flavor"]) or \
                               (preferences.get("cuisine") and "cuisine" not in preferences.get("_primary_search_keys", [])) or \
                               (preferences.get("category") and "category" not in preferences.get("_primary_search_keys", []))
                 found_meals = filter_meal_results(initial_meals, preferences, preference_map, available_lists, force_detail_check=force_check)
            else:
                 found_meals = []

            # --- Fallback to Random ---
            if not found_meals:
                 print(f"\nNo results found for {search_strategy_used} after filtering.")
                 print("Suggesting a random meal (checking dislikes/dietary)...")
                 search_strategy_used = "random"; random_meals_to_try = 5; random_meal_candidates = []; unique_ids = set()
                 for _ in range(random_meals_to_try):
                      random_meal_list = call_mealdb_api("random.php", {})
                      if random_meal_list: meal = random_meal_list[0]; unique_ids.add(meal['idMeal']); random_meal_candidates.append(meal)
                      time.sleep(0.2)
                 if random_meal_candidates:
                      unique_random = {m['idMeal']: m for m in random_meal_candidates}.values()
                      found_meals = filter_meal_results(list(unique_random), preferences, preference_map, available_lists, force_detail_check=True)

            # --- Transition ---
            if found_meals:
                 last_results = found_meals; displayed_meals = []; current_state = DialogueState.SHOWING_RESULTS
            else:
                 print(f"\nSorry, I couldn't find any meals matching your criteria ({search_strategy_used}).")
                 retry = input("Try again with fewer criteria or different terms? (yes/no): ").strip().lower()
                 if retry == 'yes': preferences = {key: [] for key in preferences}; asked_this_session = set(); current_state = DialogueState.ASKING_INITIAL
                 else: current_state = DialogueState.EXITING
            preferences.pop("_primary_search_keys", None); continue


        elif current_state == DialogueState.SHOWING_RESULTS:
            # (Showing results logic remains the same)
            max_suggestions = 5; start_index = len(displayed_meals); next_batch = last_results[start_index : start_index + max_suggestions]
            if not next_batch and start_index == 0: print("No meals found."); retry = input("Search again? (yes/no): ").strip().lower(); current_state = DialogueState.ASKING_INITIAL if retry == 'yes' else DialogueState.EXITING; continue
            elif not next_batch and start_index > 0: print("No more results."); current_state = DialogueState.GETTING_DETAILS; continue
            print("\nHere are some meal ideas:"); [print(f"  {start_index + i + 1}. {meal.get('strMeal')}") for i, meal in enumerate(next_batch)]; displayed_meals.extend(next_batch)
            current_state = DialogueState.GETTING_DETAILS; continue


        elif current_state == DialogueState.GETTING_DETAILS:
            # (Getting details logic remains the same)
             choice_input = input(f"\nEnter number (1-{len(displayed_meals)}) for details, 'more', 'search again', 'start over', or 'quit': ").strip().lower()
             if choice_input == 'quit': current_state = DialogueState.EXITING; continue
             elif choice_input == 'more': current_state = DialogueState.SHOWING_RESULTS; continue
             elif choice_input == 'search again': current_state = DialogueState.SEARCHING; continue
             elif choice_input == 'start over': preferences = {key: [] for key in preferences}; asked_this_session = set(); current_state = DialogueState.ASKING_INITIAL; continue
             elif choice_input.isdigit():
                  try:
                       choice_index = int(choice_input) - 1
                       if 0 <= choice_index < len(displayed_meals):
                            chosen_meal_summary = displayed_meals[choice_index]; chosen_meal_id = chosen_meal_summary.get('idMeal')
                            print(f"\nFetching details for: {chosen_meal_summary.get('strMeal')}..."); details_list = get_meal_details(chosen_meal_id)
                            if details_list:
                                meal_detail = details_list[0] # Display details...
                                print(f"\n--- {meal_detail.get('strMeal')} ---"); print(f"Category: {meal_detail.get('strCategory')}"); print(f"Area: {meal_detail.get('strArea')}")
                                if meal_detail.get('strTags'): print(f"Tags: {meal_detail.get('strTags')}")
                                print("\nIngredients:"); [print(f"- {meal_detail.get(f'strMeasure{i}')} {meal_detail.get(f'strIngredient{i}')}") for i in range(1, 21) if meal_detail.get(f'strIngredient{i}')]
                                print("\nInstructions:"); instructions = meal_detail.get('strInstructions', ''); print('\n'.join(line.strip() for line in instructions.splitlines() if line.strip()))
                                if meal_detail.get('strYoutube'): print(f"\nYouTube Link: {meal_detail.get('strYoutube')}")
                                if meal_detail.get('strSource'): print(f"Source: {meal_detail.get('strSource')}")
                                satisfied = input("\nLooks good? ('yes' to finish / 'no' for other options): ").strip().lower()
                                if satisfied == 'yes': current_state = DialogueState.EXITING
                                else: current_state = DialogueState.GETTING_DETAILS # Stay here
                            else: print("Sorry, couldn't fetch details."); current_state = DialogueState.GETTING_DETAILS
                       else: print("Invalid number."); current_state = DialogueState.GETTING_DETAILS
                  except ValueError: print("Invalid input."); current_state = DialogueState.GETTING_DETAILS
             else: print("Invalid input."); current_state = DialogueState.GETTING_DETAILS
             continue


        elif current_state == DialogueState.ERROR_STATE:
             print("\nAn unexpected error occurred. Restarting."); time.sleep(2)
             preferences = {key: [] for key in preference_map if not key.startswith("known_")}; asked_this_session = set(); clarification_data = None; available_lists = {}; last_results = []; displayed_meals = []
             current_state = DialogueState.START; continue


    # --- End of Loop ---
    print("\nHappy cooking!")


# --- Run the Chatbot ---
if __name__ == "__main__":
    chatbot_state_machine()
