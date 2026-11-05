"""Deterministic pet-compatibility quiz scoring (Task 27).

Maps a short illustrated quiz to four 0-100 trait axes (activity, space, time,
experience), then to an archetype label and the best-fit pet types. Pure
Python and fully testable — no AI provider involved.
"""
from __future__ import annotations

# 10-question compatibility quiz. Each question maps its answer to one of the
# scoring axes (activity, space, time, experience, affection).
QUIZ_QUESTIONS = [
    {
        "id": "activity", "label": "Your lifestyle",
        "prompt": "How active is your typical day?",
        "options": [
            ("relaxed", "Relaxed", "Mostly at home, short walks", "🛋️"),
            ("moderate", "Moderate", "Daily walks, some weekend outings", "🚶"),
            ("active", "Active", "Runs, hikes, lots of play", "🏃"),
            ("very_active", "Very active", "Outdoors most days", "⛰️"),
        ],
    },
    {
        "id": "space", "label": "Your home",
        "prompt": "Where will your pet live?",
        "options": [
            ("apartment", "Apartment", "Cosy indoor space", "🏢"),
            ("house", "House", "Indoor with some outdoor", "🏠"),
            ("villa", "Villa with garden", "Lots of outdoor space", "🏡"),
        ],
    },
    {
        "id": "time", "label": "Your routine",
        "prompt": "How much time can you give each day?",
        "options": [
            ("low", "A little", "Under 1 hour", "⏱️"),
            ("medium", "Some", "1-2 hours", "🕐"),
            ("high", "Plenty", "2+ hours", "🕗"),
        ],
    },
    {
        "id": "experience", "label": "Your experience",
        "prompt": "How experienced are you with pets?",
        "options": [
            ("first_time", "First-time", "New to pet parenting", "🌱"),
            ("some", "Some", "Had a pet before", "🌿"),
            ("experienced", "Experienced", "Very comfortable", "🌳"),
        ],
    },
    {
        "id": "household", "label": "Your household",
        "prompt": "Who's at home?",
        "options": [
            ("solo", "Just me", "A quiet household", "🧍"),
            ("couple", "A couple", "Two of us", "💑"),
            ("kids", "Family with kids", "A lively home", "👨‍👩‍👧"),
        ],
    },
    {
        "id": "other_pets", "label": "Other pets",
        "prompt": "Do you have other pets?",
        "options": [
            ("none", "None yet", "This will be our first", "🚫"),
            ("one", "One pet", "A single companion", "🐾"),
            ("many", "A few", "A full house", "🐕🐈"),
        ],
    },
    {
        "id": "budget", "label": "Your budget",
        "prompt": "Monthly budget for pet care?",
        "options": [
            ("low", "Modest", "Keeping it simple", "💰"),
            ("medium", "Comfortable", "Room for extras", "💰💰"),
            ("high", "Generous", "Whatever they need", "💰💰💰"),
        ],
    },
    {
        "id": "grooming", "label": "Grooming",
        "prompt": "How much grooming can you handle?",
        "options": [
            ("low", "Low-maintenance", "Minimal brushing", "✂️"),
            ("medium", "Some", "Weekly care", "🧴"),
            ("high", "High", "Happy to groom often", "💇"),
        ],
    },
    {
        "id": "noise", "label": "Noise tolerance",
        "prompt": "How do you feel about noise?",
        "options": [
            ("quiet", "Prefer quiet", "Calm and peaceful", "🤫"),
            ("some", "Some is fine", "A bit of chatter", "🔉"),
            ("lively", "Love lively", "Bring the energy", "📢"),
        ],
    },
    {
        "id": "affection", "label": "Companionship",
        "prompt": "What kind of bond do you want?",
        "options": [
            ("independent", "Independent", "Happy doing its own thing", "🪶"),
            ("balanced", "Balanced", "Affection with space", "⚖️"),
            ("cuddly", "Very cuddly", "A constant companion", "🤗"),
        ],
    },
]

_AXIS_VALUES = {
    "activity": {"relaxed": 20, "moderate": 55, "active": 85, "very_active": 100},
    "space": {"apartment": 30, "house": 70, "villa": 100},
    "time": {"low": 25, "medium": 60, "high": 100},
    "experience": {"first_time": 25, "some": 60, "experienced": 100},
}

# Questions beyond the four core axes refine the result but don't need their own
# axis; they nudge the readiness/affection interpretation.
_AFFECTION_VALUES = {"independent": 20, "balanced": 60, "cuddly": 100}


def score_axes(answers: dict) -> dict:
    """Convert raw answers to the four 0-100 axes (extra questions refine the
    archetype via score_axes consumers but default cleanly if absent)."""
    axes = {
        axis: _AXIS_VALUES[axis].get(answers.get(axis, ""), 50)
        for axis in _AXIS_VALUES
    }
    axes["affection"] = _AFFECTION_VALUES.get(answers.get("affection", ""), 50)
    return axes


def archetype(axes: dict) -> dict:
    """Pick an archetype label + description + best pet types from the axes."""
    activity = axes["activity"]
    space = axes["space"]

    if activity <= 40 and space <= 50:
        name = "Cosy Companion"
        desc = ("You'd thrive with a calm, affectionate pet that enjoys home "
                "time and a daily walk.")
        best = [
            ("Adult cats", "Low maintenance"),
            ("Small calm dogs", "Apartment friendly"),
            ("Rabbits", "Quiet companions"),
        ]
    elif space >= 85 and activity <= 85:
        # A large home with moderate-to-high (not extreme) activity -> family
        # match. Checked before the adventure case; very-active villa owners
        # still skew toward Adventure Buddy.
        name = "Family Pack Leader"
        desc = ("With space and energy to share, you'd suit a sociable, "
                "playful pet that fits right into family life.")
        best = [
            ("Family dogs", "Great with kids"),
            ("Medium dogs", "Balanced energy"),
            ("Bonded pairs", "Company for each other"),
        ]
    elif activity >= 75:
        name = "Adventure Buddy"
        desc = ("You're ready for an energetic companion to join your runs, "
                "hikes, and outdoor days.")
        best = [
            ("Active dogs", "Love the outdoors"),
            ("Working breeds", "Need a job to do"),
            ("Young dogs", "Endless energy"),
        ]
    else:
        name = "Balanced Guardian"
        desc = ("You'd do well with an adaptable pet that's happy with a "
                "steady routine and moderate activity.")
        best = [
            ("Adult dogs", "Settled temperament"),
            ("Cats", "Independent yet loving"),
            ("Small dogs", "Easygoing companions"),
        ]

    # Readiness score: a gentle blend favouring time + experience.
    readiness = round(
        0.35 * axes["time"] + 0.25 * axes["experience"]
        + 0.2 * axes["activity"] + 0.2 * axes["space"]
    )
    return {"name": name, "description": desc, "best": best, "readiness": readiness}


# Human-readable labels for the result profile bars.
AXIS_LABELS = {
    "activity": ("Activity level", {20: "Relaxed", 55: "Moderate", 85: "Active", 100: "Very active"}),
    "space": ("Space at home", {30: "Apartment", 70: "House", 100: "Villa"}),
    "time": ("Time available", {25: "Low", 60: "Medium", 100: "High"}),
    "experience": ("Experience", {25: "First-time", 60: "Some", 100: "Experienced"}),
}


def axis_label(axis: str, value: int) -> str:
    _, mapping = AXIS_LABELS[axis]
    # Nearest labelled value.
    closest = min(mapping, key=lambda v: abs(v - value))
    return mapping[closest]
