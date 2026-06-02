import requests
from pprint import pprint

from src.config import BRAVE_SEARCH_API_KEY, BRAVE_ANSWERS_API_KEY


def search_github(query: str) -> list[dict]:
    url = "https://api.search.brave.com/res/v1/web/search"

    if "site:github.com" not in query:
        query += " site:github.com"
    
    params = {
        "q": query, 
        "extra_snippets": "true"
    }
    headers = {
        "Accept": "application/json",
        "Accept-Encoding": "gzip",
        "X-Subscription-Token": BRAVE_SEARCH_API_KEY
    }

    response = requests.get(url, params=params, headers=headers).json()
    result = response.get("web", {}).get("results", [])

    result = [{
        "title": item.get("title"),
        "url": item.get("url"),
        "snippet": item.get("snippet")
    } for item in result]

    return result

def brave_find_github_repo(paper_title: str, paper_authors: str, deep_search: bool = False) -> str:
    url = "https://api.search.brave.com/res/v1/chat/completions"
    data = {
        "stream": False, 
        "messages": [
            {
                "role": "user", 
                "content": 
                
                f"""
                What is the GitHub repository URL for the following paper: {paper_title} by {", ".join(paper_authors)}? 
                Return only the GitHub repository URL, no other text.
                """
            }
        ],
        "extra_body": {
            "enable_research": deep_search
        }
    }

    headers = {
        "Content-Type": "application/json",
        "X-Subscription-Token": BRAVE_ANSWERS_API_KEY
    }

    response = requests.post(url, json=data, headers=headers).json()
    return response.get("choices", [{}])[0].get("message", {}).get("content", "").strip()


if __name__ == "__main__":
    q = "Mistake Attribution: Fine-Grained Mistake Understanding in Egocentric Videos by Yayuan Li, Aadit Jain, Filippos Bellos, Jason J. Corso"
    result = search_github(q)
    pprint(result)