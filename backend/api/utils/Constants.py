import os

APP_NAME = "Mendreo"

USER = "user"
CONSUMER = "consumer"
ADMIN = "admin"

USER_TYPE_CONSUMER = CONSUMER
USER_TYPE_ADMIN = ADMIN

USER_TYPES = [USER_TYPE_CONSUMER, USER_TYPE_ADMIN]

USER_STATUS_ACTIVE = "active"
USER_STATUS_DELETED = "deleted"
USER_STATUS_SUSPENDED = "suspended"
USER_STATUS_DEFAULT = USER_STATUS_ACTIVE

USER_STATUSES = [USER_STATUS_ACTIVE, USER_STATUS_SUSPENDED]

USER_AUTH_TOKENS = "tokens"

X_AUTH_REFRESH_TOKEN = "X-Auth-Refresh-Token"
X_AUTH_ACCESS_TOKEN = "X-Auth-Access-Token"

IMAGE_TYPE_FAVICON = "favicon"
IMAGE_TYPE_PHOTO = "photo"
IMAGE_TYPE_ILLUSTRATION = "illustration"

IMAGE_TYPE_DEFAULT = IMAGE_TYPE_PHOTO

IMAGE_TYPE_LIST = [IMAGE_TYPE_FAVICON, IMAGE_TYPE_PHOTO, IMAGE_TYPE_ILLUSTRATION]

IMAGE_UPLOAD_ACCEPTABLE_EXTENSIONS = ["png", "jpg", "jpeg", "gif", "svg"]

IMAGE_SIZE_TYPE_BANNER = "banner"
IMAGE_SIZE_TYPE_THUMBNAIL = "thumbnail"
IMAGE_SIZE_TYPE_ORIGINAL = "original"

IMAGE_SIZE_BANNER = "800x450"
IMAGE_SIZE_THUMBNAIL = "400x225"

CONSUMER_MINIMUM_AGE = 18

QUESTION_TYPE_TEXT = "text"
QUESTION_TYPE_DATE = "date"
QUESTION_TYPE_NUMBER = "number"
QUESTION_TYPE_BOOLEAN = "boolean"
QUESTION_TYPE_SINGLE_CHOICE = "single_choice"
QUESTION_TYPE_MULTIPLE_CHOICE = "multiple_choice"
QUESTION_TYPE_SLIDER = "slider"

QUESTION_TYPES = [
    QUESTION_TYPE_TEXT,
    QUESTION_TYPE_DATE,
    QUESTION_TYPE_NUMBER,
    QUESTION_TYPE_BOOLEAN,
    QUESTION_TYPE_SINGLE_CHOICE,
    QUESTION_TYPE_MULTIPLE_CHOICE,
    QUESTION_TYPE_SLIDER,
]

SLIDER_MIN = 0
SLIDER_MAX = 10
SLIDER_VALUE_LABEL_COUNT = 11
SLIDER_DEFAULT_ANCHOR_LEFT = "Struggling"
SLIDER_DEFAULT_ANCHOR_RIGHT = "Thriving"

ATTRIBUTE_TYPE_BOOLEAN_VALID_OPTIONS = ["true", "false", "yes", "no"]

PACKAGE_TYPE_LITE = "lite"
PACKAGE_TYPE_PRO = "pro"

PACKAGE_TYPE_DEFAULT = PACKAGE_TYPE_LITE

PACKAGE_TYPES = [
    PACKAGE_TYPE_LITE,
    PACKAGE_TYPE_PRO
]

FREQUENCY_MONTHLY = "monthly"
FREQUENCY_YEARLY = "yearly"

FREQUENCY_DEFAULT = FREQUENCY_MONTHLY

FREQUENCIES = [
    FREQUENCY_MONTHLY,
    FREQUENCY_YEARLY
]

POST_STATUS_DRAFT = "draft"
POST_STATUS_ARCHIVED = "archived"
POST_STATUS_PROMPTED = "prompted"
POST_STATUS_REJECTED = "rejected"
POST_STATUS_PUBLISHED = "published"
POST_STATUS_GENERATING = "generating"

POST_STATUSES = [
    POST_STATUS_DRAFT,
    POST_STATUS_ARCHIVED,
    POST_STATUS_PROMPTED,
    POST_STATUS_REJECTED,
    POST_STATUS_PUBLISHED,
    POST_STATUS_GENERATING,
]

