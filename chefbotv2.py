import random
import json
import sys
import re
import requests # Required for making API calls

# --- Constants ---
# WARNING: Storing API keys directly in code is insecure. Use environment variables or config files.
API_KEY = "qo0PbeqRqjMThRjJ3DSj52WseXpEHQ0uJ7ZjUMvA"
API_BASE_URL = "https://api.nal.usda.gov/fdc/v1"
SEARCH_PAGE_SIZE = 10 # Max results to fetch from API search
DATA_TYPES = ["Foundation"] # Only search Foundation foods as requested
QUESTIONS_FILE = "questions.json"
TAG_KEYWORDS_FILE = "tag_keywords.json" # File for supplementary keywords

# --- Classes ---

class Food:
    """Represents a food item with its attributes (tags), potentially loaded from API."""
    def __init__(self, name, tags, fdc_id=None, category=None):
        """
        Initializes a Food object.

        Args:
            name (str): The name of the food.
            tags (list): A list of strings describing the food.
            fdc_id (int, optional): The FoodData Central ID. Defaults to None.
            category (str, optional): The food category description from API. Defaults to None.
        """
        if not isinstance(name, str) or not name:
            raise ValueError("Food name must be a non-empty string.")
        if not isinstance(tags, list) or not all(isinstance(tag, str) for tag in tags):
             if tags: # Only raise error if tags list is provided but invalid
                 raise ValueError("Tags must be a list of strings.")

        self.name = name
        self.tags = set(tag.lower() for tag in tags)
        self.score = 0
        self.fdc_id = fdc_id # Store FDC ID if available
        self.category = category # Store category if available

    def has_tag(self, tag):
        """Checks if the food has a specific tag."""
        return tag.lower() in self.tags

    def __str__(self):
        """String representation of the food."""
        tag_str = ', '.join(sorted(self.tags)) if self.tags else "No Tags Derived"
        category_str = f" (Category: {self.category})" if self.category else ""
        fdc_id_str = f" [FDC ID: {self.fdc_id}]" if self.fdc_id else ""
        return f"{self.name}{category_str}{fdc_id_str} (Tags: {tag_str})"

    def __repr__(self):
        """Detailed representation for debugging."""
        return f"Food(name='{self.name}', tags={list(self.tags)}, fdc_id={self.fdc_id}, category='{self.category}')"


class Question:
    """Represents a question asked to the user to determine preferences."""
    def __init__(self, text, positive_tag, negative_tag=None, category=None, phase="secondary"):
        """
        Initializes a Question object.

        Args:
            text (str): The question text to display to the user.
            positive_tag (str): The tag associated with a 'yes' answer.
            negative_tag (str, optional): Tag associated with 'no'. Defaults to None.
            category (str, optional): Category for grouping (e.g., 'meal_time'). Defaults to None.
            phase (str): When to ask the question ('initial' or 'secondary'). Defaults to 'secondary'.
        """
        if not isinstance(text, str) or not text:
             raise ValueError("Question text must be a non-empty string.")
        if not isinstance(positive_tag, str) or not positive_tag:
             raise ValueError("Positive tag must be a non-empty string.")
        if phase not in ["initial", "secondary"]:
             raise ValueError("Phase must be 'initial' or 'secondary'.")

        self.text = text
        self.positive_tag = positive_tag.lower()
        self.negative_tag = negative_tag.lower() if isinstance(negative_tag, str) else None
        self.category = category.lower() if isinstance(category, str) else None
        self.phase = phase # Store the phase

    def __repr__(self):
        """Detailed representation for debugging."""
        return (f"Question(text='{self.text}', positive_tag='{self.positive_tag}', "
                f"negative_tag='{self.negative_tag}', category='{self.category}', phase='{self.phase}')")


