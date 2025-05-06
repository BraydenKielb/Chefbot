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
PREFERENCE_MAP_FILE = "preference_map.json" # Ensure this uses the improved map
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

def parse_input_nlp(text, preference_map, available_lists=None, current_asking_type=None):
    """
    Parses user input using spaCy, maps entities to preferences, and identifies intent.
    Prioritizes matching against `current_asking_type` if provided.
    Attempts to match multi-word keywords first.
    """
    if not preference_map: return {'intent': 'unknown', 'entities': {}}
    if available_lists is None: available_lists = {}

    text_original_case = text
    text_lower = text.lower()
    doc = NLP(text_lower) # spaCy Doc object

    intent = "preference"
    first_token_doc = doc[0].text.lower() if len(doc) > 0 else ""
    if text_lower.endswith("?") or first_token_doc in QUESTION_WORDS:
        intent = "question"
        return {'intent': intent, 'entities': {}}

    # Initialize extracted_entities based on preference_map keys, excluding "flavor"
    extracted_entities = {key: [] for key in preference_map if not key.startswith("known_") and key != "flavor"}
    extracted_entities['negated'] = []
    extracted_entities['attributes'] = {}
    
    matched_phrase_tokens_indices = set() 

    priority_types_to_check = []
    if isinstance(current_asking_type, str):
        priority_types_to_check = [current_asking_type]
    elif isinstance(current_asking_type, list):
        priority_types_to_check = current_asking_type
    
    # Filter out "flavor" from types to check if it's present
    types_for_phrase_check = [t for t in (priority_types_to_check + 
                                           [ptype for ptype in preference_map 
                                            if ptype not in priority_types_to_check 
                                            and not ptype.startswith("known_")]) 
                              if t != "flavor"]


    for pref_type in types_for_phrase_check:
        if pref_type not in preference_map: continue
        for key, keywords in preference_map[pref_type].items():
            for keyword_phrase in keywords:
                if " " in keyword_phrase.lower(): 
                    for match in re.finditer(re.escape(keyword_phrase.lower()), text_lower):
                        start_char, end_char = match.span()
                        is_negated_phrase = False 
                        span = doc.char_span(start_char, end_char, alignment_mode="contract")
                        if span and span.start > 0:
                            prev_token = doc[span.start -1]
                            if prev_token.dep_ == "neg" or prev_token.lemma_ in ["not", "no", "without"]:
                                is_negated_phrase = True
                        if "without " + keyword_phrase.lower() in text_lower : is_negated_phrase = True 

                        target_list_key = pref_type
                        if current_asking_type == 'dislikes' and pref_type != 'dislikes':
                             target_list_key = 'dislikes'
                        elif is_negated_phrase and pref_type != 'dislikes':
                             target_list_key = 'negated'
                             if intent == 'preference': intent = 'negation'
                        
                        if key not in extracted_entities[target_list_key]:
                            extracted_entities[target_list_key].append(key)
                        
                        if target_list_key == 'dislikes' and intent == 'preference':
                            intent = 'dislike_statement'

                        if span:
                            for token_in_phrase in span:
                                matched_phrase_tokens_indices.add(token_in_phrase.i)
    
    for token_idx, token in enumerate(doc):
        if token.i in matched_phrase_tokens_indices: 
            continue

        token_text_lemma = token.lemma_
        token_text_lower = token.text.lower()
        is_negated_token = any(child.dep_ == "neg" for child in token.children) or \
                           (token.dep_ == "pobj" and token.head.lemma_ in ["without", "except", "excluding"])

        matched_this_token_in_pass2 = False
        # Filter out "flavor" from priority_types_to_check as well
        for pref_type in [pt for pt in priority_types_to_check if pt != "flavor"]:
            if pref_type not in preference_map: continue
            for key, keywords in preference_map[pref_type].items():
                if token_text_lower in keywords or token_text_lemma in keywords:
                    target_list_key = pref_type
                    if is_negated_token:
                        target_list_key = 'negated' if pref_type != 'dislikes' else 'dislikes'
                        if pref_type != 'dislikes' and intent == 'preference': intent = 'negation'
                    
                    if key not in extracted_entities[target_list_key]: extracted_entities[target_list_key].append(key)
                    if target_list_key == 'dislikes' and intent == 'preference': intent = 'dislike_statement'
                    matched_this_token_in_pass2 = True; break
            if matched_this_token_in_pass2: break
        
        if matched_this_token_in_pass2: continue

        for pref_type, mapping in preference_map.items():
            if pref_type.startswith("known_") or pref_type in priority_types_to_check or pref_type == "flavor": continue # Skip flavor here too
            for key, keywords in mapping.items():
                if token_text_lower in keywords or token_text_lemma in keywords:
                    target_list_key = pref_type
                    if is_negated_token:
                        target_list_key = 'negated'
                        if intent == 'preference': intent = 'negation'
                    
                    if key not in extracted_entities[target_list_key]: extracted_entities[target_list_key].append(key)
                    if target_list_key == 'dislikes' and intent == 'preference': intent = 'dislike_statement'
                    matched_this_token_in_pass2 = True; break
            if matched_this_token_in_pass2: break
        
        if token.pos_ == "NOUN" and not matched_this_token_in_pass2:
            ingredient_key_for_attr = next((k for k, kw_list in preference_map.get("ingredient", {}).items() if token_text_lemma in kw_list or token_text_lower in kw_list), None)
            if ingredient_key_for_attr:
                for child in token.children:
                    if child.dep_ == "amod":
                        adj_lemma = child.lemma_
                        attr_key_found = None
                        # Texture is still relevant, flavor attributes might not be if flavor is removed
                        for key_type_attr in ["texture"]: # Removed "flavor" from attribute check if flavor is globally removed
                            if key_type_attr not in preference_map: continue # Skip if texture map doesn't exist
                            for attr_k, attr_kw_list in preference_map.get(key_type_attr, {}).items():
                                if adj_lemma in attr_kw_list:
                                    attr_key_found = attr_k; break
                            if attr_key_found: break
                        if attr_key_found:
                            if attr_key_found not in extracted_entities['attributes'].setdefault(ingredient_key_for_attr, []):
                                extracted_entities['attributes'][ingredient_key_for_attr].append(attr_key_found)

    # Cleanup
    for key_clean in extracted_entities:
        if isinstance(extracted_entities[key_clean], list):
            extracted_entities[key_clean] = list(set(extracted_entities[key_clean]))
        elif isinstance(extracted_entities[key_clean], dict):
            for sub_key_clean in extracted_entities[key_clean]:
                if isinstance(extracted_entities[key_clean][sub_key_clean], list):
                    extracted_entities[key_clean][sub_key_clean] = list(set(extracted_entities[key_clean][sub_key_clean]))

    final_entities = {k: v for k, v in extracted_entities.items() if v} 
    
    if final_entities.get('negated') and intent == 'preference': intent = 'negation'
    if final_entities.get('dislikes') and intent == 'preference': intent = 'dislike_statement'
        
    return {'intent': intent, 'entities': final_entities}