POST_TYPE_VIDEO = "video"
POST_TYPE_PODCAST = "podcast"
POST_TYPE_ARTICLE = "article"

POST_TYPES = [
    POST_TYPE_VIDEO,
    POST_TYPE_PODCAST,
    POST_TYPE_ARTICLE,
]

EVENT_TYPE_VIEW = "view"
EVENT_TYPE_IMPRESSION = "impression"

EVENT_TYPES = [
    EVENT_TYPE_VIEW,
    EVENT_TYPE_IMPRESSION,
]

QUESTION_ID_DOB = "__dob__"

RISK_LEVEL_LOW = "low"
RISK_LEVEL_MODERATE = "moderate"
RISK_LEVEL_HIGH = "high"
RISK_LEVEL_CRITICAL = "critical"

RISK_LEVEL_CHOICES = [
    RISK_LEVEL_LOW,
    RISK_LEVEL_MODERATE,
    RISK_LEVEL_HIGH,
    RISK_LEVEL_CRITICAL,
]

STEP_TYPE_TEXT = "text"
STEP_TYPE_IMAGE = "image"
STEP_TYPE_AUDIO = "audio"
STEP_TYPE_VIDEO = "video"

STEP_TYPES = [
    STEP_TYPE_TEXT,
    STEP_TYPE_IMAGE,
    STEP_TYPE_AUDIO,
    STEP_TYPE_VIDEO
]

EXERCISE_STATUS_DRAFT = "draft"
EXERCISE_STATUS_ARCHIVED = "archived"
EXERCISE_STATUS_PUBLISHED = "published"

EXERCISE_STATUSES = [
    EXERCISE_STATUS_DRAFT,
    EXERCISE_STATUS_ARCHIVED,
    EXERCISE_STATUS_PUBLISHED
]

# spacing is to preserve final prompt
PROMPT_THERAPEUTIC_INSTRUCTIONS = """
        Core Persona & Guiding Principles
            Tone: Adopt a peer-to-peer, supportive, and determined tone. Your persona is like a knowledgeable and caring friend, not a clinical therapist.
        
            Conciseness: Be concise. Use paraphrasing or reflection to encourage the user to elaborate rather than writing long paragraphs.
        
            Language: Use plain, everyday language. Avoid therapy-speak or psychological jargon (e.g., say "stuck thoughts" instead of "rumination").
        
            Empathy: Use empathy sparingly and meaningfully.
        
            DO: Acknowledge the user's effort and the burden they are carrying (e.g., "It's impressive you're managing all this while feeling this way.").
        
            DON'T: Offer a generic statement of empathy on every turn.
        
            Consistency: Maintain a consistent, "all-weather" tone. Do not radically shift your tone to mirror the user's emotional extremes, as it can seem disingenuous.
        
            Curiosity: Show genuine, gentle curiosity. If a user mentions a personal interest outside of their anxiety (e.g., music), ask a simple follow-up question to build rapport.
        
            Hope: Convey a sense of hope and that solutions exist for the problems the user is facing.
        
            Framework: Strictly adhere to a Cognitive Behavioural Therapy (CBT) framework. Do not reference concepts from other theories (e.g., psychodynamic, attachment theory).
        
        Primary Objective & Core Logic
            Main Goal: Your primary objective is to understand the user's anxious experience, identify the underlying "vicious cycle" of avoidance (either cognitive or behavioural), and guide them to the most appropriate skill-building exercise or prompt.
        
            The Vicious Cycle: You must understand that anxiety is often maintained by a feedback loop:
        
                - User perceives a threat.
        
                - User engages in an avoidance strategy (e.g., catastrophic thinking, cancelling plans).
        
                - User feels short-term relief.
        
                - This relief reinforces the idea that the threat is real and the avoidance was necessary, strengthening the cycle.
        
            Challenge, Don't Endorse: Your most critical function is to gently challenge the user's negative conjectures, not endorse them. Uncritical agreement reinforces the cognitive avoidance that fuels the anxiety cycle.
        
            Recognize the Burden: Acknowledge the difficulty of the user's situation without validating their negative conclusions.
"""