class FoodRecommender:
    """Handles recommending food by querying the USDA API and scoring results."""

    def __init__(self, api_key, questions, tag_keywords):
        """
        Initializes the FoodRecommender with API key, questions, and tag keywords.

        Args:
            api_key (str): Your USDA FoodData Central API key.
            questions (list): A list of Question objects.
            tag_keywords (dict): A dictionary mapping tags to lists of keywords.
        """
        if not api_key:
            raise ValueError("API key is required.")
        if not questions:
             raise ValueError("Question list cannot be empty.")
        if tag_keywords is None: # Check if loading failed
             print("Warning: Tag keywords not loaded. Tag derivation will be limited.")
             tag_keywords = {} # Use empty dict to avoid errors

        self.api_key = api_key
        self.questions = questions
        self.tag_keywords = tag_keywords # Store loaded keywords
        self.foods = [] # Foods will be populated from API results
        self.answered_categories = set()
        self.initial_preferences = [] # Store tags from initial 'yes' answers

    def _derive_tags_from_api(self, description, category_desc):
        """
        Derives tags primarily from API category, supplemented by description keywords
        using the loaded tag_keywords dictionary.

        Args:
            description (str): Food description from API.
            category_desc (str): Food category description from API.

        Returns:
            list: A list of derived tags.
        """
        tags = set()
        description_lower = description.lower() if description else ""
        category_lower = category_desc.lower() if category_desc else ""

        # 1. Add category as primary tags (split multi-word categories)
        if category_lower:
            category_tags = re.split(r'[,\s/-]+', category_lower)
            tags.update(tag for tag in category_tags if tag)
            tags.add(category_lower.replace(" ", "_"))

        # 2. Simple keyword matching using loaded keywords
        # Check description for keywords from the loaded dictionary
        for tag, keywords in self.tag_keywords.items():
            # Ensure keywords is actually a list (robustness for bad JSON)
            if isinstance(keywords, list):
                 if any(keyword.lower() in description_lower for keyword in keywords):
                     tags.add(tag.lower()) # Ensure tag is lowercase
            else:
                 print(f"Warning: Invalid keyword list for tag '{tag}' in loaded keywords.")


        # 3. Logic for vegetarian/meat based on derived tags
        meat_tags = {"meat", "poultry", "fish", "seafood"}
        plant_based_tags = {"vegetable", "fruit", "grain", "nut", "seed", "legume"}
        animal_non_meat = {"dairy", "egg"}

        if any(mtag in tags for mtag in meat_tags):
            tags.discard("vegetarian")
        elif any(ptag in tags for ptag in plant_based_tags) or any(atag in tags for atag in animal_non_meat):
             if not any(mtag in tags for mtag in meat_tags):
                  # Check if 'vegetarian' is a valid tag in our loaded keywords before adding
                  if 'vegetarian' in self.tag_keywords:
                       tags.add("vegetarian")

        return list(tags)

    def _search_foods_api(self, query_terms):
        """
        Searches the USDA API for foods based on query terms.

        Args:
            query_terms (list): A list of strings to include in the search query.

        Returns:
            list: A list of Food objects created from API results, or empty list on failure.
        """
        if not query_terms:
            print("Warning: No search terms provided for API query.")
            return []

        search_query = " ".join(query_terms)
        print(f"\nSearching API for: '{search_query}'...")

        params = {
            "api_key": self.api_key,
            "query": search_query,
            "dataType": ",".join(DATA_TYPES),
            "pageSize": SEARCH_PAGE_SIZE,
        }

        try:
            response = requests.get(f"{API_BASE_URL}/foods/search", params=params, timeout=15)
            response.raise_for_status()

            data = response.json()
            api_foods = data.get("foods", [])

            if not api_foods:
                print("API search returned no results.")
                return []

            print(f"Found {len(api_foods)} potential foods from API.")
            processed_foods = []
            for item in api_foods:
                name = item.get("description")
                fdc_id = item.get("fdcId")
                category = item.get("foodCategory")

                if name and fdc_id:
                    # Use the instance method to derive tags with loaded keywords
                    tags = self._derive_tags_from_api(name, category)
                    try:
                        food_obj = Food(name, tags, fdc_id, category)
                        processed_foods.append(food_obj)
                    except ValueError as ve:
                        print(f"Warning: Skipping invalid food item from API {name}: {ve}")

            return processed_foods

        except requests.exceptions.RequestException as e:
            print(f"Error during API request: {e}")
            return []
        except json.JSONDecodeError:
            print("Error: Could not decode JSON response from API.")
            return []
        except Exception as e:
            print(f"An unexpected error occurred during API search: {e}")
            return []


    def _ask_questions_by_phase(self, phase):
        """
        Asks questions designated for a specific phase ('initial' or 'secondary').

        Args:
            phase (str): The phase ('initial' or 'secondary').

        Returns:
            bool: True if questions were asked, False otherwise.
        """
        questions_asked = False
        phase_questions = [q for q in self.questions if q.phase == phase]

        if not phase_questions:
            return False

        for question in phase_questions:
            if question.category and question.category in self.answered_categories:
                 continue

            questions_asked = True
            while True:
                print(f"\nQ: {question.text}")
                user_input = input("Your answer (yes/no/skip): ").strip().lower()

                if user_input == "yes":
                    print(f"  -> Okay, preference: '{question.positive_tag}'.")
                    if phase == "initial":
                        self.initial_preferences.append(question.positive_tag)
                    elif phase == "secondary" and self.foods:
                        for food in self.foods:
                            if food.has_tag(question.positive_tag):
                                food.score += 1
                            elif question.negative_tag and food.has_tag(question.negative_tag):
                                 food.score -= 1

                    if question.category:
                        self.answered_categories.add(question.category)
                    break

                elif user_input == "no":
                    print(f"  -> Okay, avoiding '{question.positive_tag}'.")
                    if phase == "secondary" and self.foods:
                         tag_to_avoid = question.positive_tag
                         if question.negative_tag:
                              print(f"  -> Preferring '{question.negative_tag}' if applicable.")
                         for food in self.foods:
                              if food.has_tag(tag_to_avoid):
                                   food.score -= 1
                              elif question.negative_tag and food.has_tag(question.negative_tag):
                                   food.score += 1
                    break

                elif user_input == "skip":
                     print("  -> Okay, skipping this question.")
                     break
                else:
                    print("   Invalid input. Please enter 'yes', 'no', or 'skip'.")

        return questions_asked

    def recommend(self):
        """Runs the recommendation process using the API search flow."""
        self.foods = []
        self.answered_categories = set()
        self.initial_preferences = []

        print("Let's find something for you to eat!")
        print("First, some initial questions to guide the search...")

        # --- Phase 1: Initial Questions ---
        if not self._ask_questions_by_phase("initial"):
             print("No initial questions configured. Cannot perform API search effectively.")
             return

        # Add optional keyword input
        keyword = input("\nEnter an optional keyword (e.g., 'chicken', 'salad', 'soup') or press Enter to skip: ").strip().lower()
        if keyword:
            self.initial_preferences.append(keyword)

        # --- API Search ---
        if not self.initial_preferences:
            print("\nNo preferences gathered from initial questions. Cannot search API.")
            return

        self.foods = self._search_foods_api(self.initial_preferences)

        if not self.foods:
            print("\nCould not find suitable foods from the API based on initial preferences.")
            return

        print(f"\nFound {len(self.foods)} candidates. Now, let's refine your preferences...")

        # --- Phase 2: Secondary Questions for Scoring API Results ---
        self._ask_questions_by_phase("secondary")

        # --- Recommendation Logic ---
        if not self.foods:
             print("\nSomething went wrong, no foods to recommend.")
             return

        max_score = -float('inf')
        for food in self.foods:
             max_score = max(max_score, food.score)

        top_foods = [food for food in self.foods if food.score == max_score]

        # --- Output Results ---
        print("\n--- Recommendation ---")
        if not top_foods or max_score < 0:
            print("Hmm, none of the options strongly matched all your preferences after filtering.")
            least_penalized = sorted(self.foods, key=lambda f: f.score, reverse=True)
            if least_penalized:
                 print(f"Maybe try {least_penalized[0].name}? It was the closest option.")
                 print(f"Details: {least_penalized[0]}")

        elif len(top_foods) == 1:
            print(f"Based on your answers, you should make: {top_foods[0].name}!")
            print(f"Details: {top_foods[0]}")
        else:
            positive_top_foods = [food for food in top_foods if food.score >= 0]
            if not positive_top_foods:
                 print("Hmm, none of the options strongly matched all your preferences after filtering.")
                 least_penalized = sorted(self.foods, key=lambda f: f.score, reverse=True)
                 if least_penalized:
                      print(f"Maybe try {least_penalized[0].name}? It was the closest option.")
                      print(f"Details: {least_penalized[0]}")
            elif len(positive_top_foods) == 1:
                  print(f"Based on your answers, you should make: {positive_top_foods[0].name}!")
                  print(f"Details: {positive_top_foods[0]}")
            else:
                 print("Found multiple good options for you:")
                 for food in positive_top_foods:
                     print(f"- {food.name} (Score: {food.score})")
                 chosen = random.choice(positive_top_foods)
                 print(f"\nMaybe try {chosen.name} today?")
                 print(f"Details: {chosen}")


