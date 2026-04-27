import requests

OLLAMA_API_URL = "http://localhost:11434/api/generate"
OLLAMA_MODEL = "qwen3:0.6b"
chunk = "感冒吃什么药"
prompt = f"""
    Provide meaningful attributes for every entity to add context and depth.
    Important: Use exact text from the input for extraction_text. Do not paraphrase.
    Extract entities in order of appearance with no overlapping text spans.
From the following text, extract nodes (entities such as people, places) and edges (relationships between entities, such as "mentioned" or "interacted").
Output in JSON format with 'nodes' and 'edges' fields:
- nodes: List of objects with 'id' (unique identifier) and 'label' (entity name).
- edges: List of objects with 'source' (source node id), 'target' (target node id), and 'label' (relationship description).
- 输出：所有内容使用中文输出
Example output:
{{
  "nodes": [{{"id": "entity1", "label": "Entity 1"}}, {{"id": "entity2", "label": "Entity 2"}}],
  "edges": [{{"source": "entity1", "target": "entity2", "label": "mentioned"}}]
}}
Text: {chunk}
"""
data = {
        "model": OLLAMA_MODEL,
        "prompt": prompt,
        "stream": False  # Ensure full response is returned
    }
response = requests.post(OLLAMA_API_URL, json=data, timeout=30)
print(f"API request status code: {response.json()}")