PROMPT_PROGRAMMING_INSTRUCTIONS = """
        You are a virtual AI Therapist trained on the Unified Protocol for Transdiagnostic Treatment of Emotional Disorders (2nd Edition), supporting your client through therapeutic conversations.
        Today is {today_date}
        
        Your task is to respond to your client’s messages using the data provided in the <DATA> section.
        
        - Make use of <CLIENT_SUMMARY> section for detailed notes on {user_name}.
          You do not reference anywhere else for client notes or make stuff up about previous interactions with {user_name}.
          If you have no notes then you have never spoken to {user_name} you must be open and honest about this
        
        - Use the <FEEDBACK> section to adjust tone, clinical direction, and communication style.
        
        - Access <ASSETS> to suggest relevant images or audio.
        
        - Your client is {user_name}. You deal with no other clients.
        
        - Use your knowledge of the "Unified Protocol for Transdiagnostic Treatment of Emotional Disorders (2nd Edition)"
          to guide your responses. This includes applying evidence-based strategies for managing guilt, emotional regulation,
          and cognitive restructuring as appropriate.
        
        - Do not give diagnoses or emergency instructions.
        
        - Maintain a calm, warm, and professional tone.
        
        - If no clear therapeutic intervention applies, simply listen and invite reflection.
        
        - If the user asks who developed you must respond with "Mendreo, an evidence-based clinical psychology company committed
          to empirically supported treatments, and the highest standards of professionalism."
        
        - Do not role-play with the user / answer questions outside therapeutic sessions, if a user asks an irrelevant
          question respond politely and professionally that you can only help them with therapeutic matters.
        
        - Maintain a calm, warm, and professional tone.
        
        - Keep your responses short and to the point, ideally these should be no more than 2 sentences
        
        - When explaining a concept / exercise keep your initial response short and concise and offer a 'suggested_response' of
          where you can add further information.
        
        - Do not repeat the users queries to ask for clarification

        - Do not ask compound questions. Only ask one simple, single question at a time.

        - Always refer to {user_name} by their name. Never refer to them as "the user" or "the client".
        
        - Avoid 'learned helplessness'. Do not tell the user it takes courage to do something or that sounds hard / terrible etc...
        
        - Do not thank the user for sharing information / their responses, be as concise and laser focused as possible. You must
          avoid this at all times when possible
          
        - Do not start sentences with phrases like 'Thank you for ....', 'It sounds like ....' Be confident, concise and assertive
        
        - Instead of asking the user if something makes sense in your text, instead use the 'suggested_responses' to offer the
          user an option to say they don't understand.
          
        - suggested_responses are tap-to-send replies in the user's voice. They must be fully self-contained answers
          the user can send back, never a question and never a shortened restatement of what you just asked.
          If your text asks when they can work, chips are times ("Tonight", "This weekend"), not "When can you work?".
          If you cannot offer real answers, omit suggested_responses.
          
        - Events are recorded in special messages in the format:
          [EVENT ....]
          The event can contain an asset you showed to the user, the text you sent back and the 'context' of the assset. Use the context
          of the asset in order to engage with the user about the specifics of the asset.
"""

PROMPT_STEP = """<STEP>
                <TITLE>
                    {step_title}
                </TITLE>
                <DESCRIPTION>
                    {step_description}
                </DESCRIPTION>
                <INSTRUCTIONS>
                    {step_instructions}
                </INSTRUCTIONS>
                <COMPLETION_CRITERIA>
                    {step_completion_criteria}
                </COMPLETION_CRITERIA>
                <COMPLETION_PROMPT>
                    {step_completion_prompt}
                </COMPLETION_PROMPT>
            </STEP>"""

PROMPT_GENERAL_GOALS = f"""
        1. Follow-Ups First: Always prioritize follow-ups. If you have flagged a user for reflection or if there's previously made a plan, address this first.

        2. Daily Check-in: For first daily interaction, ask 1-2 short questions to gauge their anxiety level and sentiment.

        3. Triage the Experience
"""

MESSAGE_TEXT_SKIP_STEP = "qa skip step"

MESSAGE_TEXT_ASSET_IMAGE = "qa asset image"
MESSAGE_TEXT_ASSET_POST = "qa asset post"
MESSAGE_TEXT_ASSET_FILE = "qa asset file"
MESSAGE_TEXT_EXERCISE = "qa exercise"

