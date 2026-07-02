from pathlib import Path

_LLM_PAPERMAGE_SCHEMA = """
        Root object (PaperMageResult):
        {{
            "paper_title": string,
            "n_pages": number,
            "equations": [EquationEntity, ...],   // top-level; not nested under sections
            "sections": [SectionEntity, ...]      // ordered; includes a synthetic "abstract" section first
        }}

        SectionEntity:
        {{
            "entity_id": string,                  // e.g. "abstract", "sec_12"
            "section_header": string,
            "page_index": number,                 // zero-based page of the section header
            "sentences": [SentenceEntity, ...]      // sentences in this section (text lives here, not on the section)
        }}

        SentenceEntity:
        {{
            "entity_id": string,                  // e.g. "sen_105"
            "sentence_content": string,
            "page_index": number,
        }}

        EquationEntity:
        {{
            "entity_id": string,                  // e.g. "eq_3"
            "equation_content": string,
            "page_index": number,
        }}

        Sections do not include section_content in this file — read sentence_content under each section instead.
        Equations live only in the top-level "equations" array.
        Matching tips: prefer sentences for precise spans; if the match is broad, return a section entity_id.
"""


def build_identify_key_sections_prompt(
    papermage_result_path: Path,
) -> str:
    return f"""
        Identify the key pieces of implementation content in the following research paper.
        Focus on content (sections, sentences, equations) that are important to the implementation of the method
        and have a high likelihood of being implemented in the code repository.
        These pieces of content should be ones that aid the reader in understanding the implementation and enable them to compare side-by-side.

        You'll be provided the processed paper content from PaperMage as a JSON file path, with sections, sentences and equations.
        Each piece of content is referenced by an entity_id. Sentences are nested within sections; equations are top-level.

        The schema of the JSON file is the following:
{_LLM_PAPERMAGE_SCHEMA}

        ### Processed Paper JSON File Path ###
        {papermage_result_path}
        ### End Processed Paper JSON File Path ###

        ## Output Format ##
        Return just a JSON object. The first and last character of your output must be {{ and }}. No prose.

        Example:
        {{
            "entities": [
                {{
                    "content_type": "section" | "sentence" | "equation",
                    "entity_id": "entity_id as it appears in the context",
                    "section_id": "entity_id of the parent section when content_type is sentence"
                }},
                ...
            ],
        }}

        IMPORTANT: Make sure that the entity ids in your output match the entity ids in the provided context EXACTLY.
        Do not make up entity ids and do not add descriptive fields to the entity objects.
        """


def build_map_key_sections_to_code_prompt(
    entities: dict,
    code_path: str | None,
) -> str:
    return f"""
        Map the provided entities of a research paper to the code in the corresponding repository (local path provided).
        The entities come from processed paper content from PaperMage, with sections, sentences and equations.
        Each entity includes entity_id, content_type, and the full text content.

        ### Entities ###
        {entities}
        ### End Entities ###

        ### Code ###
        {code_path}
        ### End Code ###

        Provide the code snippets for each entity, and the line numbers of the code snippets.
        Focus on finding actual code snippets (.py, .ipynb, etc.) - try to avoid references to the README or
        If no high-quality code match is found for a content entity - then return an empty list for the 'code_snippets' key
        of the entity item.

        ### Output Format ###
        Return just a JSON object. The first and last character of your output must be {{ and }}. No prose.
        Maintain a flat structure for the code snippets, do not nest them under the entity item.

        Example:
        {{
            "paper_title": ...
            "matches": [
                {{
                    "entity_id": "entity_id as it appears in the context",
                    "content_type": "section" | "sentence" | "equation",
                    "content": "Full text content of the entity",
                    "code_snippets": [
                        {{
                            "content": "print('Hello, world!')",
                            "filepath": "path/to/code/file.py",
                            "start_line": 10,
                            "end_line": 20
                        }},
                    ],
                }}
            ]
        }}

        IMPORTANT: Make sure that the entity ids and content in your output match the entity ids and content in the provided context EXACTLY.
        Do not make up entity ids and do not add descriptive text to the entity content.
        """

