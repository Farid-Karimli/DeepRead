import os
import pprint
import asyncio
import json
from dotenv import load_dotenv
from tqdm import tqdm
from datasets import Dataset, load_dataset
from deepread.agent import Agent
from deepread.evals.data import get_paper_data
from deepread.evals.utils import clone_repo_to_temp_dir, delete_temp_dir

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

- The agent should have mapped all the key sections of the research paper (for example, architecture, training, inference, environment, etc.) to code snippets in the code repository. In other words, no key section should be left unmapped.
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

def evaluate_result(key_sections: dict, code_result: dict, client: genai.Client) -> dict:
    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=EVALUATION_PROMPT.format(
            key_sections=json.dumps(key_sections),
            code_snippets=json.dumps(code_result),
        ),
    )
    try: 
        response_json = json.loads(response.text.replace("```json", "").replace("```", "").strip())
        return response_json
    except json.JSONDecodeError:
        print(f"Error parsing JSON from evaluation result: {response.text}")
        return None    

async def run_deepread_on_dataset(ds: Dataset, output_dir: str, n_rows: int = None) -> None:
    agent = Agent()
    evaluation_client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

    evaluation_results = []

    selected_ds = ds.select(range(n_rows)) if n_rows is not None else ds
    for row in tqdm(selected_ds, desc="Evaluating dataset"):
        paper_data = get_paper_data(row)
        key_sections = await agent.identify_key_sections(paper_content=paper_data['paper_text'])
        if key_sections is not None:
            print(f"Key sections found for {paper_data['github_repo_url']}")
            try:
                repo_local_dir = clone_repo_to_temp_dir(paper_data['github_repo_url']) # Clone the repository to a temporary directory, for faster file system operations.
                print(f"Cloned repository to {repo_local_dir}")
            except Exception as e:
                print(f"Failed to clone repository: {e}")
                continue

            code_result = await agent.map_key_sections_to_code(key_sections=key_sections, code_path=repo_local_dir)

            if code_result is not None:
                print(f"Code result found for {paper_data['github_repo_url']}")
                result = evaluate_result(key_sections, code_result, evaluation_client)
                evaluation_results.append({
                    "paper_data": paper_data,
                    "key_sections": key_sections,
                    "code_result": code_result,
                    "evaluation_result": result
                })
            else:
                print(f"No code result found for {paper_data['github_repo_url']}")
                continue

            delete_temp_dir(repo_local_dir) # Delete the temporary directory.

    if not os.path.exists(output_dir):
        os.makedirs(output_dir)

    with open(os.path.join(output_dir, "evaluation_results.json"), "w") as f:
        json.dump(evaluation_results, f, indent=4)

if __name__ == "__main__":
    # Run the agent first, before creating the Gemini client, so the Claude CLI
    # subprocess runs in a clean environment (avoids interaction with genai init).
    if os.getenv("GEMINI_API_KEY") is None:
        print("GEMINI_API_KEY is not set")
        exit(1)
    else:
        print("GEMINI_API_KEY is set")

    ds = load_dataset("iaminju/paper2code", split="test")
    asyncio.run(run_deepread_on_dataset(ds, "evals/results", n_rows=5))