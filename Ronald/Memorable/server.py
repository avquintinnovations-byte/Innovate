import os
import tempfile
import uuid
import shutil
import subprocess
import queue
import datetime
import threading
import time
from flask import Flask, request, jsonify, send_from_directory, Response
from flask_cors import CORS
from faster_whisper import WhisperModel
from memory_store import (init_db, add_memory, search_memories, synthesize_answer, 
                          get_memories, delete_memory, add_unprocessed_memory, 
                          get_unprocessed_memories, update_memory_processed, get_embedding)

# Real-time notification queue for SSE
memory_update_queues = []


def webm_to_wav(webm_path):
    """Convert WebM/Opus from browser to 16kHz mono WAV for reliable Whisper input."""
    fd, wav_path = tempfile.mkstemp(suffix=".wav")
    os.close(fd)
    try:
        subprocess.run(
            [
                "ffmpeg", "-y", "-i", webm_path,
                "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1",
                "-loglevel", "error", wav_path
            ],
            check=True,
            capture_output=True,
            timeout=30,
        )
        return wav_path
    except FileNotFoundError:
        raise RuntimeError(
            "ffmpeg is not installed. Install ffmpeg and add it to PATH so WebM from the browser can be converted for transcription."
        )
    except subprocess.CalledProcessError as e:
        stderr = (e.stderr or b"").decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"ffmpeg failed to convert audio: {stderr or str(e)}")

app = Flask(__name__)
CORS(app)  # Enable CORS for all routes

# Initialize DB
init_db()

# Use same project root as memory_store so DB and uploads are always in one place
from memory_store import _ROOT_DIR
UPLOAD_FOLDER = os.path.join(_ROOT_DIR, "uploads")
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

# Initialize Whisper model
model_size = "tiny"
print(f"Loading {model_size} model...")
model = WhisperModel(model_size, device="cpu", compute_type="int8")
print("Model loaded.")

@app.route('/')
def index():
    """Serve the frontend HTML."""
    return send_from_directory(_ROOT_DIR, 'index.html')

@app.route('/<path:filename>')
def serve_static(filename):
    """Serve static files (CSS, JS)."""
    if filename in ['style.css', 'script.js', 'favicon.ico']:
        return send_from_directory(_ROOT_DIR, filename)
    return "File not found", 404

@app.route('/uploads/<path:filename>')
def serve_image(filename):
    return send_from_directory(UPLOAD_FOLDER, filename)

@app.route('/stream')
def stream():
    """Server-Sent Events endpoint for real-time memory updates."""
    def event_stream():
        q = queue.Queue()
        memory_update_queues.append(q)
        try:
            # Send initial connection message
            yield f"data: {jsonify({'type': 'connected'}).get_data(as_text=True)}\n\n"
            
            while True:
                # Wait for new memory notification
                message = q.get()
                yield f"data: {message}\n\n"
        except GeneratorExit:
            memory_update_queues.remove(q)
    
    return Response(event_stream(), mimetype="text/event-stream")

@app.route('/memories', methods=['GET'])
def list_memories():
    try:
        limit = int(request.args.get('limit', 10))
        offset = int(request.args.get('offset', 0))
        memories = get_memories(limit, offset)
        return jsonify(memories)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/memories/<int:memory_id>', methods=['DELETE'])
