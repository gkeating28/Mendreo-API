"""Built-in app tour steps. Ids and platforms are not editable."""

TITLE_MAX = 80
BODY_MAX = 500


def _step(step_id: str, title: str, body: str, platforms: tuple[str, ...]) -> dict:
    return {
        "id": step_id,
        "title": title,
        "body": body,
        "platforms": list(platforms),
    }


DEFAULT_TOUR_STEPS = [
    _step(
        "hero",
        "Start where the day is",
        "Welcome to Mendreo. This is your home card. It reads the day back to you, "
        "and it's a good place to land before you decide what to do.",
        ("web", "mobile"),
    ),
    _step(
        "home-tiles",
        "Four places to start",
        "Exercise, Talk, Progress and Resources. These four tiles are how you "
        "reach the main parts of the app.",
        ("web", "mobile"),
    ),
    _step(
        "nav-main",
        "Always within reach",
        "The same four sections are always close by, wherever you are in the app.",
        ("web",),
    ),
    _step(
        "nav-bar",
        "Always within reach",
        "The same four sections are always close by, wherever you are in the app.",
        ("mobile",),
    ),
    _step(
        "chat-practice",
        "Chat with Toni",
        "This is where we talk. There's a practice chat you can try first, "
        "so you can see how it works.",
        ("web", "mobile"),
    ),
    _step(
        "exercise-tabs",
        "Practice, then reflect",
        "Practice has short guided exercises. Reflect collects what you wrote "
        "afterwards, and that's where your progress really shows up.",
        ("web", "mobile"),
    ),
    _step(
        "exercise-practice",
        "Try a practice exercise",
        "There's a short practice exercise you can try, and nothing you do in it "
        "is saved. It's a good way to see how exercises work.",
        ("web", "mobile"),
    ),
    _step(
        "progress-tabs",
        "Switch the view",
        "Switch between your different progress views here.",
        ("web", "mobile"),
    ),
    _step(
        "progress-feelings",
        "Anxiety and positive emotion",
        "This is your daily check-in: how anxious you felt, and how much positive "
        "emotion you had. You can add today's check-in from this card.",
        ("web", "mobile"),
    ),
    _step(
        "progress-insights",
        "Your insights",
        "Insights pull out the themes running through your check-ins and the "
        "measures recorded in this range.",
        ("web",),
    ),
    _step(
        "progress-practice",
        "Practice log",
        "This shows the exercise sessions you've completed, so you can see how "
        "often you've been practising.",
        ("web", "mobile"),
    ),
]

STEPS_BY_ID = {step["id"]: step for step in DEFAULT_TOUR_STEPS}
STEP_IDS = tuple(STEPS_BY_ID)
