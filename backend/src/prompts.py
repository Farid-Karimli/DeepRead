from pathlib import Path

def build_identify_key_sections_prompt(
    relevant_sections: dict,
) -> str:
    return f"""
        Identify the key sections of the implementation content in the following research paper.
        Focus on sections that are important to the implementation of the method and have a high likelihood of being implemented in the code repository. 
        These sections should be ones that aid the reader in understanding the implementation and enable them to compare side-by-side.

        You'll be provided sections in JSON format - with entity_id, section_eader and section_content fields.

        Provide JUST the section names, short descriptions of the section, and the section ids, no other text.

        ### Paper Content ###
        {relevant_sections}
        ### End Paper Content ###

        Example:
        {{ 
            "sections": [
                {{
                    "section_id": "entity_id as it appears in the context",
                    "section_header": "Full section header",
                    "description": "A description of the section", 
                }}
            ]
        }}

        IMPORTANT: Make sure that the section ids and headers in your output match the section names in the provided context EXACTLY.
        Do not make up section names and do not add descriptive text to the section names. 
        """


def build_map_key_sections_to_code_prompt(
    key_sections: dict,
    code_path: str | None,
) -> str:
    return f"""
        Map the provided key sections of a research papers to the code in the corresponding repository (local path provided).

        ### Key Sections ###
        {key_sections}
        ### End Key Sections ###

        ### Code ###
        {code_path}
        ### End Code ###

        Provide the code snippets for each section, and the line numbers of the code snippets. 
        Focus on finding actual code snippets (.py, .ipynb, etc.) - try to avoid references to the README or 
        If no high-quality code match is found for a content section - then return an empty list for the 'code_snippets' key 
        of the section item. 

        Provide your response in a JSON object outlined below, no other text. 
        First character must be {{ and last must be }}. No prose.

        Example:
        {{
            "paper_title": ...
            "sections": [
                {{
                    "section_id": "entity_id as it appears in the context",
                    "section_header": "section header as it appears in the context",
                    "description": "a brief description of what the snippets implement"
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

        IMPORTANT: Make sure that the section headers and ids in your output match what is provided in the context. Do not make up section headers and do not add
        descriptive text.
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
    paper_content: list[dict],
):
    return f"""
        Map the provided snippet of code to the content in the corresponding research paper.
        The code will be provided in text format. 
        The paper content will be provided as a list of dicts, with section_id, section_header and section_content fields.

        ## Paper Content ##
        {paper_content}
        ## End Paper Content ##

        ## Code ##
        {code}
        ## End Code ##

        ## Important ##

        Reporting that a piece of code does NOT have an explanation in the paper content should be considered a valid response.
        Papers can often omit details or misrepresent the implementation. You should not returning loosely related paper content 
        just for the sake of returning something.

        ## Procedure ##
        1. Decide whether the selected code snippet is the kind of thing that *should* 
        be referenced in the paper content at all. For example, things like project description READMEs,
        config files, environment and init files like __init__.py, git files cannot be expected to have references in the paper content.
        You should focus on files that perform actual computation relevant to the method described in the paper. 
        2. If it should map, search the paper sections for references.
        3. Reach one of the verdicts below based on what you found.

        ## Verdicts ##
        - "described": you found code that genuinely implements or corresponds to the paper's content.
        - "not_described": the code describes something that should have an explanation/description in the paper, 
        but no genuine reference exists in the paper.
        - "not_applicable": the code is not the kind of thing that maps to paper content.

        ## Output Format ## 
        Return just a JSON object. The section id is the entity_id as it appears in the context.
        If your verdict is "not_described" or "not_applicable", the "sections" key should be an empty list.
        The first and last character of your output should be {{ and }}. No prose. 
        
        Example:
        {{
            "reasoning": "Concisely - what you looked for, where you searched, and why you reached the verdict.",
            "verdict": "described" | "not_described" | "not_applicable",
            "sections": [
                {{
                    "section_id": "entity_id as it appears in the context",
                    "description": "briefly, how the section relates to the code snippet",
                }}
            ]
        }}
        """