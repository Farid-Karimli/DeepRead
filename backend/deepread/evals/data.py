from datasets import Dataset, load_dataset
from typing import Generator


def get_paper_data(row: dict) -> str:
    paper_sections_combined = {}
    for section in row['paper_cleaned_json']['pdf_parse']['body_text']:
        section_name = (
            section['sec_num'] + ' ' + section['section']
            if section['sec_num'] is not None
            else section['section']
        ).strip()
        if section_name not in paper_sections_combined:
            paper_sections_combined[section_name] = ''
        paper_sections_combined[section_name] += section['text']

    paper_text_combined = ''
    for section_name, section_text in paper_sections_combined.items():
        paper_text_combined += section_name + '\n' + section_text + '\n\n'
    return {
        'paper_text': paper_text_combined,
        'github_repo_url': row['repo_url']
    }


def get_paper_data_generator(ds: Dataset) -> Generator[dict, None, None]:
    for row in ds['test']:
        yield get_paper_data(row)


if __name__=="__main__":
    ds = load_dataset("iaminju/paper2code", split="test")
    print(get_paper_data(ds[0]))