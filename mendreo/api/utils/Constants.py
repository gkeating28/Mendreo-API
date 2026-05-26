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

QUESTION_TYPES = [
    QUESTION_TYPE_TEXT,
    QUESTION_TYPE_DATE,
    QUESTION_TYPE_NUMBER,
    QUESTION_TYPE_BOOLEAN,
    QUESTION_TYPE_SINGLE_CHOICE,
    QUESTION_TYPE_MULTIPLE_CHOICE,
]

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
          
        - suggested_responses must be fully self contained answers the user can reply to you with.
          
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
}

