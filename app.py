import json
import time

from google import genai
from google.genai import types # pyright: ignore[reportMissingImports]
import streamlit as st # pyright: ignore[reportMissingImports]

try:
    from twilio.rest import Client as TwilioClient # pyright: ignore[reportMissingImports]
except ImportError:
    TwilioClient = None

from prompts import SYSTEM_PROMPT, WELCOME_MESSAGE_TEMPLATE, SUMMARY_REQUEST_PROMPT


# ============================================================
# CONFIGURATION
# ============================================================

# IMPORTANT:
# "gemini-3.8-flash" is not a valid model name.
# Use a model that is actually available to your Gemini API key.
MODEL_NAME = "gemini-3.8-flash"


st.set_page_config(
    page_title="RxCare - Prescription & Diet Guide",
    page_icon="💊"
)


# ============================================================
# SECRETS
# ============================================================

required_secrets = [
    "GEMINI_API_KEY",
    "TWILIO_ACCOUNT_SID",
    "TWILIO_AUTH_TOKEN",
    "TWILIO_WHATSAPP_FROM",
    "TWILIO_CONTENT_SID",
]

for secret in required_secrets:
    if secret not in st.secrets:
        st.error(
            f"Missing `{secret}` in Streamlit Secrets. "
            "Please check your app settings."
        )
        st.stop()


GEMINI_API_KEY = st.secrets["GEMINI_API_KEY"]
TWILIO_ACCOUNT_SID = st.secrets["TWILIO_ACCOUNT_SID"]
TWILIO_AUTH_TOKEN = st.secrets["TWILIO_AUTH_TOKEN"]
TWILIO_WHATSAPP_FROM = st.secrets["TWILIO_WHATSAPP_FROM"]
TWILIO_CONTENT_SID = st.secrets["TWILIO_CONTENT_SID"]


# ============================================================
# CLIENTS
# ============================================================

@st.cache_resource
def get_gemini_client():
    return genai.Client(api_key=GEMINI_API_KEY)


@st.cache_resource
def get_twilio_client():
    if TwilioClient is None:
        return None

    return TwilioClient(
        TWILIO_ACCOUNT_SID,
        TWILIO_AUTH_TOKEN
    )


gemini_client = get_gemini_client()
twilio_client = get_twilio_client()


# ============================================================
# UI HELPERS
# ============================================================

def render_message(message):
    with st.chat_message(message["role"]):

        if message["kind"] == "text":
            st.write(message["content"])

        elif message["kind"] == "image":
            st.image(message["content"])


def add_message(role, kind, content):
    st.session_state.messages.append({
        "role": role,
        "kind": kind,
        "content": content
    })

    render_message(st.session_state.messages[-1])


# ============================================================
# GEMINI
# ============================================================

def ask_gemini(parts, max_retries=3):
    """
    Send request to Gemini with retry handling for temporary
    503 / UNAVAILABLE errors.
    """

    for attempt in range(max_retries):

        try:
            response = st.session_state.chat.send_message(parts)

            if response is None:
                return "The AI returned an empty response. Please try again."

            if not response.text:
                return "I couldn't generate a response. Please try again."

            return response.text

        except Exception as error:

            error_text = str(error)

            # Temporary Gemini overload
            if (
                "503" in error_text
                or "UNAVAILABLE" in error_text
                or "Service Unavailable" in error_text
            ):

                if attempt < max_retries - 1:

                    # 2 sec → 4 sec → 8 sec
                    wait_time = 2 ** (attempt + 1)

                    time.sleep(wait_time)

                    continue

                return (
                    "The AI service is temporarily busy. "
                    "Please wait a few seconds and try again."
                )

            # Authentication problems
            if (
                "401" in error_text
                or "API key" in error_text
                or "authentication" in error_text.lower()
            ):
                return (
                    "There is a problem with the Gemini API key. "
                    "Please check your Streamlit Secrets."
                )

            # Invalid model
            if (
                "404" in error_text
                or "not found" in error_text.lower()
                or "model" in error_text.lower()
                and "not found" in error_text.lower()
            ):
                return (
                    f"The selected Gemini model '{MODEL_NAME}' "
                    "is not available for this API key."
                )

            # Other errors
            return (
                "Sorry, I couldn't process your request right now. "
                "Please try again."
            )

    return "Please try again later."


# ============================================================
# WHATSAPP
# ============================================================

def clean_whatsapp_text(text):

    if not text:
        return "No prescription summary available."

    text = " ".join(text.split())

    return text[:1500] + "..." if len(text) > 1500 else text


