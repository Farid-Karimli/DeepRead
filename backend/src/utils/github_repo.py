from github import Github
from github.ContentFile import ContentFile

def get_repo_contents(repo_name: str) -> list:
    """
    Returns a list of all files in a GitHub repository.
    """
    g = Github()
    
    repo = g.get_repo(repo_name)
    contents = []

    try:
        file_content: list[ContentFile] = repo.get_contents("")
    except Exception as e:
        print(f"Could not access file: {e}")

    while file_content:
        file = file_content.pop(0)
        if file.type == "dir":
            contents.extend(repo.get_contents(file.path))
        else:
            contents.append(file)


    return contents



if __name__ == "__main__":
    repo_name = "dvlab-research/ControlNeXt"    
    contents = get_repo_contents(repo_name)
    print(F"Found {len(contents)} files.")
    print(contents)