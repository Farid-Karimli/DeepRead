import requests
import logging

from src.config import COHERE_API_KEY

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
logger = logging.getLogger(__name__)

class Reranker:
    def __init__(self, type: str = "cohere"):
        self.type = type
        
        if self.type == "cohere":
            self.cohere_url = "https://api.cohere.com/v2/rerank"
        else:
            raise ValueError(f"Invalid reranker type: {self.type}")

    def rerank(self, query: str, documents: list[str]) -> list[dict]:
        if self.type == "cohere":
            response = requests.post(
                self.cohere_url,
                headers={
                    "Authorization": f"Bearer {COHERE_API_KEY}",
                },
                json={
                    "model": "rerank-v4.0-fast",
                    "query": query,
                    "documents": documents,
                }
            ).json()

            logger.info(f"Reranked {len(documents)} documents for query: {query[:100]}")

            results = response.get("results", [])

            return results
        else:
            raise ValueError(f"Invalid reranker type: {self.type}")

if __name__ == "__main__":
    reranker = Reranker("cohere")
    reranked_results = reranker.rerank(query="What is the capital of France?", documents=["France is a country in Europe.", "France is a country in Europe.", "The capital of France is Paris."])
    print(reranked_results)