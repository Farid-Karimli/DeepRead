from src.agent import Agent
import asyncio

def test_direct_content_to_code():
    """
        This test runs the content to code routine of the agent and returns its result.
    """
    agent = Agent()

    selection = """ For step 1, we use AllenNLP’s SRL method [ 13], 
                    which is based on a deep BiLSTM encoder [ 18 ] with attention
                    and a Conditional Random Field [24] output layer to pro-
                    duce the semantic groups for each semantic role in each
                    action description. Since most of the action descriptions
                    in the source datasets contain only the predicate and ob-
                    ject, we filter out the shorter descriptions and cut the longer
                    descriptions to keep only the predicate and object, i.e.,
                    R = {predicate, object}. 
                """

    repo_url = "https://github.com/yayuanli/MATT.git"

    context = """We introduce Mistake Attribution (MATT), a new task for
                fine-grained understanding of human mistakes in egocentric
                videos. While prior work detects whether a mistake occurs,
                MATT attributes the mistake to what part of the instruction
                is violated (semantic role), when in the video the deviation
                becomes irreversible (the Point-of-No-Return, PNR), andwhere the mistake appears in the PNR frame. We develop
                MisEngine, a data engine that automatically constructs mistake samples from existing datasets with attribution-rich annotations. Applied to large egocentric corpora, MisEngine
                yields EPIC-KITCHENS-M and Ego4D-M—two datasets
                up to two orders of magnitude larger than prior mistake
                datasets. We then present MisFormer, a unified attentionbased model for mistake attribution across semantic, temporal, and spatial dimensions, trained with MisEngine supervision. A human study demonstrates the ecological validity of
                our MisEngine-constructed mistake samples, confirming that
                EPIC-KITCHENS-M and Ego4D-M can serve as reliable
                benchmarks for mistake understanding. Experiments on both
                our datasets and prior benchmarks show that MisFormer,
                as a single unified model, outperforms task-specific SOTA
                methods by at least 6.66%, 21.81%, 18.7%, and 3.00% in
                video-language understanding, temporal localization, handobject interaction, and mistake detection, respectively.
                """


    result = asyncio.run(agent.map_content_to_code(
        content=selection, 
        repo_url=repo_url, 
        context=context
    ))

    return result


if __name__ == "__main__":
    print(test_direct_content_to_code())