import os
import uuid

import vecs
import voyageai
from typing import List
from pprint import pprint
from chunker import chunk_file
from dotenv import load_dotenv
from vecs import IndexMethod, IndexMeasure, IndexArgsHNSW


from deepread.utils import k_nearest_neighbors
from deepread.vectorize.utils import TreeSitterCodeChunk, CodeChunk, find_files_by_pattern


load_dotenv()

CODE_DIR = os.path.join(os.path.dirname(__file__), "..", "..","code")
RECTIFIED_FLOW_DIR = os.path.join(CODE_DIR, "RectifiedFlow")
FILE = os.path.join(RECTIFIED_FLOW_DIR, "ImageGeneration", "losses.py")

vo = voyageai.Client(os.environ.get("VOYAGE_API_KEY"))

class CodeVectorDB:
    def __init__(self, db_connection: str):
        self.db_connection_string = db_connection
        self.vx = vecs.create_client(self.db_connection_string)
        self.code_collection = self.vx.get_or_create_collection(name='code', dimension=1536)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False
    
    def add_chunks(self, chunks: List[CodeChunk]):
        if chunks is None or len(chunks) == 0:
            return
        embeddings = vo.embed([chunk.content for chunk in chunks if chunk.content is not None or chunk.content != ""], model="voyage-code-2").embeddings
        records = [(str(chunk.chunk_id), embedding, 
            {"file_path": chunk.file_path, 
            "start_line": chunk.start_line, 
            "end_line": chunk.end_line,
            "content": chunk.content}) for chunk, embedding in zip(chunks, embeddings)]
        self.code_collection.upsert(records=records)

    def vectorize_repo(self, repo_dir: str):
        repo_files = find_files_by_pattern(repo_dir, ["*.py"])
        print(f"Found {len(repo_files)} files in {repo_dir}")
        for f in repo_files:
            chunks = chunk_file(os.path.join(repo_dir, f), "python")
            chunks = [CodeChunk(chunk_id=uuid.uuid4(), file_path=f, start_line=chunk.start_line, end_line=chunk.end_line, content=chunk.content) for chunk in chunks]
            print(f"Found {len(chunks)} chunks in {f}")
            self.add_chunks(chunks)

    def query(self, query: str, k: int = 3):
        query_embedding = vo.embed([query], model="voyage-code-2").embeddings[0]
        retrieved = self.code_collection.query(
            data=query_embedding,
            limit=k,
            filters={},
            measure="cosine_distance",
            include_value=True,
            include_metadata=True,
        )
        return retrieved

if __name__ == "__main__":
    with CodeVectorDB(os.getenv("SUPABASE_DB_CONN_STR")) as db:
        db.vectorize_repo(RECTIFIED_FLOW_DIR)
        retrieved = db.query("What is the loss function used in the training loop?")
        print(retrieved)