# --- Data Loading Functions ---

def load_questions_from_json(filepath=QUESTIONS_FILE):
    """
    Loads question data from a JSON file.
    Expects each question object to have a "phase" key ('initial' or 'secondary').
    """
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            data = json.load(f)
            if not isinstance(data, list):
                print(f"Error: JSON data in '{filepath}' is not a list.")
                return []
            questions_list = []
            for item in data:
                 if isinstance(item, dict) and all(k in item for k in ['text', 'positive_tag', 'phase']):
                     try:
                         question_obj = Question(
                             item['text'],
                             item['positive_tag'],
                             item.get('negative_tag'),
                             item.get('category'),
                             item['phase']
                         )
                         questions_list.append(question_obj)
                     except ValueError as ve:
                          print(f"Warning: Skipping invalid question item '{item.get('text', 'UNKNOWN')}': {ve}")
                 else:
                      print(f"Warning: Skipping invalid item in question JSON (missing text, positive_tag, or phase): {item}")
            return questions_list
    except FileNotFoundError:
        print(f"Error: Question data file '{filepath}' not found.")
        return []
    except json.JSONDecodeError:
        print(f"Error: Could not decode JSON from '{filepath}'. Check the file format.")
        return []
    except Exception as e:
        print(f"An unexpected error occurred while loading questions from {filepath}: {e}")
        return []