def call_mealdb_api(endpoint, params=None):
    url = MEALDB_API_BASE + endpoint; params = params or {}
    try:
        response = requests.get(url, params=params, timeout=15)
        if response.status_code == 429: time.sleep(5); response = requests.get(url, params=params, timeout=15)
        response.raise_for_status()
        data = response.json()
        return data.get('meals') 
    except requests.exceptions.Timeout: print(f"API Error: Timeout calling {endpoint}."); return None
    except requests.exceptions.ConnectionError: print(f"API Error: Connection error for {endpoint}."); return None
    except requests.exceptions.HTTPError as e:
        print(f"API Error: HTTP Error {response.status_code} for {endpoint}: {e}"); return None
    except requests.exceptions.RequestException as e: print(f"API Error: Request error for {endpoint}: {e}"); return None
    except json.JSONDecodeError: print(f"API Error: JSON decode error from {endpoint}."); return None
    except Exception as e: print(f"Unexpected API error for {endpoint}: {e}"); return None

def fetch_mealdb_lists():
    print("Fetching available lists from TheMealDB...")
    lists = {"categories": set(), "areas": set(), "ingredients": set()} 
    try:
        cat_data = call_mealdb_api("list.php?c=list")
        if cat_data: lists["categories"] = {item['strCategory'].lower() for item in cat_data if item and 'strCategory' in item and item['strCategory']}
        else: print("  - Failed to load categories or no categories returned.")
        
        area_data = call_mealdb_api("list.php?a=list")
        if area_data: lists["areas"] = {item['strArea'].lower() for item in area_data if item and 'strArea' in item and item['strArea']}
        else: print("  - Failed to load areas or no areas returned.")

        ing_data = call_mealdb_api("list.php?i=list")
        if ing_data: lists["ingredients"] = {item['strIngredient'].lower() for item in ing_data if item and 'strIngredient' in item and item['strIngredient']}
        else: print("  - Failed to load ingredients or no ingredients returned.")
    except Exception as e: print(f"An error occurred while fetching lists: {e}")
    print(f"  - Loaded {len(lists['categories'])} categories, {len(lists['areas'])} areas, {len(lists['ingredients'])} ingredients.")
    return lists["categories"], lists["areas"], lists["ingredients"]

def get_meal_details(meal_id):
    if not meal_id: return None
    meal_data_list = call_mealdb_api("lookup.php", {'i': meal_id})
    return meal_data_list[0] if meal_data_list else None

