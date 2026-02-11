document.addEventListener('DOMContentLoaded', () => {
    const chatContainer = document.getElementById('chatContainer');
    const statusIndicator = document.getElementById('statusIndicator');
    const cameraPreview = document.getElementById('cameraPreview');
    const snapshotCanvas = document.getElementById('snapshotCanvas');
    
    let mediaRecorder;
    let audioChunks = [];
    let isRecording = false;
    let isRecalling = false;
    let streamReference = null;   // camera+mic when holding Record
    let audioOnlyStream = null;   // mic only for Recall (reused)
    
    // Lazy Loading State
    let currentOffset = 0;
    const LIMIT = 50;
    let isLoadingMemories = false;
    let allLoaded = false;

    // --- Initial Load ---
    loadMemories(true);
    
    // --- Real-time updates via SSE ---
    let eventSource;
    function connectSSE() {
        const backendUrl = getBackendUrl('/stream');
        eventSource = new EventSource(backendUrl);
        
        eventSource.onmessage = (event) => {
            try {
                const data = JSON.parse(event.data);
                if (data.type === 'new_memory') {
                    // Check if memory already exists (avoid duplicates)
                    if (document.getElementById(`memory-${data.memory.id}`)) {
                        return;
                    }
                    
                    // Add new memory to the bottom
                    const el = createMemoryElement(data.memory);
                    chatContainer.appendChild(el);
                    chatContainer.scrollTop = chatContainer.scrollHeight;
                    
                    // Hide placeholder if visible
                    const placeholder = document.querySelector('.placeholder-text');
                    if (placeholder) placeholder.style.display = 'none';
                    
                    console.log('New memory received via SSE:', data.memory.id);
                }
            } catch (error) {
                console.error('Error parsing SSE message:', error);
            }
        };
        
        eventSource.onerror = (error) => {
            console.error('SSE connection error:', error);
            eventSource.close();
            // Reconnect after 5 seconds
            setTimeout(connectSSE, 5000);
        };
    }
    
    connectSSE();

    // --- Refresh (e.g. after processing from device) ---
    function refreshMemories() {
        const bubbles = chatContainer.querySelectorAll('.message-bubble, .system-message');
        bubbles.forEach(el => el.remove());
        const placeholder = document.querySelector('.placeholder-text');
        if (placeholder) placeholder.style.display = '';
        currentOffset = 0;
        allLoaded = false;
        loadMemories(true);
    }

    // --- Infinite Scroll ---
    chatContainer.addEventListener('scroll', () => {
        if (chatContainer.scrollTop === 0 && !isLoadingMemories && !allLoaded) {
            // User scrolled to top, load older memories
            const currentHeight = chatContainer.scrollHeight;
            loadMemories(false).then(() => {
                // Maintain scroll position relative to bottom content
                const newHeight = chatContainer.scrollHeight;
                chatContainer.scrollTop = newHeight - currentHeight;
            });
        }
    });

    // --- Media: camera only when holding Record; mic for Recall on first use ---
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
        console.warn('getUserMedia not supported');
    }

    function initializeRecorder(stream) {
        try {
            let audioStream = stream.getAudioTracks().length > 0 ? new MediaStream(stream.getAudioTracks()) : stream;
            mediaRecorder = new MediaRecorder(audioStream);

            mediaRecorder.ondataavailable = (e) => { audioChunks.push(e.data); };

            mediaRecorder.onstop = () => {
                const audioBlob = new Blob(audioChunks, { type: 'audio/webm' });
                audioChunks = [];

                if (isRecalling) {
                    handleRecall(audioBlob);
                } else {
                    captureImage((imageBlob) => {
                        const uiRefs = addMemoryBubble({
                            audioBlob: audioBlob,
                            imageBlob: imageBlob,
                            isNew: true
                        });
                        transcribeAudio(audioBlob, imageBlob, uiRefs);
                    });
                }

                isRecording = false;
                isRecalling = false;
                statusIndicator.classList.remove('active');
                statusIndicator.querySelector('span').innerText = "Recording...";
                // Stop camera and hide preview (only used for Record)
                if (streamReference) {
                    streamReference.getTracks().forEach(t => t.stop());
                    streamReference = null;
                }
                cameraPreview.srcObject = null;
                cameraPreview.classList.remove('active');
            };
        } catch (err) {
            console.error('Error creating MediaRecorder:', err);
        }
    }

    function captureImage(callback) {
        if (!streamReference) { callback(null); return; }
        const videoTrack = streamReference.getVideoTracks()[0];
        if (!videoTrack || videoTrack.readyState !== 'live') { callback(null); return; }

        snapshotCanvas.width = cameraPreview.videoWidth || 640;
        snapshotCanvas.height = cameraPreview.videoHeight || 480;

        const ctx = snapshotCanvas.getContext('2d');
        ctx.drawImage(cameraPreview, 0, 0, snapshotCanvas.width, snapshotCanvas.height);

        snapshotCanvas.toBlob((blob) => { callback(blob); }, 'image/jpeg', 0.8);
    }

    // --- Memory Management ---

    async function loadMemories(isInitial = false) {
        if (isLoadingMemories) return;
        isLoadingMemories = true;

        // Show Syncing Indicator
        const syncIndicator = document.createElement('div');
        syncIndicator.className = 'sync-indicator';
        syncIndicator.innerText = isInitial ? "Syncing memories..." : "Loading older memories...";
        if (isInitial) {
            chatContainer.appendChild(syncIndicator);
        } else {
            chatContainer.insertBefore(syncIndicator, chatContainer.firstChild);
        }

        try {
            const cacheBust = isInitial ? '&_=' + Date.now() : '';
            const backendUrl = getBackendUrl(`/memories?limit=${LIMIT}&offset=${currentOffset}${cacheBust}`);
            const response = await fetch(backendUrl);
            if (!response.ok) throw new Error('Failed to load memories');
            const data = await response.json();
            const memories = Array.isArray(data) ? data : [];

            if (memories.length < LIMIT) {
                allLoaded = true;
            }

            // Remove sync indicator
            syncIndicator.remove();

            if (isInitial) {
                // Reverse to show oldest -> newest at bottom
                memories.slice().reverse().forEach(mem => {
                    const el = createMemoryElement(mem);
                    chatContainer.appendChild(el);
                });
                chatContainer.scrollTop = chatContainer.scrollHeight;
            } else {
                // Insert older memories at top
                const fragment = document.createDocumentFragment();
                memories.slice().reverse().forEach(mem => {
                    const el = createMemoryElement(mem);
                    fragment.appendChild(el);
                });
                chatContainer.insertBefore(fragment, chatContainer.firstChild);
            }

            currentOffset += memories.length;

        } catch (err) {
            console.error("Failed to load memories", err);
            syncIndicator.innerText = "Failed to sync.";
            setTimeout(() => syncIndicator.remove(), 2000);
        } finally {
            isLoadingMemories = false;
        }
    }

    function createMemoryElement(mem) {
        // mem has: id, text, image_path, audio_path, timestamp
        const messageDiv = document.createElement('div');
        messageDiv.className = 'message-bubble';
        messageDiv.id = `memory-${mem.id}`;

        // Image
        if (mem.image_path) {
            const img = document.createElement('img');
            img.src = getBackendUrl(mem.image_path);
            img.className = 'message-image';
            messageDiv.appendChild(img);
        }

        // Audio (if available) or just Text
        if (mem.audio_path) {
            const audio = document.createElement('audio');
            audio.src = getBackendUrl(mem.audio_path);
            audio.controls = true;
            messageDiv.appendChild(audio);
        }

        // Meta
        const metaDiv = document.createElement('div');
        metaDiv.className = 'message-meta';
        
        const dateStr = mem.timestamp ? (new Date(mem.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) || '--:--') : '--:--';
        const timeSpan = document.createElement('span');
        timeSpan.className = 'timestamp';
        timeSpan.innerText = dateStr;

        const statusIcon = document.createElement('div');
        statusIcon.className = 'status-icon status-done'; // Stored memories are done
        statusIcon.title = "Stored";

        const toggleBtn = document.createElement('button');
        toggleBtn.className = 'transcription-toggle';
        toggleBtn.innerText = 'Aa';
        toggleBtn.style.display = 'inline-block'; // Always show for stored
        
        metaDiv.appendChild(timeSpan);
        metaDiv.appendChild(statusIcon);
        metaDiv.appendChild(toggleBtn);

        // Text Box
        const transcriptionBox = document.createElement('div');
        transcriptionBox.className = 'transcription-box';
        transcriptionBox.innerText = mem.text || "(No text)";
        
        toggleBtn.addEventListener('click', () => {
            transcriptionBox.classList.toggle('visible');
        });

        messageDiv.appendChild(metaDiv);
        messageDiv.appendChild(transcriptionBox);

        // Long Press Delete
        addLongPressListener(messageDiv, mem.id);

        return messageDiv;
    }

    function addMemoryBubble({audioBlob, imageBlob, isNew}) {
        // Similar to createMemoryElement but for NEW in-flight memories
        const audioUrl = URL.createObjectURL(audioBlob);
        const audio = document.createElement('audio');
        audio.src = audioUrl;
        audio.controls = true;

        const messageDiv = document.createElement('div');
        messageDiv.className = 'message-bubble';
        
        if (imageBlob) {
            const imageUrl = URL.createObjectURL(imageBlob);
            const img = document.createElement('img');
            img.src = imageUrl;
            img.className = 'message-image';
            messageDiv.appendChild(img);
        }
        
        messageDiv.appendChild(audio);

        // Meta
        const metaDiv = document.createElement('div');
        metaDiv.className = 'message-meta';
        
        const time = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
        const timeSpan = document.createElement('span');
        timeSpan.className = 'timestamp';
        timeSpan.innerText = time;

        const statusIcon = document.createElement('div');
        statusIcon.className = 'status-icon status-pending';

        const toggleBtn = document.createElement('button');
        toggleBtn.className = 'transcription-toggle';
        toggleBtn.innerText = 'Aa';
        
        metaDiv.appendChild(timeSpan);
        metaDiv.appendChild(statusIcon);
        metaDiv.appendChild(toggleBtn);

        const transcriptionBox = document.createElement('div');
        transcriptionBox.className = 'transcription-box';

        toggleBtn.addEventListener('click', () => { transcriptionBox.classList.toggle('visible'); });

        messageDiv.appendChild(metaDiv);
        messageDiv.appendChild(transcriptionBox);

        chatContainer.appendChild(messageDiv);
        chatContainer.scrollTop = chatContainer.scrollHeight;
        
        return { statusElement: statusIcon, textElement: transcriptionBox, toggleButton: toggleBtn };
    }

    function addLongPressListener(element, id) {
        let pressTimer;
        
        const start = (e) => {
            pressTimer = setTimeout(() => {
                if (confirm("Delete this memory?")) {
                    deleteMemory(id, element);
                }
            }, 800); // 800ms long press
        };

        const cancel = (e) => {
            clearTimeout(pressTimer);
        };

        // Handle context menu specifically
        element.addEventListener('contextmenu', (e) => {
            e.preventDefault();
            return false;
        });

        element.addEventListener('mousedown', start);
        element.addEventListener('touchstart', start);
        element.addEventListener('mouseup', cancel);
        element.addEventListener('mouseleave', cancel);
        element.addEventListener('touchend', cancel);
        element.addEventListener('touchcancel', cancel);
    }

    async function deleteMemory(id, element) {
        try {
            const backendUrl = getBackendUrl(`/memories/${id}`);
            const response = await fetch(backendUrl, { method: 'DELETE' });
            if (response.ok) {
                element.style.opacity = '0';
                setTimeout(() => element.remove(), 300);
            } else {
                alert("Failed to delete memory.");
            }
        } catch (err) {
            console.error("Delete failed", err);
        }
    }

    // --- Core Actions ---

    function startRecording() {
        if (isRecording || isRecalling) return;
        isRecalling = false;
        const btn = document.getElementById('recordBtn');
        if (btn) btn.classList.add('recording');
        const placeholder = document.querySelector('.placeholder-text');
        if (placeholder) placeholder.style.display = 'none';

        navigator.mediaDevices.getUserMedia({
            audio: true,
            video: { facingMode: 'environment', width: { ideal: 640 }, height: { ideal: 480 } }
        }).then(stream => {
            if (!btn || !btn.classList.contains('recording')) {
                stream.getTracks().forEach(t => t.stop());
                return;
            }
            streamReference = stream;
            cameraPreview.srcObject = stream;
            cameraPreview.play().catch(e => console.error('Video play error:', e));
            cameraPreview.classList.add('active');
            initializeRecorder(stream);
            mediaRecorder.start();
            isRecording = true;
            statusIndicator.querySelector('span').innerText = 'Recording Memory...';
            statusIndicator.classList.add('active');
        }).catch(err => {
            console.error('Permission error:', err);
            if (btn) btn.classList.remove('recording');
            if (placeholder) placeholder.style.display = '';
            alert('Microphone and Camera permissions are required to record.');
        });
    }

    function startRecalling() {
        if (isRecording || isRecalling) return;
        isRecalling = true;
        const btn = document.getElementById('recallBtn');
        if (btn) btn.classList.add('recording');
        const placeholder = document.querySelector('.placeholder-text');
        if (placeholder) placeholder.style.display = 'none';

        function startWithStream(stream) {
            audioOnlyStream = stream;
            initializeRecorder(stream);
            mediaRecorder.start();
            isRecording = true;
            statusIndicator.querySelector('span').innerText = 'Listening for Query...';
            statusIndicator.classList.add('active');
        }

        if (audioOnlyStream && audioOnlyStream.active) {
            startWithStream(audioOnlyStream);
            return;
        }
        const recallBtnEl = document.getElementById('recallBtn');
        navigator.mediaDevices.getUserMedia({ audio: true }).then(stream => {
            if (!recallBtnEl || !recallBtnEl.classList.contains('recording')) {
                stream.getTracks().forEach(t => t.stop());
                return;
            }
            startWithStream(stream);
        }).catch(err => {
            console.error('Permission error:', err);
            if (btn) btn.classList.remove('recording');
            if (placeholder) placeholder.style.display = '';
            isRecalling = false;
            alert('Microphone permission is required to recall.');
        });
    }

    function stopRecording() {
        if (mediaRecorder && mediaRecorder.state === 'recording') {
            mediaRecorder.stop();
            const recordBtn = document.getElementById('recordBtn');
            if(recordBtn) recordBtn.classList.remove('recording');
            const recallBtn = document.getElementById('recallBtn');
            if(recallBtn) recallBtn.classList.remove('recording');
        }
    }

    function addSystemMessage(text, memories = []) {
        const messageDiv = document.createElement('div');
        messageDiv.className = 'message-bubble system-message';
        
        const headerDiv = document.createElement('div');
        headerDiv.className = 'system-message-header';
        headerDiv.innerHTML = '<span>🤖 AI Recall</span>';
        messageDiv.appendChild(headerDiv);

        const textDiv = document.createElement('div');
        textDiv.className = 'system-message-text';
        textDiv.innerText = text;
        messageDiv.appendChild(textDiv);

        if (memories && memories.length > 0) {
            const topMemory = memories[0];
            const replyCard = document.createElement('div');
            replyCard.className = 'memory-reply-card';
            replyCard.onclick = () => {
                const targetId = `memory-${topMemory.id}`;
                const targetElement = document.getElementById(targetId);
                if (targetElement) {
                    targetElement.scrollIntoView({ behavior: 'smooth', block: 'center' });
                    targetElement.classList.add('highlight-memory');
                    setTimeout(() => targetElement.classList.remove('highlight-memory'), 2000);
                } else {
                     // If we lazy load, it might be hidden. 
                     // Ideally we should fetch it if missing. For now, simple alert.
                     alert("Memory might be in older history. Scroll up to load it.");
                }
            };

            const bar = document.createElement('div');
            bar.className = 'reply-bar';
            replyCard.appendChild(bar);

            const contentDiv = document.createElement('div');
            contentDiv.className = 'reply-content';

            const metaTitle = document.createElement('div');
            metaTitle.className = 'reply-title';
            const date = new Date(topMemory.timestamp).toLocaleString();
            metaTitle.innerText = `Memory from ${date}`;
            contentDiv.appendChild(metaTitle);

            const snippet = document.createElement('div');
            snippet.className = 'reply-text';
            snippet.innerText = topMemory.text;
            contentDiv.appendChild(snippet);
            replyCard.appendChild(contentDiv);

            if (topMemory.image_path) {
                const img = document.createElement('img');
                const backendUrl = getBackendUrl('');
                img.src = backendUrl + topMemory.image_path;
                img.className = 'reply-thumbnail';
                replyCard.appendChild(img);
            }
            messageDiv.appendChild(replyCard);
            
            if (memories.length > 1) {
                const moreContextBtn = document.createElement('button');
                moreContextBtn.className = 'show-more-context-btn';
                moreContextBtn.innerText = `Show ${memories.length - 1} more sources`;
                
                const otherMemoriesDiv = document.createElement('div');
                otherMemoriesDiv.className = 'other-memories-list';
                otherMemoriesDiv.style.display = 'none';

                memories.slice(1).forEach(mem => {
                   const item = document.createElement('div');
                   item.className = 'other-memory-item';
                   item.innerText = `• ${new Date(mem.timestamp).toLocaleTimeString()}: ${mem.text.substring(0, 50)}...`;
                   otherMemoriesDiv.appendChild(item);
                });

                moreContextBtn.onclick = () => {
                    const isHidden = otherMemoriesDiv.style.display === 'none';
                    otherMemoriesDiv.style.display = isHidden ? 'block' : 'none';
                    moreContextBtn.innerText = isHidden ? 'Hide extra sources' : `Show ${memories.length - 1} more sources`;
                };
                
                messageDiv.appendChild(moreContextBtn);
                messageDiv.appendChild(otherMemoriesDiv);
            }
        }
        chatContainer.appendChild(messageDiv);
        chatContainer.scrollTop = chatContainer.scrollHeight;
    }

    async function transcribeAudio(audioBlob, imageBlob, uiRefs) {
        const { statusElement, textElement, toggleButton } = uiRefs;
        const formData = new FormData();
        formData.append('audio', audioBlob, 'recording.webm');
        if (imageBlob) formData.append('image', imageBlob, 'snapshot.jpg');

        try {
            const backendUrl = getBackendUrl('/transcribe');
            const response = await fetch(backendUrl, { method: 'POST', body: formData });
            if (!response.ok) throw new Error(`Server error: ${response.status}`);
            const data = await response.json();
            
            statusElement.className = 'status-icon status-done';
            statusElement.title = "Transcribed & Saved";
            
            if (data.text) {
                textElement.innerText = data.text;
                toggleButton.style.display = 'inline-block';
            } else {
                textElement.innerText = "(No speech detected)";
                toggleButton.style.display = 'inline-block';
            }
            
            if (data.memory_id) {
                const bubble = statusElement.closest('.message-bubble');
                if (bubble) {
                    bubble.id = `memory-${data.memory_id}`;
                    // Add listener to the NEW bubble
                    addLongPressListener(bubble, data.memory_id);
                }
            }

        } catch (error) {
            console.error('Transcription failed:', error);
            statusElement.className = 'status-icon';
            statusElement.style.color = 'red';
            statusElement.innerText = '!';
        }
    }

    async function handleRecall(audioBlob) {
        const loadingDiv = document.createElement('div');
        loadingDiv.className = 'message-bubble system-message';
        loadingDiv.innerText = "🤔 Thinking...";
        chatContainer.appendChild(loadingDiv);
        chatContainer.scrollTop = chatContainer.scrollHeight;

        const formData = new FormData();
        formData.append('audio', audioBlob, 'query.webm');

        try {
            const backendUrl = getBackendUrl('/recall');
            const response = await fetch(backendUrl, { method: 'POST', body: formData });
            chatContainer.removeChild(loadingDiv);
            if (!response.ok) throw new Error(`Server error: ${response.status}`);
            const data = await response.json();
            addSystemMessage(data.answer, data.memories);
        } catch (error) {
            if(loadingDiv.parentNode) chatContainer.removeChild(loadingDiv);
            console.error('Recall failed:', error);
            addSystemMessage("❌ Error retrieving memory: " + error.message);
        }
    }

    function getBackendUrl(endpoint) {
        const hostname = window.location.hostname;
        const protocol = window.location.protocol === 'https:' ? 'https:' : 'http:';
        const baseUrl =
            (hostname === 'localhost' || hostname === '127.0.0.1')
                ? `${protocol}//localhost:5000`
                : `${protocol}//${hostname}:5000`;
        return baseUrl + endpoint;
    }

    // --- Listeners ---
    const recordBtn = document.getElementById('recordBtn');
    const recallBtn = document.getElementById('recallBtn');
    
    if (recordBtn) {
        recordBtn.addEventListener('touchstart', (e) => { e.preventDefault(); startRecording(); });
        recordBtn.addEventListener('touchend', (e) => { e.preventDefault(); stopRecording(); });
        recordBtn.addEventListener('mousedown', startRecording);
        recordBtn.addEventListener('mouseup', stopRecording);
        recordBtn.addEventListener('mouseleave', () => { if (isRecording && !isRecalling) stopRecording(); });
    }

    if (recallBtn) {
        recallBtn.addEventListener('touchstart', (e) => { e.preventDefault(); startRecalling(); });
        recallBtn.addEventListener('touchend', (e) => { e.preventDefault(); stopRecording(); });
        recallBtn.addEventListener('mousedown', startRecalling);
        recallBtn.addEventListener('mouseup', stopRecording);
        recallBtn.addEventListener('mouseleave', () => { if (isRecording && isRecalling) stopRecording(); });
    }

    const refreshBtn = document.getElementById('refreshMemoriesBtn');
    if (refreshBtn) refreshBtn.addEventListener('click', () => refreshMemories());

    document.addEventListener('keydown', (event) => {
        if (event.code === 'Space') { event.preventDefault(); if (!event.repeat && !isRecording) startRecording(); }
    });
    document.addEventListener('keyup', (event) => {
        if (event.code === 'Space' && isRecording) { event.preventDefault(); stopRecording(); }
    });
});