def send_whatsapp(to_number, user_name, summary):

    try:

        if twilio_client is None:
            return False, "Twilio package is not installed."

        content_variables = json.dumps(
            {
                "1": user_name,
                "2": clean_whatsapp_text(summary)
            },
            ensure_ascii=False
        )

        message = twilio_client.messages.create(
            from_=TWILIO_WHATSAPP_FROM,
            to=f"whatsapp:{to_number}",
            content_sid=TWILIO_CONTENT_SID,
            content_variables=content_variables,
        )

        return True, message.sid

    except Exception as error:

        return False, str(error)


# ============================================================
# ONBOARDING
# ============================================================

if "onboarded" not in st.session_state:

    st.title("💊 RxCare")

    st.caption(
        "Prescription Scanner, Tablet Guide & Nutritional Advisor"
    )

    with st.form("onboarding_form"):

        name = st.text_input("Your name")

        whatsapp_number = st.text_input(
            "WhatsApp number (with country code)",
            placeholder="+91XXXXXXXXXX",
            help="Your medication and dietary instructions can be sent here.",
        )

        submitted = st.form_submit_button("Get Started 🚀")

    if submitted:

        if not name.strip() or not whatsapp_number.strip():

            st.warning(
                "Please provide your name and WhatsApp number."
            )

        else:

            st.session_state.name = name.strip()

            st.session_state.whatsapp_number = (
                whatsapp_number.strip()
            )

            try:

                st.session_state.chat = gemini_client.chats.create(
                    model=MODEL_NAME,
                    config=types.GenerateContentConfig(
                        system_instruction=SYSTEM_PROMPT
                    ),
                )

                st.session_state.messages = []

                st.session_state.onboarded = True

                st.rerun()

            except Exception as error:

                st.error(
                    "Unable to start the AI assistant. "
                    "Please check your Gemini model/API configuration."
                )

    st.stop()


# ============================================================
# CHAT HEADER
# ============================================================

header_col, button_col = st.columns(
    [5, 2],
    vertical_alignment="center"
)


with header_col:

    st.title("💊 RxCare Advisor")


with button_col:

    send_disabled = len(st.session_state.messages) <= 1

    if st.button(
        "📤 Send to WhatsApp",
        disabled=send_disabled,
        use_container_width=True
    ):

        with st.spinner("Preparing your summary..."):

            summary = ask_gemini(
                [SUMMARY_REQUEST_PROMPT]
            )

        success, info = send_whatsapp(
            st.session_state.whatsapp_number,
            st.session_state.name,
            summary
        )

        if success:

            st.success(
                "Sent! Check your WhatsApp 📲"
            )

        else:

            st.error(
                f"Couldn't send that: {info}"
            )


st.caption(
    f"Patient: {st.session_state.name} | "
    f"Updates sent to: {st.session_state.whatsapp_number}"
)


# ============================================================
# CHAT HISTORY
# ============================================================

if not st.session_state.messages:

    add_message(
        "assistant",
        "text",
        WELCOME_MESSAGE_TEMPLATE.format(
            name=st.session_state.name
        )
    )

else:

    for message in st.session_state.messages:
        render_message(message)


# ============================================================
# USER INPUT
# ============================================================

user_input = st.chat_input(
    "Upload doctor prescription photo or ask about your medications...",
    accept_file=True,
    file_type=["jpg", "jpeg", "png"],
)


if user_input:

    photo = (
        user_input.files[0]
        if user_input.files
        else None
    )

    text = user_input.text

    parts = []


    # --------------------------------------------------------
    # IMAGE
    # --------------------------------------------------------

    if photo is not None:

        photo_bytes = photo.getvalue()

        add_message(
            "user",
            "image",
            photo_bytes
        )

        parts.append(
            types.Part.from_bytes(
                data=photo_bytes,
                mime_type=photo.type
            )
        )


    # --------------------------------------------------------
    # TEXT
    # --------------------------------------------------------

    if text:

        add_message(
            "user",
            "text",
            text
        )

        parts.append(text)


    # --------------------------------------------------------
    # IMAGE WITHOUT TEXT
    # --------------------------------------------------------

    elif photo is not None:

        parts.append(
            """
            Please analyze this doctor's prescription or
            medicine label carefully.

            Provide:

            1. List each medicine visible in the image.
            2. Explain the apparent primary use of each medicine.
            3. Explain how the medicine is generally taken,
               ONLY if the instructions are clearly visible.
            4. Explain suitable foods/dietary considerations.
            5. Mention important foods or drinks that may
               interact with the medicines.
            6. Clearly state when information cannot be
               confidently read from the image.
            7. Do not invent missing medicine names,
               dosages, or instructions.

            Important:
            This is informational guidance and should not
            replace advice from a doctor or pharmacist.
            """
        )


    # --------------------------------------------------------
    # GEMINI RESPONSE
    # --------------------------------------------------------

    if parts:

        with st.spinner(
            "Analyzing prescription and formulating dietary advice..."
        ):

            answer = ask_gemini(parts)

        add_message(
            "assistant",
            "text",
            answer
        )