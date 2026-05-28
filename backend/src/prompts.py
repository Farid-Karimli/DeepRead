from pathlib import Path


def build_identify_key_sections_prompt(
    paper_content_to_analyze: str,
    github_repository_url: str | None,
) -> str:
    return f"""
        Identify the key sections of the implementation content in the following research paper.
        Focus on sections that have a high likelihood of being implemented in the code repository. These sections
        should be ones that aid the reader in understanding the implementation and enable them to compare side-by-side.

        Ignore sections that are not implementation content, such as introduction, conclusion, figures, tables, etc.

        Also, extract the GitHub repository URL from the paper, if it is present.

        Provide JUST the section names, and start and end lines, short descriptions of the section, and the GitHub repository URL, no other text.

        ### Paper Content ###
        {paper_content_to_analyze}
        ### End Paper Content ###

        ### GitHub Repository URL ###
        In case the repository URL is not present in the paper, it is provided here. Note that this may be empty if the URL is present in the paper already.
        {github_repository_url}
        ### End GitHub Repository URL ###

        Example:
        {{ "sections": [
            {{
                "section_name": "Section 1",
                "start_line": 10,
                "end_line": 20,
                "description": "A comprehensive description of the section", 
            }}
            ],
            "github_repo_url": "https://github.com/your-repo/your-repo.git"
        ]}}

        IMPORTANT: Make sure that the section names in your output match the section names in the provided paper EXACTLY.
        Do not make up section names and do not add
        descriptive text to the section names. Sections should include subsections within sections, marked with a sub-section number. If there is no sub-section number, 
        append a sub-section number to the section name with a period. 

        """

def build_identify_key_sections_prompt_v2(
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
        Provide JUST the code snippets and the line numbers in a JSON object, no other text. 

        Return only a JSON object. First character must be {{ and last must be }}. No prose.

        Example:
        {{
            "paper_title": ...
            "sections": [
                {{
                    "section_id": "entity_id as it appears in the context",
                    "section_header": "section header as it appears in the context",
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
            Map the provided piece of content from a scientific research paper to relevant code snippets
            in its associated code repository. The content could be in text or a path to an image. 
            The local path to the repository will be provided too. 
            You could also be provided context surrounding the specific piece of content the user is interested in, 
            like surrounding text, caption or the paper abstract. 

            ## Content ##
            {content}
            ## End Content

            ## Context ##
            {context}
            ## End Context

            ## Local Repository Path ##
            {repo_path}
            ## End Local Repository Path ## 

            Provide the code snippets for each section, and the line numbers of the code snippets.
            Return just a JSON object. The first and last character of your output should be {{ and }}. 
            No prose. 

            ## Output Format ## 

            {{
                "code_snippets": [
                        {{
                            "content": "print('Hello, world!')",
                            "filepath": path to the file relative to the repository root directory,
                            "start_line": 10,
                            "end_line": 20
                        }},
                    ],
            }}
        """

def build_code_to_content_mapping_prompt(
    code: str, # a single piece of code
    paper_content: list[dict],
):
    return f"""
        Map the provided code snippets to the content in the corresponding research paper.
        The code will be provided in text format. 
        The paper content will be provided as a list of dicts, with section_id, section_header and section_content fields.

        ### Code ###
        {code}
        ### End Code ###

        ### Paper Content ###
        {paper_content}
        ### End Paper Content ###

        Provide the corresponding sections for the code snippet.
        The section id is the entity_id as it appears in the context.
        The description is a short description of how the section relates to the code snippet.
        Return just a JSON object. The first and last character of your output should be {{ and }}. 
        No prose. 
        
        Example:
        {{
            "sections": [
                {{
                    "section_id": "entity_id as it appears in the context",
                    "description": "how the section relates to the code snippet",
                }}
            ]
        }}
        """