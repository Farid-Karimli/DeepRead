import requests
from pprint import pprint

from src.config import BRAVE_SEARCH_API_KEY


def search_github(query: str) -> list[dict]:
    url = "https://api.search.brave.com/res/v1/web/search"

    if "site:github.com" not in query:
        query += " site:github.com"
    
    params = {
        "q": query
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

if __name__ == "__main__":
    result = search_github("Linear Bandits with Memory: from Rotting to Rising")
    pprint(result)