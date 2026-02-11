import os
import sqlite3
import numpy as np
import json
import datetime
from openai import OpenAI

# Initialize OpenAI client
client = OpenAI(api_key="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")

# Always use the DB next to this file so Flask and Waitress share the same data
_ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
DB_NAME = os.path.join(_ROOT_DIR, "memories.db")

def init_db():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS memories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            text TEXT,
            image_path TEXT,
            timestamp TEXT,
            embedding TEXT,
            metadata TEXT
        )
    ''')
    
    # Try to add audio_path column if it doesn't exist (migration)
    try:
        c.execute('ALTER TABLE memories ADD COLUMN audio_path TEXT')
    except sqlite3.OperationalError:
        pass # Column likely exists
    
    # Try to add processed column if it doesn't exist (migration)
    try:
        c.execute('ALTER TABLE memories ADD COLUMN processed INTEGER DEFAULT 0')
    except sqlite3.OperationalError:
        pass # Column likely exists

    conn.commit()
    conn.close()

def get_embedding(text):
    response = client.embeddings.create(
        input=text,
        model="text-embedding-3-small"
    )
    return response.data[0].embedding

def add_memory(text, image_path=None, audio_path=None, timestamp=None, processed=True):
    """Add a memory to the database. If processed=False, embedding is skipped."""
    embedding = None
    if processed and text:
        embedding = get_embedding(text)
    
    if timestamp is None:
        timestamp = datetime.datetime.now().isoformat()
    
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('''
        INSERT INTO memories (text, image_path, audio_path, timestamp, embedding, metadata, processed)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    ''', (text, image_path, audio_path, timestamp, 
          json.dumps(embedding) if embedding else None, 
          json.dumps({"source": "user_recording"}), 
          1 if processed else 0))
    
    # Get the ID of the inserted row
    memory_id = c.lastrowid
    
    conn.commit()
    conn.close()
    return memory_id

def add_unprocessed_memory(image_path, audio_path, timestamp=None):
    """Add a raw file pair from ESP32 without processing."""
    return add_memory(text=None, image_path=image_path, audio_path=audio_path, 
                     timestamp=timestamp, processed=False)

def get_unprocessed_memories():
    """Get all memories that haven't been processed yet."""
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('SELECT id, image_path, audio_path, timestamp FROM memories WHERE processed = 0 ORDER BY timestamp ASC')
    rows = c.fetchall()
    conn.close()
    
    results = []
    for row in rows:
        results.append({
            "id": row[0],
            "image_path": row[1],
            "audio_path": row[2],
            "timestamp": row[3]
        })
    return results

def update_memory_processed(memory_id, text, embedding):
    """Update a memory with transcription and embedding after processing."""
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('''
        UPDATE memories 
        SET text = ?, embedding = ?, processed = 1
        WHERE id = ?
    ''', (text, json.dumps(embedding), memory_id))
    conn.commit()
    conn.close()

def get_memories(limit=10, offset=0):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    # Order by timestamp DESC (newest first)
    c.execute('SELECT id, text, image_path, audio_path, timestamp FROM memories ORDER BY timestamp DESC LIMIT ? OFFSET ?', (limit, offset))
    rows = c.fetchall()
    conn.close()
    
    results = []
    for row in rows:
        results.append({
            "id": row[0],
            "text": row[1],
            "image_path": row[2],
            "audio_path": row[3],
            "timestamp": row[4]
        })
    return results

def delete_memory(memory_id):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('DELETE FROM memories WHERE id = ?', (memory_id,))
    deleted = c.rowcount > 0
    conn.commit()
    conn.close()
    return deleted

def search_memories(query_text, n_results=3):
    query_embedding = get_embedding(query_text)
    
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    # Only select processed memories with embeddings
    c.execute('SELECT id, text, image_path, timestamp, embedding FROM memories WHERE processed = 1 AND embedding IS NOT NULL')
    rows = c.fetchall()
    conn.close()
    
    if not rows:
        return []
        
    results = []
    for row in rows:
        db_id, text, image_path, timestamp, emb_json = row
        # Skip if embedding is still null (shouldn't happen with the WHERE clause, but be safe)
        if not emb_json:
            continue
        db_embedding = json.loads(emb_json)
        
        # Calculate cosine similarity
        similarity = np.dot(query_embedding, db_embedding) / (np.linalg.norm(query_embedding) * np.linalg.norm(db_embedding))
        
        results.append({
            "id": db_id,
            "text": text,
            "image_path": image_path,
            "timestamp": timestamp,
            "similarity": similarity
        })
    
    # Sort by similarity
    results.sort(key=lambda x: x["similarity"], reverse=True)
    return results[:n_results]

def synthesize_answer(query, memories):
    context_str = ""
    for mem in memories:
        context_str += f"- [{mem['timestamp']}] {mem['text']}\n"
    
    system_prompt = f"""You are a helpful memory assistant. 
    User is asking a question about their past memories.
    Use the following retrieved memories to answer the user's question.
    If the memories don't fully answer the question, say so, but provide the best relevant info you have.
    
    Context:
    {context_str}
    """
    
    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": query}
        ]
    )
    
    return response.choices[0].message.content

if __name__ == "__main__":
    init_db()
    print("Database initialized.")