# --- Dietary and Dislike Checkers ---
def check_dietary_restrictions(meal_detail, preferences, preference_map):
    if not meal_detail: return True 
    dietary_pref_keys = preferences.get("dietary", [])
    if not dietary_pref_keys: return False

    ingredients_lower = {meal_detail.get(f'strIngredient{i}', '').strip().lower() for i in range(1, 21) if meal_detail.get(f'strIngredient{i}')}
    ingredients_lower.discard('') 

    violating_keywords = {"meat": set(), "dairy": set(), "eggs": set(), "gluten": set()}
    if "vegetarian" in dietary_pref_keys or "vegan" in dietary_pref_keys:
        for k_map in preference_map.get("known_meats", {}).values(): violating_keywords["meat"].update(k_map)
    if "vegan" in dietary_pref_keys or "dairy_free" in dietary_pref_keys: 
        for k_map in preference_map.get("known_dairy", {}).values(): violating_keywords["dairy"].update(k_map)
    if "vegan" in dietary_pref_keys: 
        violating_keywords["eggs"].update(preference_map.get("ingredient", {}).get("eggs", []))
    if "gluten_free" in dietary_pref_keys:
        for k_map in preference_map.get("known_gluten", {}).values(): violating_keywords["gluten"].update(k_map)

    for ing_str in ingredients_lower:
        if violating_keywords["meat"] and any(re.search(r'\b' + re.escape(kw) + r'\b', ing_str) for kw in violating_keywords["meat"]):
            if not re.search(r'\b(vegetarian|vegetable|veggie)\s+(broth|stock|bouillon)\b', ing_str, re.IGNORECASE): return True
        if violating_keywords["dairy"] and any(re.search(r'\b' + re.escape(kw) + r'\b', ing_str) for kw in violating_keywords["dairy"]):
            if not re.search(r'\b(dairy[- ]?free|lactose[- ]?free)\b', ing_str, re.IGNORECASE): return True
        if violating_keywords["eggs"] and any(re.search(r'\b' + re.escape(kw) + r'\b', ing_str) for kw in violating_keywords["eggs"]):
            return True 
        if violating_keywords["gluten"] and any(re.search(r'\b' + re.escape(kw) + r'\b', ing_str) for kw in violating_keywords["gluten"]):
            if not re.search(r'\bgluten[- ]?free\b', ing_str, re.IGNORECASE):
                if "soy sauce" in ing_str and not re.search(r'\b(tamari|gluten[- ]?free soy sauce)\b', ing_str, re.IGNORECASE): return True
                elif re.search(r'\b(oat|oats)\b', ing_str, re.IGNORECASE) and not re.search(r'\b(gluten[- ]?free oat|certified gluten[- ]?free)\b', ing_str, re.IGNORECASE): return True
                elif not ("soy sauce" in ing_str or re.search(r'\b(oat|oats)\b', ing_str, re.IGNORECASE)): return True
    return False

def check_dislikes(meal_detail, preferences, preference_map):
    if not meal_detail: return True
    dislike_item_keys = preferences.get("dislikes", []) 
    if not dislike_item_keys: return False

    all_disliked_keywords_to_check = set()
    for item_key in dislike_item_keys:
        # Check "dislikes" map first, then other relevant maps like ingredient, category
        all_disliked_keywords_to_check.update(kw.lower() for kw in preference_map.get("dislikes", {}).get(item_key, []))
        for pref_type in ["ingredient", "category", "cuisine"]: # Removed "flavor"
            all_disliked_keywords_to_check.update(kw.lower() for kw in preference_map.get(pref_type, {}).get(item_key, [item_key.lower()]))
    
    if not all_disliked_keywords_to_check: return False

    ingredients_lower = {meal_detail.get(f'strIngredient{i}', '').strip().lower() for i in range(1, 21) if meal_detail.get(f'strIngredient{i}')}
    ingredients_lower.discard('')
    
    for ing_str in ingredients_lower:
        if any(re.search(r'\b' + re.escape(dis_kw) + r'\b', ing_str) for dis_kw in all_disliked_keywords_to_check):
            return True
    meal_name_lower = meal_detail.get('strMeal', '').lower()
    meal_cat_lower = meal_detail.get('strCategory', '').lower()
    if any(re.search(r'\b' + re.escape(dis_kw) + r'\b', meal_name_lower) for dis_kw in all_disliked_keywords_to_check): return True
    if any(re.search(r'\b' + re.escape(dis_kw) + r'\b', meal_cat_lower) for dis_kw in all_disliked_keywords_to_check): return True
        
    return False