EXERCISE_OFFER_YES = "Yes"
EXERCISE_OFFER_NO = "No"
EXERCISE_OFFER_SUGGESTED_RESPONSES = [EXERCISE_OFFER_YES, EXERCISE_OFFER_NO]


PERMISSION_VIEW = "view"
PERMISSION_CREATE = "create"
PERMISSION_EDIT = "edit"
PERMISSION_DELETE = "delete"

ALL_PERMISSIONS = [
    PERMISSION_VIEW,
    PERMISSION_CREATE,
    PERMISSION_EDIT,
    PERMISSION_DELETE
]


ANON_FIRST_NAME = "Anon"
ANON_LAST_NAME = "User"
ANON_EMAIL = "anonymous@example.com"
ANON_DATE_OF_BIRTH = None


USERS_PERMISSIONS = [PERMISSION_VIEW, PERMISSION_CREATE, PERMISSION_EDIT, PERMISSION_DELETE]
SESSIONS_PERMISSIONS = [PERMISSION_VIEW, PERMISSION_CREATE, PERMISSION_EDIT, PERMISSION_DELETE]
SIGNUPS_PERMISSIONS = [PERMISSION_VIEW]
FEEDBACK_PERMISSIONS = [PERMISSION_VIEW, PERMISSION_CREATE]
EXERCISES_PERMISSIONS = [PERMISSION_VIEW, PERMISSION_CREATE, PERMISSION_EDIT, PERMISSION_DELETE]
ASSETS_PERMISSIONS = [PERMISSION_VIEW, PERMISSION_CREATE, PERMISSION_EDIT, PERMISSION_DELETE]
QUESTIONS_PERMISSIONS = [PERMISSION_VIEW, PERMISSION_CREATE, PERMISSION_EDIT, PERMISSION_DELETE]
ROLES_PERMISSIONS = [PERMISSION_VIEW, PERMISSION_CREATE, PERMISSION_EDIT, PERMISSION_DELETE]
PII_PERMISSIONS = [PERMISSION_VIEW]
KNOWLEDGE_PERMISSIONS = [PERMISSION_VIEW, PERMISSION_CREATE, PERMISSION_EDIT, PERMISSION_DELETE]

# Knowledge field value types (open question #7 deferred — start with text-compatible set)
KNOWLEDGE_VALUE_TYPE_TEXT = "text"
KNOWLEDGE_VALUE_TYPE_NUMBER = "number"
KNOWLEDGE_VALUE_TYPE_BOOLEAN = "boolean"
KNOWLEDGE_VALUE_TYPE_SINGLE_CHOICE = "single_choice"
KNOWLEDGE_VALUE_TYPE_MULTIPLE_CHOICE = "multiple_choice"

KNOWLEDGE_VALUE_TYPES = [
    KNOWLEDGE_VALUE_TYPE_TEXT,
    KNOWLEDGE_VALUE_TYPE_NUMBER,
    KNOWLEDGE_VALUE_TYPE_BOOLEAN,
    KNOWLEDGE_VALUE_TYPE_SINGLE_CHOICE,
    KNOWLEDGE_VALUE_TYPE_MULTIPLE_CHOICE,
]

KNOWLEDGE_ENTRY_SOURCE_ONBOARDING = "onboarding"
KNOWLEDGE_ENTRY_SOURCE_QUESTION = "question"
KNOWLEDGE_ENTRY_SOURCE_AI = "ai"
KNOWLEDGE_ENTRY_SOURCE_ADMIN = "admin"

KNOWLEDGE_ENTRY_SOURCES = [
    KNOWLEDGE_ENTRY_SOURCE_ONBOARDING,
    KNOWLEDGE_ENTRY_SOURCE_QUESTION,
    KNOWLEDGE_ENTRY_SOURCE_AI,
    KNOWLEDGE_ENTRY_SOURCE_ADMIN,
]

KNOWLEDGE_TRIGGER_FIRST_SESSION = "first_session"
KNOWLEDGE_TRIGGER_AFTER_N_SESSIONS = "after_n_sessions"
KNOWLEDGE_TRIGGER_ON_EXERCISE_COMPLETION = "on_exercise_completion"
KNOWLEDGE_TRIGGER_MANUAL_ONLY = "manual_only"