def remove_memory(memory_id):
    try:
        success = delete_memory(memory_id)
        if success:
            return jsonify({'success': True})
        else:
            return jsonify({'error': 'Memory not found'}), 404
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/upload_esp32', methods=['POST'])
def upload_esp32():
    """ESP32 sync endpoint - only stores files, processing happens on server."""
    if 'audio' not in request.files or 'image' not in request.files:
        return jsonify({'error': 'Missing audio or image'}), 400
    
    audio_file = request.files['audio']
    image_file = request.files['image']
    file_index = request.form.get('index', 'unknown')
    
    print(f"[ESP32 Sync] Received pair #{file_index}")
    
    try:
        # Save audio file
        ext = os.path.splitext(audio_file.filename or '')[-1].lower() or '.wav'
        if ext not in ('.wav', '.mp3', '.ogg', '.m4a'):
            ext = '.wav'
        audio_filename = f"audio_{uuid.uuid4().hex}{ext}"
        saved_audio_path = os.path.join(UPLOAD_FOLDER, audio_filename)
        audio_file.save(saved_audio_path)
        
        # Validate audio file
        audio_size = os.path.getsize(saved_audio_path)
        if audio_size < 1000:  # Less than 1KB
            print(f"[ESP32 Sync] WARNING: Audio file very small ({audio_size} bytes)")
        
        # Save image file
        img_ext = os.path.splitext(image_file.filename or '')[-1].lower() or '.jpg'
        image_filename = f"img_{uuid.uuid4().hex}{img_ext}"
        saved_image_path = os.path.join(UPLOAD_FOLDER, image_filename)
        image_file.save(saved_image_path)
        
        # Validate image file
        image_size = os.path.getsize(saved_image_path)
        if image_size < 1000:  # Less than 1KB
            print(f"[ESP32 Sync] WARNING: Image file very small ({image_size} bytes)")
        
        # Store as unprocessed in database (no transcription yet)
        db_image_path = f"/uploads/{image_filename}"
        db_audio_path = f"/uploads/{audio_filename}"
        
        memory_id = add_unprocessed_memory(db_image_path, db_audio_path)
        
        print(f"[ESP32 Sync] Files stored, memory #{memory_id} queued for processing")
        print(f"[ESP32 Sync] Audio: {audio_size} bytes, Image: {image_size} bytes")
        
        return jsonify({
            'success': True,
            'memory_id': memory_id,
            'status': 'queued_for_processing',
            'index': file_index
        })
    
    except Exception as e:
        print(f"[ESP32 Sync] Error storing pair #{file_index}: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

@app.route('/transcribe', methods=['POST'])
def transcribe():
    if 'audio' not in request.files:
        return jsonify({'error': 'No audio file provided'}), 400
    
    audio_file = request.files['audio']
    image_file = request.files.get('image')  # Optional image
    custom_timestamp = request.form.get('timestamp')  # Optional ISO datetime (e.g. for ESP32 sync)

    # Save audio persistently; keep extension from upload (e.g. .webm from browser, .wav from ESP32)
    ext = os.path.splitext(audio_file.filename or '')[-1].lower() or '.webm'
    if ext not in ('.webm', '.wav', '.mp3', '.ogg', '.m4a'):
        ext = '.webm'
    audio_filename = f"audio_{uuid.uuid4().hex}{ext}"
    saved_audio_path = os.path.join(UPLOAD_FOLDER, audio_filename)
    audio_file.save(saved_audio_path)

    saved_image_path = None
    if image_file:
        img_ext = os.path.splitext(image_file.filename or '')[-1].lower() or '.jpg'
        filename = f"img_{uuid.uuid4().hex}{img_ext}"
        saved_image_path = os.path.join(UPLOAD_FOLDER, filename)
        image_file.save(saved_image_path)

    try:
        # Convert to WAV for reliable Whisper input (browser sends WebM/Opus; ESP32 may send WAV)
        audio_to_transcribe = saved_audio_path
        wav_path = None
        try:
            wav_path = webm_to_wav(saved_audio_path)
            audio_to_transcribe = wav_path
        except RuntimeError as e:
            print(f"WebM conversion failed ({e}), trying direct transcribe...")
            # Fallback: try transcribing WebM directly (may work if PyAV supports it)
        try:
            segments, info = model.transcribe(audio_to_transcribe, beam_size=5)
            transcription_text = "".join([segment.text for segment in segments]).strip()
        finally:
            if wav_path and os.path.exists(wav_path):
                try:
                    os.remove(wav_path)
                except OSError:
                    pass

        # Store in Memory Store (DB + Embeddings) - always store so it shows in the app (e.g. ESP32-processed)
        db_image_path = f"/uploads/{os.path.basename(saved_image_path)}" if saved_image_path else None
        db_audio_path = f"/uploads/{audio_filename}"
        text_to_store = transcription_text if transcription_text else "(No speech detected)"
        memory_id = add_memory(
            text_to_store, db_image_path, db_audio_path,
            timestamp=custom_timestamp if custom_timestamp else None
        )
        print(f"Memory stored in database with ID: {memory_id}")

        return jsonify({
            'text': transcription_text,
            'language': info.language,
            'probability': info.language_probability,
            'memory_id': memory_id,
            'audio_path': f"/uploads/{audio_filename}"
        })

    except Exception as e:
        print(f"Error during transcription: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

@app.route('/recall', methods=['POST'])
def recall():
    if 'audio' not in request.files:
        return jsonify({'error': 'No audio file provided'}), 400
        
    audio_file = request.files['audio']
    
    with tempfile.NamedTemporaryFile(delete=False, suffix=".webm") as temp_audio:
        audio_file.save(temp_audio.name)
        temp_path = temp_audio.name

    wav_path = None
    try:
        # Convert WebM to WAV for reliable Whisper input
        try:
            wav_path = webm_to_wav(temp_path)
            audio_to_transcribe = wav_path
        except RuntimeError as e:
            print(f"WebM conversion failed ({e}), trying direct transcribe...")
            audio_to_transcribe = temp_path

        # 1. Transcribe the query
        segments, _ = model.transcribe(audio_to_transcribe, beam_size=5)
        query_text = "".join([segment.text for segment in segments]).strip()
        print(f"Recall Query: {query_text}")

        if not query_text:
            return jsonify({'text': "", 'answer': "I didn't hear anything.", 'memories': []})

        # 2. Retrieve relevant memories
        relevant_memories = search_memories(query_text)

        # 3. Synthesize answer with LLM
        if not relevant_memories:
            answer = "I couldn't find any relevant memories matching your request."
        else:
            answer = synthesize_answer(query_text, relevant_memories)

        return jsonify({
            'query_text': query_text,
            'answer': answer,
            'memories': relevant_memories
        })

    except Exception as e:
        print(f"Error during recall: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500
    finally:
        if wav_path and os.path.exists(wav_path):
            try:
                os.remove(wav_path)
            except OSError:
                pass
        if os.path.exists(temp_path):
            os.remove(temp_path)

# ============================================================================
# Background Processing System
# ============================================================================

processing_active = True
processing_stats = {
    'total_processed': 0,
    'last_processed_time': None,
    'errors': 0
}

def process_single_memory(memory_info):
    """Process a single unprocessed memory."""
    memory_id = memory_info['id']
    audio_path = memory_info['audio_path']
    
    # Skip if no audio path
    if not audio_path:
        print(f"[Processor] Memory #{memory_id} has no audio path, skipping")
        return False
    
    # Convert relative path to absolute
    if audio_path.startswith('/uploads/'):
        audio_filename = audio_path.replace('/uploads/', '')
        full_audio_path = os.path.join(UPLOAD_FOLDER, audio_filename)
    else:
        full_audio_path = os.path.join(UPLOAD_FOLDER, audio_path)
    
    if not os.path.exists(full_audio_path):
        print(f"[Processor] Audio file not found: {full_audio_path}")
        return False
    
    wav_path = None
    try:
        # Check file size first
        file_size = os.path.getsize(full_audio_path)
        if file_size < 1000:  # Less than 1KB is suspicious
            print(f"[Processor] Audio file too small ({file_size} bytes), likely corrupted")
            return False
        
        # Convert to WAV if needed (skip for .wav files from ESP32)
        audio_to_transcribe = full_audio_path
        if not full_audio_path.lower().endswith('.wav'):
            try:
                wav_path = webm_to_wav(full_audio_path)
                audio_to_transcribe = wav_path
            except RuntimeError as e:
                print(f"[Processor] Conversion failed ({e}), trying original file")
        
        # Transcribe
        try:
            segments, info = model.transcribe(audio_to_transcribe, beam_size=5)
            transcription_text = "".join([segment.text for segment in segments]).strip()
        except Exception as e:
            print(f"[Processor] Transcription failed for memory #{memory_id}: {e}")
            print(f"[Processor] File: {full_audio_path}, Size: {file_size} bytes")
            return False
        
        # Generate embedding
        text_to_store = transcription_text if transcription_text else "(No speech detected)"
        embedding = get_embedding(text_to_store)
        
        # Update database
        update_memory_processed(memory_id, text_to_store, embedding)
        
        print(f"[Processor] Memory #{memory_id} processed: {text_to_store[:50]}...")
        
        # Broadcast to all SSE clients
        import json as json_lib
        memory_data = json_lib.dumps({
            'type': 'new_memory',
            'memory': {
                'id': memory_id,
                'text': text_to_store,
                'image_path': memory_info['image_path'],
                'audio_path': audio_path,
                'timestamp': memory_info['timestamp']
            }
        })
        for q in memory_update_queues:
            try:
                q.put(memory_data)
            except:
                pass
        
        return True
        
    except Exception as e:
        print(f"[Processor] Error processing memory #{memory_id}: {e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        if wav_path and os.path.exists(wav_path):
            try:
                os.remove(wav_path)
            except OSError:
                pass

def background_processor():
    """Background thread that processes unprocessed memories."""
    print("[Processor] Background processor started")
    
    while processing_active:
        try:
            # Get unprocessed memories
            unprocessed = get_unprocessed_memories()
            
            if unprocessed:
                print(f"[Processor] Found {len(unprocessed)} unprocessed memories")
                
                for memory in unprocessed:
                    if not processing_active:
                        break
                    
                    success = process_single_memory(memory)
                    
                    if success:
                        processing_stats['total_processed'] += 1
                        processing_stats['last_processed_time'] = datetime.datetime.now().isoformat()
                    else:
                        processing_stats['errors'] += 1
                    
                    # Small delay between processing
                    time.sleep(0.5)
            
            # Wait before checking again
            time.sleep(5)
            
        except Exception as e:
            print(f"[Processor] Error in background processor: {e}")
            import traceback
            traceback.print_exc()
            time.sleep(10)
    
    print("[Processor] Background processor stopped")

@app.route('/sync_status', methods=['GET'])
def sync_status():
    """Get status of file syncing and processing."""
    try:
        unprocessed = get_unprocessed_memories()
        return jsonify({
            'unprocessed_count': len(unprocessed),
            'processing_stats': processing_stats,
            'processor_active': processing_active
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/process_now', methods=['POST'])
def process_now():
    """Manually trigger processing of pending files."""
    try:
        unprocessed = get_unprocessed_memories()
        
        if not unprocessed:
            return jsonify({
                'success': True,
                'message': 'No unprocessed files',
                'processed_count': 0
            })
        
        processed_count = 0
        errors = []
        
        for memory in unprocessed:
            success = process_single_memory(memory)
            if success:
                processed_count += 1
            else:
                errors.append(memory['id'])
        
        return jsonify({
            'success': True,
            'processed_count': processed_count,
            'total_count': len(unprocessed),
            'errors': errors
        })
    
    except Exception as e:
        print(f"Error in manual processing: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    # Start background processor thread
    processor_thread = threading.Thread(target=background_processor, daemon=True)
    processor_thread.start()
    print("[Server] Background processor thread started")
    
    ssl_context = None
    # If you generated cert.pem/key.pem (via generate_cert.py),
    # run the API over HTTPS so mobile browsers allow mic/camera usage.
    if os.path.exists("cert.pem") and os.path.exists("key.pem"):
        ssl_context = ("cert.pem", "key.pem")

    try:
        app.run(host='0.0.0.0', port=5000, debug=True, ssl_context=ssl_context)
    finally:
        processing_active = False
        print("[Server] Shutting down background processor...")
