"""LLM client - supports Groq and Gemini."""
import os
import json
import logging

logger = logging.getLogger(__name__)

_client = None
_provider = None


def _init_client():
    global _client, _provider

    groq_key = os.getenv("GROQ_API_KEY")
    gemini_key = os.getenv("GEMINI_API_KEY")

    if groq_key and groq_key != "your_groq_api_key_here":
        from groq import Groq
        _client = Groq(api_key=groq_key)
        _provider = "groq"
        logger.info("Using Groq LLM provider")
    elif gemini_key and gemini_key != "your_gemini_api_key_here":
        from google import genai
        _client = genai.Client(api_key=gemini_key)
        _provider = "gemini"
        logger.info("Using Gemini LLM provider")
    else:
        raise RuntimeError("No LLM API key found. Set GROQ_API_KEY or GEMINI_API_KEY in .env")


def get_client():
    if _client is None:
        _init_client()
    return _client, _provider


def llm_chat(system_prompt: str, user_prompt: str, temperature: float = 0.3, max_retries: int = 2) -> str:
    """Send a chat completion request to the configured LLM."""
    client, provider = get_client()

    for attempt in range(max_retries):
        try:
            if provider == "groq":
                # Try models in order of preference
                models = [
                    "openai/gpt-oss-20b",
                    "llama-3.3-70b-versatile",
                    "llama-3.1-8b-instant",
                ]
                last_err = None
                for model in models:
                    try:
                        response = client.chat.completions.create(
                            model=model,
                            messages=[
                                {"role": "system", "content": system_prompt},
                                {"role": "user", "content": user_prompt},
                            ],
                            temperature=temperature,
                            max_tokens=2000,
                        )
                        return response.choices[0].message.content
                    except Exception as model_err:
                        last_err = model_err
                        logger.warning(f"Groq model {model} failed: {model_err}")
                        continue
                raise last_err

            elif provider == "gemini":
                from google.genai import types
                response = client.models.generate_content(
                    model="gemini-2.5-flash",
                    contents=f"{system_prompt}\n\n{user_prompt}",
                    config=types.GenerateContentConfig(
                        temperature=temperature,
                        max_output_tokens=2000,
                    ),
                )
                return response.text

        except Exception as e:
            logger.error(f"LLM call attempt {attempt + 1} failed: {e}")
            if attempt == max_retries - 1:
                raise
    return ""


def llm_json(system_prompt: str, user_prompt: str, temperature: float = 0.1) -> dict:
    """Get a JSON response from the LLM."""
    full_system = system_prompt + "\n\nYou MUST respond with valid JSON only. No markdown, no explanation, just the JSON object."
    raw = llm_chat(full_system, user_prompt, temperature=temperature)

    # Clean markdown code fences if present
    text = raw.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        # Remove first and last lines (```json and ```)
        lines = [l for l in lines[1:] if not l.strip() == "```"]
        text = "\n".join(lines)

    return json.loads(text)