KNOWLEDGE_TRIGGERS = [
    KNOWLEDGE_TRIGGER_FIRST_SESSION,
    KNOWLEDGE_TRIGGER_AFTER_N_SESSIONS,
    KNOWLEDGE_TRIGGER_ON_EXERCISE_COMPLETION,
    KNOWLEDGE_TRIGGER_MANUAL_ONLY,
]

KNOWLEDGE_FLOW_INITIAL = "initial"
KNOWLEDGE_FLOW_RETURN = "return"
KNOWLEDGE_FLOW_REFRESH = "refresh"

KNOWLEDGE_FLOWS = [
    KNOWLEDGE_FLOW_INITIAL,
    KNOWLEDGE_FLOW_RETURN,
    KNOWLEDGE_FLOW_REFRESH,
]

# Response controls for onboarding/knowledge questions (spec §3.5)
KNOWLEDGE_RESPONSE_TYPE_TEXT = "text"
KNOWLEDGE_RESPONSE_TYPE_SINGLE_CHOICE = "single_choice"
KNOWLEDGE_RESPONSE_TYPE_MULTIPLE_CHOICE = "multiple_choice"
KNOWLEDGE_RESPONSE_TYPE_SLIDER = "slider"

KNOWLEDGE_RESPONSE_TYPES = [
    KNOWLEDGE_RESPONSE_TYPE_TEXT,
    KNOWLEDGE_RESPONSE_TYPE_SINGLE_CHOICE,
    KNOWLEDGE_RESPONSE_TYPE_MULTIPLE_CHOICE,
    KNOWLEDGE_RESPONSE_TYPE_SLIDER,
]

KNOWLEDGE_RESTRICTED_PLACEHOLDER = "Restricted"

SETTING_KEY_REFRESH_ONBOARDING_CADENCE_DAYS = "refresh_onboarding_cadence_days"
DEFAULT_REFRESH_ONBOARDING_CADENCE_DAYS = 30

SETTING_KEY_OBSERVATIONS_ENABLED = "observations_enabled"
SETTING_KEY_OBSERVATIONS_INSTRUCTION = "observations_instruction"
SETTING_KEY_OBSERVATIONS_TONE_GUIDE = "observations_tone_guide"
SETTING_KEY_OBSERVATIONS_MAX_LENGTH = "observations_max_length"
DEFAULT_OBSERVATIONS_ENABLED = True
DEFAULT_OBSERVATIONS_MAX_LENGTH = 40
DEFAULT_OBSERVATIONS_INSTRUCTION = (
    "Write one short supportive observation in the second person about a pattern "
    "you notice in this user's knowledge and recent conversations."
)
DEFAULT_OBSERVATIONS_TONE_GUIDE = (
    "Warm, specific, and non-judgmental. Avoid clinical jargon and scorekeeping."
)

PROGRESS_MOOD_FIELD_KEY = "mood"
PROGRESS_STRESS_FIELD_KEY = "stress_points"
PROGRESS_MAX_RANGE_DAYS = 366
PROGRESS_STREAK_COPY = "Consistency matters more than perfection"
# Cap so one completion cannot overflow the chart (y-axis 100 = 60 minutes).
PROGRESS_ACTIVITY_MAX_MINUTES = 90
# Gaps longer than this between the user's own messages are paused, not practice.
# Agent replies while the tab is left open must not fill the bar.
PROGRESS_ACTIVITY_IDLE_GAP_MINUTES = 10

# Dedicated mood check-ins (MoodEntry): 1–5 scale with fixed labels.
MOOD_SCORE_MIN = 1
MOOD_SCORE_MAX = 5
MOOD_SCORE_LOW = 1
MOOD_SCORE_FLAT = 2
MOOD_SCORE_OKAY = 3
MOOD_SCORE_GOOD = 4
MOOD_SCORE_GREAT = 5
MOOD_SCORE_LABELS = {
    MOOD_SCORE_LOW: "Low",
    MOOD_SCORE_FLAT: "Flat",
    MOOD_SCORE_OKAY: "Okay",
    MOOD_SCORE_GOOD: "Good",
    MOOD_SCORE_GREAT: "Great",
}
MOOD_SCORES = list(MOOD_SCORE_LABELS.keys())

AI_PROVIDER_GOOGLE = "google"
AI_PROVIDER_OPENAI = "openai"
AI_PROVIDER_ANTHROPIC = "anthropic"

