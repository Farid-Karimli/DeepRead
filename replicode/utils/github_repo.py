from github import Github

def get_repo_contents(repo_name: str) -> list:
    """
    Returns a list of all files in a GitHub repository.
    """
    g = Github()
    
    repo = g.get_repo(repo_name)
    contents = []

    try:
        file_content = repo.get_contents("")
    except Exception as e:
        print(f"Could not access file: {e}")

    while contents:
        file_content = contents.pop(0)
        if file_content.type == "dir":
            contents.extend(repo.get_contents(file_content.path))
        else:
            contents.append(file_content)


    return contents



if __name__ == "__main__":
    repo_name = "Farid-Karimli/RepliCode"
    contents = get_repo_contents(repo_name)
    print(contents)