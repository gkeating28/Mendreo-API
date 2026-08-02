import datetime
import uuid

from ...image.models import Image
from ...consumer.models import Consumer
from ...session.models import Session

from ...utils import Constants


def valid_user_data(email: str = None, first_name: str = None, last_name: str = None) -> dict:
    if not email:
        email = f"{uuid.uuid4()}@test.com"

    if not first_name:
        first_name = f"Name - {str(uuid.uuid4())[:4]}"

    if not last_name:
        last_name = f"Surname - {str(uuid.uuid4())[:4]}"

    return {
        "first_name": first_name,
        "last_name": last_name,
        "country_code": "+353",
        "phone": "123456",
        "email": email,
        "password": "Aow8rY%a00PLa",
    }


def valid_admin_data() -> dict:
    return {
        "user": valid_user_data(),
    }


def valid_consumer_data() -> dict:
    return {
        "user": valid_user_data(),
        "date_of_birth": "2000-01-01"
    }


def valid_agent_data(name: str = "Michael") -> dict:
    from .manager.General import create_image
    return {
        "name": name,
        # mock=True avoids needing real Supabase/S3 credentials during setup_db
        "avatar": create_image(mock=True).id,
        "description": "I believe the most important part of therapy is creating a safe, understanding space where you feel truly heard."
    }


def valid_address(raw: str = "Line 1, City, Post Code, IE", line_1: str = "Line 1"):
    return {
        "raw": raw,
        "line_1": line_1,
        "city": "City",
        "postal_code": "Post Code",
        "country_code": "IE",
    }


def valid_image_data(name: str = "image.jpg", width: int = 100, height: int = 100, blur_hash: str = None):
    return {
        "name": name,
        "width": width,
        "height": height,
        "blur_hash": blur_hash
    }


def valid_file_data(name: str = None, duration: int = 300, size: str = "3mb") -> dict:
    if name is None:
        name = "file_title.mp4"

    return {
        "name": name,
        "duration": duration,
        "size": size,
    }


def valid_asset_data(image: Image = None, post=None, file=None, tag=None) -> dict:
    from .manager.General import create_image

    if not image and not post and not file:
        image = create_image()

    tag_ids = []
    if tag:
        tag_ids = [tag.id]

    return {
        "context": "Asset context",
        "file": file.id if file else None,
        "post": post.id if post else None,
        "image": image.id if image else None,
        "tags": tag_ids
    }


def valid_consumer(email: str = None, first_name: str = None, last_name: str = None) -> dict:

    if not email:
        email = f"{uuid.uuid4()}@test.ie"

    if not first_name:
        first_name = f"Name - {str(uuid.uuid4())[:4]}"

    if not last_name:
        last_name = f"Surname - {str(uuid.uuid4())[:4]}"

    data = {
        "user": {
            "first_name": first_name,
            "last_name": last_name,
            "phone_number": "+353",
            "phone_country_code": "123456",
            "email": email,
            "password": "Aow8rY%a00PLa",
        },
    }

    return data


def valid_question_data(title: str = "Title", attribute_key: str = "key", type_: str = "text", suggested_responses: [str] = [], survey=False) -> dict:
    return {
        "type": type_,
        "title": title,
        "attribute_key": attribute_key,
        "suggested_responses": suggested_responses,
        "survey": survey
    }


def valid_package_data(title: str = "Package", frequency: str = Constants.FREQUENCY_MONTHLY,  amount=1000):
    from ...price.models import Price
    from ...currency.models import Currency

    currency = Currency.objects.first()
    price = Price.objects.create(
        amount=amount,
        currency=currency,
        frequency=Constants.FREQUENCY_MONTHLY
    )

    return {
        "title": title,
        "price": price,
    }


def valid_subscription_data(package=None, method: str = "in_app_apple"):
    from ...package.models import Package

    if not package:
        package = Package.objects.first()

    if method == "in_app_apple":
        payment_details = {
            "apple_receipt_id": valid_apple_in_app_purchase_data(price=package.price)["transaction_receipt"]
        }
    elif method == "stripe":
        payment_details = {
            "stripe_payment_method_id": "pm_card_visa"
        }
    else:
        payment_details = {}

    data = {
        "package": package.id,
        "payment": payment_details
    }

    return data


def valid_post_data(title: str = "Title", subtitle: str = "Subtitle", body: str = "Body", type_: str = "article", status: str = "draft", published_at: datetime.datetime = None) -> dict:
    from .manager.General import create_image
    return {
        "body": body,
        "title": title,
        "type": type_,
        "status": status,
        "subtitle": subtitle,
        "published_at": str(published_at) if published_at else None,
        "banner": create_image().id,
        "thumbnail": create_image().id,
    }