def load_tag_keywords_from_json(filepath=TAG_KEYWORDS_FILE):
    """
    Loads the tag-to-keywords mapping from a JSON file.

    Args:
        filepath (str): The path to the JSON file.

    Returns:
        dict: A dictionary mapping tags to lists of keywords, or None if loading fails.
    """
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            data = json.load(f)
            if not isinstance(data, dict):
                 print(f"Error: JSON data in '{filepath}' is not a dictionary.")
                 return None
            # Optional: Add validation here to check if values are lists of strings
            return data
    except FileNotFoundError:
        print(f"Error: Tag keywords file '{filepath}' not found.")
        return None
    except json.JSONDecodeError:
        print(f"Error: Could not decode JSON from '{filepath}'. Check the file format.")
        return None
    except Exception as e:
        print(f"An unexpected error occurred while loading tag keywords from {filepath}: {e}")
        return None


# --- Main Execution ---
if __name__ == "__main__":
    # Load external data
    all_questions = load_questions_from_json()
    tag_keywords = load_tag_keywords_from_json()

    # --- Critical Checks ---
    if not all_questions:
         print("\nError loading necessary question data. Exiting.")
         print(f" -> Ensure '{QUESTIONS_FILE}' exists, is valid JSON, and questions have a 'phase' key.")
         sys.exit(1)
    if tag_keywords is None:
         print(f"\nError loading tag keywords from '{TAG_KEYWORDS_FILE}'. Exiting.")
         # Decide if you want to exit or continue with limited tagging
         sys.exit(1) # Exit if keywords are considered essential
         # Alternatively: print("Warning: Continuing without supplementary keywords.") tag_keywords = {}

    if not any(q.phase == 'initial' for q in all_questions):
         print(f"\nError: No questions marked with phase 'initial' found in '{QUESTIONS_FILE}'.")
         print("Cannot proceed without initial questions to guide the API search.")
         sys.exit(1)


    # --- Proceed with Recommendation ---
    print(f"Successfully loaded {len(all_questions)} questions.")
    print(f"Successfully loaded {len(tag_keywords)} tag keyword categories.")

    # Create the recommender, passing the loaded keywords
    recommender = FoodRecommender(API_KEY, all_questions, tag_keywords)
    recommender.recommend()

    print("\n--------------------------------------------------")
    print("Reminder: This version recommends a single food item based on API results.")
    print("Meal combination logic is not yet implemented.")
    print("--------------------------------------------------")