# --- Meal Filtering ---
def filter_meal_results(meals, preferences, preference_map, available_lists, force_detail_check=False, initial_search_type=None):
    if not meals: return []
    
    needs_detail_check = force_detail_check or \
                         any(preferences.get(key) for key in ["dislikes", "dietary"]) or \
                         (preferences.get("category") and initial_search_type != "category") or \
                         (preferences.get("cuisine") and initial_search_type != "cuisine") or \
                         (preferences.get("ingredient") and initial_search_type != "ingredient")

    if not needs_detail_check: return meals 

    print(f"\nFiltering {len(meals)} results (checking details)...")
    meals_to_keep = []
    details_cache = {} 

    for meal_summary in meals:
        meal_id = meal_summary.get('idMeal')
        if not meal_id: continue

        meal_detail = details_cache.get(meal_id)
        if not meal_detail:
            meal_detail = get_meal_details(meal_id) 
            if meal_detail: details_cache[meal_id] = meal_detail
            else: print(f"Warning: Could not fetch details for meal ID {meal_id}. Excluding."); continue
        
        if check_dislikes(meal_detail, preferences, preference_map): continue
        if check_dietary_restrictions(meal_detail, preferences, preference_map): continue

        secondary_cuisine_key = preferences.get("cuisine")[0] if len(preferences.get("cuisine",[])) == 1 and initial_search_type != "cuisine" else None
        if secondary_cuisine_key:
            meal_area_api = meal_detail.get('strArea', '').lower()
            expected_api_areas = {kw.lower() for kw_map_key, kw_list in preference_map.get("cuisine", {}).items() 
                                  if kw_map_key == secondary_cuisine_key for kw in kw_list 
                                  if kw.lower() in available_lists.get("areas",set())}
            if not expected_api_areas and secondary_cuisine_key.lower() in available_lists.get("areas",set()): 
                expected_api_areas.add(secondary_cuisine_key.lower())
            if expected_api_areas and meal_area_api not in expected_api_areas: continue
        
        secondary_category_key = preferences.get("category")[0] if len(preferences.get("category",[])) == 1 and initial_search_type != "category" else None
        if secondary_category_key:
            meal_cat_api = meal_detail.get('strCategory', '').lower()
            expected_api_cats = {kw.lower() for kw_map_key, kw_list in preference_map.get("category", {}).items() 
                                 if kw_map_key == secondary_category_key for kw in kw_list 
                                 if kw.lower() in available_lists.get("categories",set())}
            if not expected_api_cats and secondary_category_key.lower() in available_lists.get("categories",set()):
                expected_api_cats.add(secondary_category_key.lower())
            if expected_api_cats and meal_cat_api not in expected_api_cats: continue

        secondary_ingredient_key = preferences.get("ingredient")[0] if len(preferences.get("ingredient",[])) == 1 and initial_search_type != "ingredient" else None
        if secondary_ingredient_key:
            found_secondary_ingredient = False
            ingredient_keywords = preference_map.get("ingredient", {}).get(secondary_ingredient_key, [secondary_ingredient_key.lower()])
            for i in range(1, 21):
                ing_name = meal_detail.get(f'strIngredient{i}')
                if ing_name and ing_name.strip():
                    if any(re.search(r'\b' + re.escape(kw.lower()) + r'\b', ing_name.strip().lower()) for kw in ingredient_keywords):
                        found_secondary_ingredient = True
                        break
            if not found_secondary_ingredient:
                continue
        
        # Flavor check removed
        
        meals_to_keep.append(meal_summary)

    print(f"Finished filtering. {len(meals_to_keep)} meals remaining.")
    return meals_to_keep

# --- Dialogue State Machine ---
class DialogueState:
    START = "START"; FETCHING_LISTS = "FETCHING_LISTS"
    ASKING_CUISINE_INGREDIENT = "ASKING_CUISINE_INGREDIENT"
    ASKING_CATEGORY = "ASKING_CATEGORY" # ASKING_FLAVOR removed
    ASKING_DIETARY = "ASKING_DIETARY"; ASKING_DISLIKES = "ASKING_DISLIKES"
    CLARIFY_PREFERENCE = "CLARIFY_PREFERENCE"; HANDLE_NEGATION = "HANDLE_NEGATION"
    READY_TO_SEARCH = "READY_TO_SEARCH"; SEARCHING = "SEARCHING"
    SHOWING_RESULTS = "SHOWING_RESULTS"; GETTING_DETAILS = "GETTING_DETAILS"
    EXITING = "EXITING"; ERROR_STATE = "ERROR_STATE"