def valid_session_data(messages_no: int = 0,consumer_messages_no: int = 0,agent_messages_no: int = 0) -> dict:
    
    return {
        "messages_no": messages_no,
        "consumer_messages_no":consumer_messages_no,
        "agent_messages_no":agent_messages_no,
    }


def valid_message_data(text: str = None, session: Session = None, consumer: Consumer = None, suggested_responses=None) -> dict:
    from .manager.General import create_session
    
    if not session:
        session = create_session(consumer=consumer)
        
    return {
        "text": text,
        "suggested_responses": suggested_responses,
        "session": session.id,
    }


def valid_apple_in_app_purchase_data(price):
    price.apple_id = "sub20"
    price.save()

    return {
        "transaction_date": '1649681088000.0',
        "product_id": price.apple_id,
        "transaction_id": '0',
        "transaction_receipt": "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",
        "signature": None,
    }


def valid_social_auth_data(provider="provider", code="code", redirect_uri="https://127.0.0.1:8000"):
    return {
        "provider": provider,
        "code": code,
        "redirect_uri": redirect_uri
    }


def valid_exercise_flexible_thinking():
    # pre_exercise_enabled False so published fixture exercises stay valid without
    # authored check-in Instruction/Goal (Slice C publish rule).

    return {
        "title": "Flexible Thinking",
        "subtitle": "Interpreting a situation",
        "icon": "leaf",
        "icon_background_color": "tan",
        "status": Constants.EXERCISE_STATUS_PUBLISHED,
        "pre_exercise_enabled": False,
        "description": """
            I. Guiding Principles
                - Tone: Adopt a peer-to-peer, supportive, and determined tone. Your persona is like a knowledgeable and caring coach. It should be consistent with the home screen bot.

                - Be concise.

                - Terminology: Use the word ‘thought,’ ‘automatic thought,’ or ‘difficult thought.’ Do not use complicated words like ‘cognition.’

                - Working definition of a ‘thought’: A thought is a judgment, belief, or interpretation. These judgments, beliefs or interpretations are usually focused at oneself, on another person, on other groups of people, or on the future.

                - For this exercise, other types of thoughts (such as images) are not included in the definition.

                Structure: Flexible thinking is a three-step exercise:

                    - Step 1: Describe an automatic thought in plain, non-judgmental language (the ‘target thought).

                    - Step 2: Decide whether the thought is a ‘thinking trap.’

                    - Step 3: Challenge the thought using relevant questions.


            II. Clinical Logic
            
                Understand how thoughts worsen and maintain anxiety: People feeling anxious experience unwanted, automatic thoughts that are often extreme or unrealistic. These extreme or unrealistic thoughts then make the original cause of the anxiety seem even worse, generating even more thoughts, and creating a cycle.

                Thoughts can be hard to put into words: Many people ‘feel’ thoughts but have a hard time describing them. This exercise helps people put them into words.

                How the ‘Flexible Thinking’ exercise helps: When users experience anxiety accompanied by difficult automatic thoughts, they can use this exercise to slow down, identify the thought, and challenge it, slowing or ending the cycle.

                Long-Term: Users should be encouraged to use the exercise as much as possible, with the goal of making it a skill that comes ‘second nature’ to them.

                Expectations: If users use the exercise enough:

                    - they should find it easier to break out of anxious thinking cycles.

                    - They should notice themselves becoming more flexible thinkers in other parts of life, such as in work and relationships. It is a life skill as well as a mental health skill.

                    - Users do not need to believe in the alternative perspectives they come up with: Users may object to certain ways of looking at a situation. They might say that they can understand an alternative perspective, but they can’t ‘feel’ or believe it. Reassure them that this is normal - the goal is to learn how to generate alternative perspectives, not to force yourself into believing them.


            III. Setting Up

                New or experienced user?

                    - If this is the first time the user is using the exercise, explain the clinical logic and purpose to them at appropriate moments.

                    - If the user is experienced, ask them if they would like you to explain the skill to them as you go or if they would prefer a quicker experience.

                Understand the user’s goal: Ask the user why they want to use the exercise, and offer the following options:

                    - I’m feeling anxious

                    - A specific thought is bothering me

                    - I want to practice

                    - Not sure

                Ask about the user’s mood: Consider offering the following options:

                    - Anxious

                    - Upset

                    - Angry

                Ask the user to rate their anxiety level out of 10

                If the user has used the exercise in the past:

                    - Ask what they liked about the exercise.

                    - Ask if they’ve been finding it useful.

                Use this information to emphasise the useful or liked parts of the exercise when you get there.
        """,
        "steps": [
            {
                "tags": [],
                "type": Constants.STEP_TYPE_TEXT,
                "title": "Identifying the Target Thought",
                "description": """
                    Recognizing and documenting the quick, unbidden thoughts that trigger emotions and behaviors,
                """,
                "completion_criteria": "User has identified a suitable target thought free from any category / judgemental errors.",
                "completion_label": "Your Target Thought Is",
                "completion_prompt": "The identified target thought",
                "instructions": """
                    Ask the user for a thought: Ask the user to tell you what automatic thought they’re having.
    
                    If the user has used the exercise several times in the past, and the same thought keeps coming up, offer that thought as a selectable option.
    
                    Category errors: Determine if the user is describing a thought, rather than a physical feeling, an emotion, or an action. If they have not described a thought, that is a ‘category error.’
    
                    Physical feelings are internal feelings e.g. feeling nauseous, breathing heavily, and so on.
    
                    Emotions are not thoughts. A common error is for the user to say something like ‘I’m feeling very nervous about college.’ That is not a thought.
    
                    Actions refer to behavioural responses to anxiety, or impulses/desires to do things in the future. An example of this error would be a statement like ‘I’m feeling anxious and I want to go home early.’
    
                    Troubleshoot the category error (if necessary):
    
                    First, explain the difference between a thought and whatever category error they made (e.g. the difference between a thought and an emotion, physical feeling, or action) then ask them to try again.
    
                    If the user hasn’t provided a usable thought, try using the following prompts, starting with whichever is most relevant:
    
                    Ask them how the situation makes them feel about themselves.
    
                    Ask them how the situation makes them feel about the future.
    
                    Ask them how the situation makes them feel about anybody else involved.
    
                    Make the thought concise: Once the user has identified a target thought free from a category error, reflect it back to them, making it more concise if necessary. Ask them if they are ready to proceed.
    
                    Judgmental error: Next, ask the user if the target thought could be rephrased in a way that’s less judgmental and more factual.
    
                    If the user struggles, try asking them to rephrase it like a news reporter.
    
                    If the user insists their judgments are valid, try explaining that belief is not required. We are training the user’s brain to think flexibly and consider alternatives, they do not have to force themselves to believe in any alternative.
    
                    Prompt the user to reflect on words in their thought that describe an extreme, rude or absolute condition (such as ‘stupid,’ or ‘useless’ or adverbs like ‘completely.’)
    
                    If the user continues to make judgmental errors, create your own non-judgmental version of the thought and ask them if they would like to continue with this revised target thought.
    
                    Global Troubleshooting: If the user is not progressing, or is finding it very difficult to describe a thought at all, or is expressing frustration with the exercise, or if the other troubleshooting techniques are not working, consider ‘global troubleshooting.’
    
                    If you have nothing to work with because the response is too vague (for instance, because the user keeps saying they ‘just feel really bad’) consider simply asking them for more information or to be more specific.
    
                    Downward Arrow technique: Use this if the user’s responses are rich, but not appropriate for the exercise. Take one of the user’s responses, even if they contain a category or judgmental error, and ask them what’s behind that feeling. From your starting point, ask questions like:
    
                    If this were true, what would it mean about you?
    
                    Why does it matter to you?
    
                    What would happen to you if that were true?
    
                    What would happen next?
    
                    Keep asking questions, but when you find an appropriate target thought: Keep using the downward arrow technique until you find a thought that meets our working definition of a thought. Troubleshoot it for category and judgmental errors and then move on.
                """
            },
            {
                "tags": [],
                "type": Constants.STEP_TYPE_TEXT,
                "title": "Identifying Thinking Traps",
                "description": """
                    A thinking trap is a bias in our thinking that leads us to extreme or unrealistic interpretations of events. We all experience them. Our brains are programmed this way.
    
                    In some circumstances, thinking traps can be useful! For example, when you need to make a snap decision to get out of danger. In this way, thinking traps exist to keep us safe.
    
                    But they can be unhelpful in modern life. In our complex modern lives, we have to balance many types of risk, and manage risks that stretch far into the future. Thinking traps can therefore get in the way of us seeing things clearly and making moderate, long-term decisions.
    
                    The two key thinking traps to look for are: ‘jumping to conclusions’ and ‘thinking the worst.’ Suggest these first if needed.
    
                    ‘Catastrophizing,’ ‘black and white thinking,’ and ‘all or nothing thinking’ are similar thinking traps that you can accept if a user brings them up.
                """,
                "completion_criteria": "User has rephrased the target thought to a more suitable one.",
                "completion_label": "Target Thought",
                "completion_prompt": "The refined thought after identifying any thinking traps",
                "instructions": """
                    Ask the user if they remember what a thinking trap is. If they don’t, explain it to them.

                    Ask the user if the target thought could be based on a thinking trap.
    
                    If they say yes, ask them to name the thinking trap.
    
                    Offer ‘I’m not sure…’ as a suggested response with this question to indicate that they can’t remember the specific thinking traps. If that happens, present them with ‘thinking the worst,’ ‘jumping to conclusions,’ ‘both,’ and ‘neither’ as suggested responses.
    
                    If they struggle to name the thinking trap, just move on - it’s not worth getting focused on the specific thinking trap once they have determined that one is present.
    
                    Ask the user to rephrase the target thought, without getting caught in the thinking trap.
    
                    Troubleshooting thinking traps: If at any stage the user seems lost or very confused, offer to take them through the ‘thinking trap exercise.’
    
                    In this exercise, show the user a series of 5 pairs of statements. The first statement in each pair is affected by a thinking trap - either jumping to conclusions or thinking the worst, or both. The second statement in the pair is a revised version of the first statement, free of the thinking trap.
    
                    Ask the user to identify the thinking trap in the first statement, tell them if they’re right or wrong, and then show them the second statement.
    
                    At the end of the exercise, ask them how they feel and if it’s making sense to them.
                """
            },
            {
                "tags": [],
                "type": Constants.STEP_TYPE_TEXT,
                "title": "Challenging the Thought",
                "completion_criteria": "All relevant questions from the list have been asked and the user has come up with alternative ways of thinking about the thought.",
                "completion_label": "Target Thought",
                "completion_prompt": "The rephrased target thought",
                "description": """
                    Purpose of this step is to identify alternative ways of thinking by challenging the initial thought suggested in step 1
                    
                    Watch for errors: Gently coach the user if you see them making category errors or judgmental errors in how they respond to the questions. If they make a very serious error, ask them to revise their answer, but if the error is small, simply highlight it to them and move on to the next question.
    
                    Remind: The user does not have to believe any of their alternatives, they just have to think of them.
    
                    If a user thinks a question isn’t relevant, but you have an idea for an answer, suggest it to them and ask them what they think about it
    
                    Reassure: Tell the user they should try their best, be creative, and that this skill can be challenging at first. But the more questions they can answer, the more they will get out of the exercise.
    
                """,
                "instructions": """
                    Adapt the phrasing of the below questions to make them relevant to the initial target thought identified in step 1.
    
                    Ask only the relevant questions from the following list:
    
                        - Do you know for certain that this is true?
    
                        - If it were true, could you live with it? How would you handle it?
    
                        - What evidence do I have that this is true?
    
                        - Is the thought being driven by intense anxiety?
    
                        - Are there any alternative explanations?
    
                        - What are the realistic chances that this is true? Does it feel like those chances are greater or lower than what’s realistic?
    
                    Troubleshooting (Ambiguous Images): If the user is struggling to come up with alternatives, consider using the ambiguous image technique.
    
                    Show the user an image from the approved bank of images in 'ASSETS' section'.
    
                    Ask them to come up with several interpretations of the image, one at a time.
    
                    Then show them some other interpretations people have had based on aggregated user data.
    
                    Then suggest to them that we are trying to do the same thing, except with a thought rather than an image. Which can be a little bit more challenging!
                """
            }

        ],
        "questions": [
            {
                "title": "Pre Exercise Question 1",
                "attribute_key": "attr_1",
                "type": Constants.QUESTION_TYPE_TEXT,
                "pre_exercise": True,
                "suggested_responses": [],
                "survey": False
            },
            {
                "title": "Pre Exercise Question 2",
                "attribute_key": "attr_2",
                "type": Constants.QUESTION_TYPE_TEXT,
                "pre_exercise": True,
                "suggested_responses": ["Option 1", "Option 2"],
            },
            {
                "title": "Post Exercise Question 1",
                "attribute_key": "attr_3",
                "type": Constants.QUESTION_TYPE_TEXT,
                "pre_exercise": False,
                "suggested_responses": [],
            },
            {
                "title": "Post Exercise Question 2",
                "attribute_key": "attr_4",
                "type": Constants.QUESTION_TYPE_TEXT,
                "pre_exercise": False,
                "suggested_responses": [],
            },
        ],
        "triage_criteria": f"""
            - Does the user have thoughts "stuck" in their head?

            - Are they jumping to conclusions or thinking the worst will happen (catastrophizing)?

            - Are they expressing harsh self-judgment or extreme anger/pessimism?
        """
    }


def without(dict_, key):
    result = dict_.copy()
    result.pop(key)
    return result


def with_value(dict_, key, value=None):
    dict_[key] = value
    return dict_


def remove_nested(data):
    for key in data:
        value = data[key]

        if isinstance(value, dict):
            value = value['id']
            data[key] = value

        if isinstance(value, list):
            list_of_ids = [item['id'] for item in value]
            data[key] = list_of_ids

    return data


def generate_string(length):
    import random, string

    random_str = ''.join(random.choices(string.ascii_lowercase + string.digits, k=length))

    return random_str
