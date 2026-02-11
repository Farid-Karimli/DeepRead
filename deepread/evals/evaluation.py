import os
import pprint
import asyncio
import json
from dotenv import load_dotenv
from agent import Agent

# Load .env file but don't override existing environment variables
# This ensures we use a valid ANTHROPIC_API_KEY from system env if available,
# while still loading GEMINI_API_KEY from .env if needed
load_dotenv(override=False)

# Import genai after loading environment variables to avoid initialization issues
from google import genai

EVALUATION_PROMPT = """
You're an evaluator for a code agent that maps key sections of a research paper to code snippets in a code repository.
You will be given sections from a research paper and the code snippets that the agent mapped to the sections.
You will need to evaluate the agent's output and provide a score for how good the agent's mapping is.

## Evaluation Criteria

- The agent should have mapped all the key sections of the research paper (for example, architecture, training, inference, environment, etc.) to code snippets in the code repository.
- The agent should have mapped the key sections of the research paper to the correct code snippets in the code repository. In other words, the code snippets should be correct for the section.
- The agent should have mapped the key sections of the research paper to the correct line numbers of the code snippets in the code repository. In other words, the line numbers should be correct for the section.

## Evaluation Score

The evaluation score is a number between 0 and 10, where 10 is the best score.

## Output Format

Provide the evaluation score in the following JSON format:
{{
    "evaluation_score": <score>
}}

## Key Sections From Research Paper
This is the key sections from the research paper that the agent extracted from the paper.

{key_sections}

## Code Snippets from Code Repository
This is the code snippets from the code repository that the agent mapped to the key sections from the research paper.

{code_snippets}
"""

if __name__ == "__main__":
    # Run the agent first, before creating the Gemini client, so the Claude CLI
    # subprocess runs in a clean environment (avoids interaction with genai init).
    if os.getenv("GEMINI_API_KEY") is None:
        print("GEMINI_API_KEY is not set")
        exit(1)
    else:
        print(f"GEMINI_API_KEY: {os.getenv('GEMINI_API_KEY')}")

    with open("key_sections.json", "r") as f:
        key_sections = json.load(f)
    with open("code_result.json", "r") as f:
        code_result = json.load(f)

    # The client gets the API key from the environment variable `GEMINI_API_KEY`.
    
    
    client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

    if key_sections is not None and code_result is not None:
        print(f"********* Key Sections *********")
        pprint.pprint(key_sections)
        print(f"********* End Key Sections *********")
        print(f"********* Code Snippets *********")
        pprint.pprint(code_result)
        print(f"********* End Code Snippets *********")
        response = client.models.generate_content(
            model="gemini-3-flash-preview",
            contents=EVALUATION_PROMPT.format(
                key_sections=json.dumps(key_sections),
                code_snippets=json.dumps(code_result),
            ),
        )
        print(response.text)
    else:
        print("Skipping evaluation (missing key_sections or code_result).")