def chatbot_state_machine():
    preference_map = load_preference_map()
    if not preference_map: print("Critical error: Could not load preference map."); return

    # Removed "flavor" from preferences initialization
    preferences = {key: [] for key in preference_map if not key.startswith("known_") and key != "flavor"}
    current_state = DialogueState.START
    asked_this_session = set() 
    clarification_data = None
    available_lists = {"categories": set(), "areas": set(), "ingredients": set()}
    last_results = []
    displayed_meals = []
    last_intent_data = {} 

    # Define the fixed list of categories for examples
    FIXED_CATEGORY_EXAMPLES = ["Beef", "Breakfast", "Chicken", "Dessert", "Goat", "Lamb", "Miscellaneous", "Pasta", "Pork", "Seafood", "Side", "Starter", "Vegan", "Vegetarian"]


    # Removed ASKING_FLAVOR from the order
    SECONDARY_QUESTION_ORDER = [
        DialogueState.ASKING_CATEGORY,
        DialogueState.ASKING_DISLIKES,
        DialogueState.ASKING_DIETARY,
        #DialogueState.ASKING_FLAVOR, # Removed
        DialogueState.READY_TO_SEARCH
    ]

    def get_next_secondary_question_state(current_asked_set):
        for state in SECONDARY_QUESTION_ORDER:
            pref_type_map = {
                DialogueState.ASKING_CATEGORY: "category", DialogueState.ASKING_DISLIKES: "dislikes",
                DialogueState.ASKING_DIETARY: "dietary" # ASKING_FLAVOR removed
            }
            pref_type = pref_type_map.get(state)
            if pref_type and pref_type not in current_asked_set: return state
        return DialogueState.READY_TO_SEARCH

    while current_state != DialogueState.EXITING:
        user_input = ""

        if current_state == DialogueState.START: current_state = DialogueState.FETCHING_LISTS
        elif current_state == DialogueState.FETCHING_LISTS:
            categories, areas, ingredients = fetch_mealdb_lists()
            available_lists.update({"categories": categories or set(), "areas": areas or set(), "ingredients": ingredients or set()}) 
            if not all(available_lists.values()): print("\nWarning: Failed to load some essential lists.")
            print("\nWelcome! I'm here to help you decide what to eat.");
            current_state = DialogueState.ASKING_CUISINE_INGREDIENT
        
        elif current_state == DialogueState.ASKING_CUISINE_INGREDIENT:
            prompt_text = "\nDo you have a preferred cuisine and/or main ingredient in mind?"
            example_cuisines = random.sample(list(preference_map.get("cuisine",{}).keys()), min(len(preference_map.get("cuisine",{})), 5)) if preference_map.get("cuisine") else []
            example_ingredients = random.sample(list(preference_map.get("ingredient",{}).keys()), min(len(preference_map.get("ingredient",{})), 5)) if preference_map.get("ingredient") else []
            if not example_cuisines and available_lists["areas"]: example_cuisines = random.sample(list(available_lists["areas"]), min(len(available_lists["areas"]), 5))
            if not example_ingredients and available_lists["ingredients"]: example_ingredients = random.sample(list(available_lists["ingredients"]), min(len(available_lists["ingredients"]), 5))

            if example_cuisines: prompt_text += f"\n(e.g., Cuisines: {', '.join(c.title() for c in example_cuisines)})"
            if example_ingredients: prompt_text += f"\n(e.g., Ingredients: {', '.join(i.title() for i in example_ingredients)})"
            print(prompt_text)

            user_input = input("Cuisine/Ingredient: ").strip()
            if user_input.lower() == 'quit': current_state = DialogueState.EXITING; continue
            if user_input.lower() in ["skip", "any", "no", "none", ""]:
                asked_this_session.update(["cuisine", "ingredient"])
                current_state = get_next_secondary_question_state(asked_this_session); continue

            parsed_data = parse_input_nlp(user_input, preference_map, available_lists, current_asking_type=["cuisine", "ingredient"])
            last_intent_data = parsed_data
            intent, entities = parsed_data.get("intent", "unknown"), parsed_data.get("entities", {})

            if intent == "question": print("Sorry, I can search for meals, but I can't answer general questions yet."); continue
            if intent in ["negation", "dislike_statement"]: current_state = DialogueState.HANDLE_NEGATION; continue
            
            processed_here = False
            if intent == "preference":
                needs_clarification = False
                for key_type in ["cuisine", "ingredient"]:
                    if entities.get(key_type):
                        processed_here = True
                        current_vals = preferences.get(key_type, [])
                        combined_vals = list(set(current_vals + entities[key_type]))
                        preferences[key_type] = combined_vals
                        asked_this_session.add(key_type)
                        if len(combined_vals) > 1: 
                            clarification_data = {"type": key_type, "options": combined_vals, "original_prefs": current_vals}
                            needs_clarification = True; break 
                if processed_here:
                     print(f"Okay, I noted: { {k:v for k,v in preferences.items() if k in ['cuisine','ingredient'] and v} }")
                if needs_clarification: current_state = DialogueState.CLARIFY_PREFERENCE; continue
            
            if not processed_here and not (entities.get("cuisine") or entities.get("ingredient")): 
                print("Hmm, I didn't catch a specific cuisine or ingredient there. Let's try other questions.");
            
            asked_this_session.update(["cuisine", "ingredient"])
            current_state = get_next_secondary_question_state(asked_this_session); continue

        # Combined ASKING_CATEGORY, ASKING_DIETARY, ASKING_DISLIKES (Flavor removed)
        elif current_state in [DialogueState.ASKING_CATEGORY, DialogueState.ASKING_DIETARY, DialogueState.ASKING_DISLIKES]:
            pref_type_details = {
                DialogueState.ASKING_CATEGORY: ("category", "Any specific category for your meal?", FIXED_CATEGORY_EXAMPLES), # Use fixed examples
                DialogueState.ASKING_DIETARY: ("dietary", "Any dietary restrictions?", list(preference_map.get("dietary", {}).keys())),
                DialogueState.ASKING_DISLIKES: ("dislikes", "Are there any ingredients or specific food types you'd like to avoid?", [])
            }
            current_pref_type, question_text_base, example_source = pref_type_details[current_state]
            
            examples_to_show = random.sample(example_source, min(len(example_source), 5)) if example_source else []
            question_text = f"\n{question_text_base}"
            if examples_to_show: question_text += f" (e.g., {', '.join(e.replace('_',' ').title() for e in examples_to_show)})"
            
            print(question_text); user_input = input("Your answer: ").strip()

            if user_input.lower() == 'quit': current_state = DialogueState.EXITING; continue
            if user_input.lower() in ["skip", "any", "no", "none", ""]:
                asked_this_session.add(current_pref_type)
                current_state = get_next_secondary_question_state(asked_this_session); continue

            parsed_data = parse_input_nlp(user_input, preference_map, available_lists, current_asking_type=current_pref_type)
            last_intent_data = parsed_data 
            intent, entities = parsed_data.get("intent", "unknown"), parsed_data.get("entities", {})

            if intent == "question": print("Sorry, I can search for meals, but I can't answer general questions yet."); continue
            
            if current_pref_type == "dislikes": 
                current_state = DialogueState.HANDLE_NEGATION; continue
            
            if intent in ["negation", "dislike_statement"]: 
                current_state = DialogueState.HANDLE_NEGATION; continue

            if intent == "preference" and entities.get(current_pref_type):
                vals = entities[current_pref_type]
                print(f"Okay, I noted: {{'{current_pref_type}': {vals}}}")
                current_vals = preferences.get(current_pref_type, [])
                combined_vals = list(set(current_vals + vals))
                preferences[current_pref_type] = combined_vals
                asked_this_session.add(current_pref_type)

                if current_pref_type == "category" and len(combined_vals) > 1: 
                    clarification_data = {"type": current_pref_type, "options": combined_vals, "original_prefs": current_vals}
                    current_state = DialogueState.CLARIFY_PREFERENCE; continue
                current_state = get_next_secondary_question_state(asked_this_session); continue
            else: 
                other_prefs = {k:v for k,v in entities.items() if k not in [current_pref_type, 'negated', 'attributes'] and v}
                if other_prefs : print(f"Hmm, I didn't catch a specific {current_pref_type}, but noted: {other_prefs}")
                else: print(f"Hmm, I didn't catch a specific {current_pref_type} there.")
                asked_this_session.add(current_pref_type) 
                current_state = get_next_secondary_question_state(asked_this_session); continue
        
        elif current_state == DialogueState.HANDLE_NEGATION:
            entities_from_last_input = last_intent_data.get('entities', {})
            items_to_mark_as_disliked = set()

            items_to_mark_as_disliked.update(entities_from_last_input.get('negated', []))
            items_to_mark_as_disliked.update(entities_from_last_input.get('dislikes', []))
            for entity_type, entity_keys in entities_from_last_input.items():
                if entity_type not in ['negated', 'attributes', 'dislikes', 'flavor']: # Exclude flavor here too
                    items_to_mark_as_disliked.update(entity_keys)
            
            if items_to_mark_as_disliked:
                print(f"Okay, avoiding items related to: {', '.join(items_to_mark_as_disliked)}.")
                for item_key in items_to_mark_as_disliked:
                    if item_key not in preferences["dislikes"]:
                        preferences["dislikes"].append(item_key)
                    # Removed "flavor" from this loop
                    for pref_list_type in ["cuisine", "ingredient", "category", "dietary"]:
                        if item_key in preferences.get(pref_list_type, []):
                            preferences[pref_list_type].remove(item_key)
                            print(f"   - '{item_key}' removed from your '{pref_list_type}' preferences.")
            else:
                print("I understood you want to avoid something, but I'm not sure what specific items.")

            if "dislikes" not in asked_this_session: asked_this_session.add("dislikes")
            current_state = get_next_secondary_question_state(asked_this_session); continue
            
        elif current_state == DialogueState.CLARIFY_PREFERENCE:
            if clarification_data:
                pref_type, options, original_prefs = clarification_data["type"], clarification_data["options"], clarification_data.get("original_prefs", [])
                print(f"\nYou mentioned a few {pref_type}s: {', '.join(options)}."); print(f"Which one specific {pref_type} should I focus on?")
                user_input = input(f"Choose one {pref_type}: ").strip()
                if user_input.lower() == 'quit': current_state = DialogueState.EXITING; continue
                
                parsed_clarification = parse_input_nlp(user_input, preference_map, available_lists, current_asking_type=pref_type)
                best_match = next((opt for opt in parsed_clarification.get('entities', {}).get(pref_type, []) if opt in options), None)
                
                if best_match:
                    print(f"Okay, focusing on {pref_type}: {best_match}."); preferences[pref_type] = [best_match]
                else:
                    print(f"Sorry, I didn't match that. Keeping previous {pref_type} options."); preferences[pref_type] = original_prefs
                clarification_data = None; asked_this_session.add(pref_type)
                current_state = get_next_secondary_question_state(asked_this_session); continue
            else: 
                current_state = DialogueState.ASKING_CUISINE_INGREDIENT; continue

        elif current_state == DialogueState.READY_TO_SEARCH:
            print("\nOkay, I have your preferences:")
            has_primary_search_term = False; positive_prefs_printed = False
            for key, val_list in preferences.items():
                # Exclude flavor from summary as well
                if val_list and key not in ["dislikes", "_primary_search_keys", "flavor"]:
                    print(f"- {key.replace('_',' ').title()}: {', '.join(val_list)}")
                    positive_prefs_printed = True
                    if key in ["ingredient", "category", "cuisine"]: has_primary_search_term = True
            if preferences.get("dislikes"): print(f"- Avoiding: {', '.join(preferences['dislikes'])}")
            if not positive_prefs_printed and not preferences.get("dislikes"): print("(No preferences specified yet.)")
            
            if not has_primary_search_term:
                print("\nI need a main ingredient, category, or cuisine to search effectively.")
                if not (preferences.get("dislikes") and not positive_prefs_printed): 
                    asked_this_session.discard("cuisine"); asked_this_session.discard("ingredient"); asked_this_session.discard("category")
                    current_state = DialogueState.ASKING_CUISINE_INGREDIENT; continue
            
            search_confirm = input("Ready to search for meals? (yes/no): ").strip().lower()
            if search_confirm == 'yes': current_state = DialogueState.SEARCHING
            elif search_confirm == 'quit': current_state = DialogueState.EXITING
            else: asked_this_session.clear(); current_state = DialogueState.ASKING_CUISINE_INGREDIENT
            continue

        elif current_state == DialogueState.SEARCHING:
            pref_cuisine_key = preferences.get("cuisine")[0] if preferences.get("cuisine") else None
            pref_ingredient_key = preferences.get("ingredient")[0] if preferences.get("ingredient") else None
            pref_category_key = preferences.get("category")[0] if preferences.get("category") else None
            
            found_meals = []
            
            def get_api_val(p_key, p_map_type, api_list_name):
                if not p_key: return None
                kws = preference_map.get(p_map_type, {}).get(p_key, [p_key.lower()])
                val = next((kw.lower() for kw in kws if kw.lower() in available_lists.get(api_list_name, set())), None)
                return val if val else (p_key.lower() if p_key.lower() in available_lists.get(api_list_name, set()) else p_key)

            api_val_cuisine = get_api_val(pref_cuisine_key, "cuisine", "areas")
            api_val_ingredient = get_api_val(pref_ingredient_key, "ingredient", "ingredients")
            api_val_category = get_api_val(pref_category_key, "category", "categories")

            search_attempts = []
            if api_val_cuisine: search_attempts.append({"type": "cuisine", "value": api_val_cuisine, "param": "a"})
            if api_val_ingredient: search_attempts.append({"type": "ingredient", "value": api_val_ingredient, "param": "i"})
            if api_val_category: search_attempts.append({"type": "category", "value": api_val_category, "param": "c"})


            for attempt_num, attempt_info in enumerate(search_attempts):
                if found_meals: break 

                search_param = {attempt_info["param"]: attempt_info["value"]}
                search_strategy_used = f"Primary filter: {attempt_info['type']}={attempt_info['value']}"
                print(f"\nAttempt {attempt_num+1}: Searching by {attempt_info['type']} '{attempt_info['value']}'...")
                
                initial_meals = call_mealdb_api("filter.php", search_param)
                search_type_used_for_this_attempt = attempt_info["type"] 
                
                if initial_meals:
                    print(f"Initial search yielded {len(initial_meals)} meals. Applying further filters...")
                    current_found_meals = filter_meal_results(initial_meals, preferences, preference_map, available_lists, initial_search_type=search_type_used_for_this_attempt)
                    if current_found_meals:
                        found_meals = current_found_meals
                        print(f"Found {len(found_meals)} meals matching all criteria with this attempt.")
                        break 
                    else:
                        print("No meals matched all criteria after filtering for this attempt.")
                else:
                    print(f"No meals found directly by {attempt_info['type']} '{attempt_info['value']}'.")

            if not found_meals: 
                print("\nAll primary search attempts failed to find meals matching all criteria.")
                print("Trying to find a random meal suggestion (checking all preferences)...")
                search_strategy_used = "random"; random_candidates = []
                for _ in range(5): 
                    meal_list = call_mealdb_api("random.php")
                    if meal_list and (not random_candidates or meal_list[0]['idMeal'] not in [m['idMeal'] for m in random_candidates]):
                         random_candidates.append(meal_list[0])
                    time.sleep(0.1) 
                if random_candidates:
                    found_meals = filter_meal_results(random_candidates, preferences, preference_map, available_lists, force_detail_check=True, initial_search_type="random")

            if found_meals:
                last_results = found_meals; displayed_meals = []; current_state = DialogueState.SHOWING_RESULTS
            else:
                print(f"\nSorry, I couldn't find any meals matching your criteria, even with random suggestions.");
                retry = input("Try again ('retry'), start over ('start over'), or 'quit'?: ").strip().lower()
                if retry == 'start over': preferences = {k:[] for k in preferences if k != "flavor"}; asked_this_session.clear(); current_state = DialogueState.ASKING_CUISINE_INGREDIENT
                elif retry == 'retry': asked_this_session.clear(); current_state = DialogueState.ASKING_CUISINE_INGREDIENT
                else: current_state = DialogueState.EXITING
            continue
            
        elif current_state == DialogueState.SHOWING_RESULTS:
            max_suggestions = 5; start_index = len(displayed_meals); next_batch = last_results[start_index : start_index + max_suggestions]
            if not next_batch:
                print("No more results to show." if start_index > 0 else "No meals found.")
                current_state = DialogueState.GETTING_DETAILS; continue 
            print("\nHere are some meal ideas:");
            for i, meal in enumerate(next_batch): print(f"  {start_index + i + 1}. {meal.get('strMeal')}")
            displayed_meals.extend(next_batch)
            current_state = DialogueState.GETTING_DETAILS; continue

        elif current_state == DialogueState.GETTING_DETAILS:
            choice_input = input(f"\nEnter number (1-{len(displayed_meals)}) for details, 'more', 'search again', 'start over', or 'quit': ").strip().lower()
            if choice_input == 'quit': current_state = DialogueState.EXITING; continue
            if choice_input == 'more': current_state = DialogueState.SHOWING_RESULTS; continue
            if choice_input == 'search again': current_state = DialogueState.SEARCHING; continue
            if choice_input == 'start over': 
                preferences = {k:[] for k in preferences if k != "flavor"}
                asked_this_session.clear(); 
                current_state = DialogueState.ASKING_CUISINE_INGREDIENT; continue
            if choice_input.isdigit():
                try:
                    idx = int(choice_input) - 1
                    if 0 <= idx < len(displayed_meals):
                        details = get_meal_details(displayed_meals[idx]['idMeal'])
                        if details:
                            print(f"\n--- {details.get('strMeal')} ---")
                            print(f"Category: {details.get('strCategory')}, Area: {details.get('strArea')}")
                            if details.get('strTags'): print(f"Tags: {details.get('strTags')}")
                            print("\nIngredients:")
                            for i in range(1, 21):
                                ing = details.get(f'strIngredient{i}')
                                measure = details.get(f'strMeasure{i}')
                                if ing and ing.strip(): print(f"- {measure.strip() if measure else ''} {ing.strip()}")
                            print("\nInstructions:\n" + "\n".join(line.strip() for line in details.get('strInstructions','').splitlines() if line.strip()))
                            if details.get('strYoutube'): print(f"\nYouTube: {details.get('strYoutube')}")
                            if details.get('strSource'): print(f"Source: {details.get('strSource')}")

                            if input("\nLooks good? ('yes' to finish / 'no' for other options): ").lower() == 'yes': current_state = DialogueState.EXITING
                        else: print("Sorry, couldn't fetch details.")
                    else: print("Invalid number.")
                except ValueError: print("Invalid input.")
            else: print("Invalid input.")
            continue

        elif current_state == DialogueState.ERROR_STATE:
            print("\nAn unexpected error occurred. Restarting dialogue."); time.sleep(1)
            preferences = {k:[] for k in preferences if k != "flavor"}; asked_this_session.clear(); last_intent_data={}; 
            current_state = DialogueState.START; continue 

    print("\nHappy cooking!")

if __name__ == "__main__":
    chatbot_state_machine()
