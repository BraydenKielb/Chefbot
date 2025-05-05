#food class
class Food:
    def __init__(self, name, tags):
        self.name = name
        self.tags = tags
        self.score = 0

    def matches(self, tag):
        return tag in self.tags

    def increment_score(self):
        self.score += 1


#list of all the food objects that the bot can pick from
foods = [Food("Pancakes", ["sweet", "breakfast", "vegetarian"]),
    Food("Grilled Chicken", ["savory", "lunch", "dinner", "meat", "healthy"]),
    Food("Steak", ["savory", "dinner", "meat"]),
    Food("Pretzel", ["salty", "snack", "vegetarian"]),
    Food('Pizza', ['unhealthy', 'cheesy', 'lunch', 'dinner']),
    Food("Burger", ['unhealthy', 'meat', 'salty', 'lunch', 'dinner']),
    Food('Chicken Noodle Soup', ['healthy', 'lunch', 'dinner', 'meat']),
    Food('Fruit Salad', ['vegetarian', 'healthy', 'lunch']),
    Food('Chips', ['salty', 'unhealthy', 'snack']),
    Food('Eggs', ['breakfast', 'healthy', 'vegetarian'])
         ]


questions = [
    ("Is this for breakfast?", "breakfast"),
    ("Are you looking for a dinner option?", "dinner"),
    ("Is this for lunch?", "lunch"),
    ("Are you looking for a snack?", 'snack'),
    ("Do you want something sweet?", "sweet"),
    ("Do you want it to be vegetarian?", "vegetarian"),
    ("Do you want something healthy?", "healthy"),
    ("Do you want something salty?", "salty")
]

#working logic for bot
session = {
    "current_q": 0,  # Track the current question index
    "scores": {food.name: 0 for food in foods}  # Track food scores
}

while session["current_q"] < len(questions):
    # Ask the current question
    question = questions[session["current_q"]][0]
    print(question)

    user_input = input("Your answer (yes/no): ").strip().lower()

    if "yes" in user_input:
        tag = questions[session["current_q"]][1]  # Get the tag for the current question
        for food in foods:
            if food.matches(tag):
                food.increment_score()

    #skip other time of meal questions if input is yes
    if "breakfast" in questions[session["current_q"]][1] and 'yes' in user_input:
        session["current_q"] += 4
    elif 'lunch' in questions[session["current_q"]][1] and 'yes' in user_input:
        session["current_q"] += 2
    elif 'dinner' in questions[session["current_q"]][1] and 'yes' in user_input:
        session["current_q"] += 3
    else:
        session["current_q"] += 1

# After all questions, recommend the top food
top_food = max(foods, key=lambda f: f.score)
print(f"\nYou should make {top_food.name}!")