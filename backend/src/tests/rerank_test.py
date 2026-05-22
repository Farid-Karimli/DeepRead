import asyncio
from src.agent import Agent
from pprint import pprint

if __name__ == "__main__":
    agent = Agent()
    reranked_results = asyncio.run(agent.map_content_to_code(
        content="InfoNCELoss",
        repo_url="https://github.com/dojeon-ai/Atari-PB.git",
        context="""
        CURL: Contrastive Unsupervised Reinforcement Learning
        (Laskin et al., 2020b) learns the spatial feature of images
        using augmentation functions and InfoNCE loss. It operates
        by ensuring that two augmented instances of the same image
        are encoded similarly in latent space.
        """
    ))
    pprint(reranked_results)
