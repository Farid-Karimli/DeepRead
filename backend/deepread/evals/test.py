from google import genai
import os
import json
from deepread.evals.evaluation import EVALUATION_PROMPT, evaluate_result
from dotenv import load_dotenv

load_dotenv(override=False)

key_sections = json.load(open("./../key_sections.json"))
code_result = json.load(open("./../code_result.json"))

client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
result = evaluate_result(key_sections, code_result, client)
print(result)