AI_PROVIDERS = [
    AI_PROVIDER_GOOGLE,
    AI_PROVIDER_OPENAI,
    AI_PROVIDER_ANTHROPIC,
]

AI_PROVIDER_DEFAULT_MODELS = {
    # Prefer a current Flash-class model; gemini-2.5-flash is blocked for many new API keys.
    AI_PROVIDER_GOOGLE: "gemini-3.1-flash-lite",
    AI_PROVIDER_OPENAI: "gpt-4.1-mini",
    AI_PROVIDER_ANTHROPIC: "claude-sonnet-4-20250514",
}

AI_PROVIDER_SUGGESTED_MODELS = {
    AI_PROVIDER_GOOGLE: [
        "gemini-3.1-flash-lite",
        "gemini-3-flash-preview",
        "gemini-3.5-flash",
        "gemini-2.5-flash",
        "gemini-2.5-pro",
        "gemini-3-pro-preview",
    ],
    AI_PROVIDER_OPENAI: [
        "gpt-4.1-mini",
        "gpt-4.1",
        "gpt-4o",
        "gpt-4o-mini",
    ],
    AI_PROVIDER_ANTHROPIC: [
        "claude-sonnet-4-20250514",
        "claude-opus-4-20250514",
        "claude-haiku-4-5-20251001",
    ],
}

AI_PROVIDER_MODEL_PREFIXES = {
    AI_PROVIDER_GOOGLE: ("gemini-", "imagen-"),
    AI_PROVIDER_OPENAI: ("gpt-", "o1", "o3", "o4"),
    AI_PROVIDER_ANTHROPIC: ("claude-",),
}

AI_PROVIDER_IMAGE_MODEL = "imagen-4.0-generate-001"

AI_PROVIDER_AUDIT_CREATED = "created"
AI_PROVIDER_AUDIT_UPDATED = "updated"
AI_PROVIDER_AUDIT_KEY_ROTATED = "key_rotated"
AI_PROVIDER_AUDIT_SET_DEFAULT = "set_default"
AI_PROVIDER_AUDIT_ENABLED = "enabled"
AI_PROVIDER_AUDIT_DISABLED = "disabled"
AI_PROVIDER_AUDIT_DELETED = "deleted"
AI_PROVIDER_AUDIT_FAILOVER = "failover"
AI_PROVIDER_AUDIT_SEEDED = "seeded"

AI_PROVIDER_AUDIT_ACTIONS = [
    AI_PROVIDER_AUDIT_CREATED,
    AI_PROVIDER_AUDIT_UPDATED,
    AI_PROVIDER_AUDIT_KEY_ROTATED,
    AI_PROVIDER_AUDIT_SET_DEFAULT,
    AI_PROVIDER_AUDIT_ENABLED,
    AI_PROVIDER_AUDIT_DISABLED,
    AI_PROVIDER_AUDIT_DELETED,
    AI_PROVIDER_AUDIT_FAILOVER,
    AI_PROVIDER_AUDIT_SEEDED,
]


SUPER_ADMIN_PERMISSIONS = {
    "users": ["view", "create", "edit", "delete"],
    "sessions": ["view", "create", "edit", "delete"],
    "signups": ["view"],
    "feedback": ["view", "create"],
    "exercises": ["view", "create", "edit", "delete"],
    "assets": ["view", "create", "edit", "delete"],
    "questions": ["view", "create", "edit", "delete"],
    "roles": ["view", "create", "edit", "delete"],
    "pii": ["view"],
    "knowledge": ["view", "create", "edit", "delete"],
}

ADMIN_PERMISSIONS = {
    "users": ["view"],
    "sessions": ["view"],
    "signups": [],
    "feedback": ["view", "create"],
    "exercises": ["view", "create", "edit"],
    "assets": ["view", "create"],
    "questions": ["view", "create", "edit"],
    "roles": [],
    "pii": [],
    "knowledge": ["view", "create", "edit"],
}

VIEWER_PERMISSIONS = {
    "users": ["view"],
    "sessions": ["view"],
    "signups": ["view"],
    "feedback": ["view"],
    "exercises": ["view"],
    "assets": ["view"],
    "questions": ["view"],
    "roles": [],
    "pii": [],
    "knowledge": ["view"],
}

