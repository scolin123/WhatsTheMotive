import google.generativeai as genai
from config import Config


def generate_suggestion_description(room_title: str, suggestion_text: str) -> str:
    """
    Call Gemini Flash to generate a 1-2 sentence description of a suggestion
    given the room topic for context.

    Raises:
        RuntimeError: If the API key is missing or the API call fails.
    """
    if not Config.GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY is not configured.")

    genai.configure(api_key=Config.GEMINI_API_KEY)
    model = genai.GenerativeModel("gemini-3-flash-preview")

    prompt = (
        f'The topic is: "{room_title}".\n'
        f'The suggestion is: "{suggestion_text}".\n\n'
        f"Write a 1-2 sentence description of this suggestion to help people understand what it is. "
        f"Be concise, factual, and neutral. Do not use bullet points."
    )

    response = model.generate_content(prompt)
    return response.text.strip()