def build_single_content_to_code_mapping_prompt(
    content: str | Path,
    repo_path: Path,
    context: str
):

    if isinstance(content, str): # Piece of text
        return f"""
            Map the provided piece of content from a scientific research paper to relevant code
            snippets in its associated code repository, OR determine that no such code exists.

            The content could be text or a path to an image. The local path to the repository
            will be provided. You may also be given surrounding context (nearby text, a caption,
            or the paper abstract) to help disambiguate the selection.

            ## Content ##
            {content}
            ## End Content ##

            ## Context ##
            {context}
            ## End Context ##

            ## Local Repository Path ##
            {repo_path}
            ## End Local Repository Path ##

            ## Important ##
            Papers frequently describe methods, components, or results that are NOT present in
            their associated repository — code is omitted, lives elsewhere, or was never released.
            Reporting that a method is absent is a correct and valuable outcome, not a failure.
            It is equally important NOT to invent a match. Returning loosely related or
            best-guess code when no genuine implementation exists is worse than reporting absence.

            Equally, do not report absence prematurely. Only conclude that code is missing after
            you have actually inspected the repository and looked where the implementation would
            plausibly live.

            ## Procedure ##
            1. Decide whether the selected content is the kind of thing that *should* have a code
            implementation at all (a concrete method, algorithm, or computation) versus content
            that would not normally map to code (motivation, related work, a theoretical claim,
            a dataset description).
            2. If it should map, search the repository for the implementation. Note which files or
            modules you inspected and where you expected the code to be.
            3. Reach one of the verdicts below based on what you found.

            ## Verdicts ##
            - "implemented": you found code that genuinely implements or corresponds to the content.
            - "not_implemented": the content describes something that should have code, but no
            genuine implementation exists in this repository.
            - "not_applicable": the content is not the kind of thing that maps to code.

            ## Output Format ##
            Return just a JSON object. The first and last character of your output must be {{ and }}.
            No prose outside the JSON.

            {{
                "reasoning": "What you looked for, where you searched, and why you reached the verdict.",
                "verdict": "implemented" | "not_implemented" | "not_applicable",
                "code_snippets": [
                    {{
                        "content": "print('Hello, world!')",
                        "filepath": "path relative to the repository root",
                        "start_line": 10,
                        "end_line": 20
                    }}
                ]
            }}

            When the verdict is "not_implemented" or "not_applicable", "code_snippets" must be an
            empty list.
        """

def build_code_to_content_mapping_prompt(
    code: str, # a single piece of code
    papermage_result_path: Path,
):
    return f"""
        Map the provided snippet of code to the content in the corresponding research paper.
        The code will be provided in text format.
        The paper content will be provided as a JSON file path.
        The schema of the JSON file is the following:
{_LLM_PAPERMAGE_SCHEMA}

        ## Paper Content JSON File Path##
        {papermage_result_path}
        ## End Paper Content JSON File Path ##

        ## Code ##
        {code}
        ## End Code ##

        ## Important ##

        Reporting that a piece of code does NOT have an reference in the paper content should be considered a valid response.
        Papers can often omit details or misrepresent the implementation. You should not returning loosely related paper content
        just for the sake of returning something.

        ## Procedure ##
        1. Decide whether the selected code snippet is the kind of thing that *should*
        be referenced in the paper content at all. For example, things like project description READMEs,
        config files, environment and init files like __init__.py, git files cannot be expected to have references in the paper content.
        You should focus on files that perform actual computation relevant to the method described in the paper.
        2. If it should map, search the paper's semantic layers in the content JSON file for references.
        Note that the paper may not go deep into the details of the implementation, but rather a higher-level overview.
        Your objective is to find the most relevant references to the code snippet in the paper content, not whether
        everything about the code snippet is explicitly described in the paper content. Remember that we're dealing with academic papers, not code documentation.
        3. Reach one of the verdicts below based on what you found.

        ## Verdicts ##
        - "described": you found paper content that references the code snippet
        - "not_described": the code snippet should but does not have ANY references of any kind in the paper content.
        - "not_applicable": the code is not the kind of thing that maps to paper content.

        ## Output Format ##
        Return just a JSON object. The first and last character of your output should be {{ and }}. No prose.

        If your verdict is "not_described" or "not_applicable", the "matches" key should be an empty list.

        Provide the type of the entity under the "entity_type" key.

        If matching a sentence, set entity_id to the sentence's entity_id and section_id to its parent section.
        If matching a section, set entity_id to the section's entity_id.
        If matching an equation, set entity_id to the equation's entity_id and leave section_id empty.

        Example:
        {{
            "reasoning": "Concisely - what you looked for, where you searched, and why you reached the verdict.",
            "verdict": "described" | "not_described" | "not_applicable",
            "matches": [
                {{
                    "entity_type": "section" | "sentence" | "equation",
                    "entity_id": "entity_id as it appears in the context",
                    "description": "briefly, how the entity relates to the code snippet",
                    "section_id": "parent section entity_id when entity_type is sentence, otherwise empty string"
                }}
            ]
        }}
        """
