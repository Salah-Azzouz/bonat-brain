// Chat functionality for Bonat AI Agent with Authentication

document.addEventListener('DOMContentLoaded', function() {
    const chatForm = document.getElementById('chat-form');
    const userInput = document.getElementById('user-input');
    const chatMessages = document.getElementById('chat-messages');
    const loading = document.getElementById('typing-indicator');
    
    // Store comments in localStorage (must be before functions that use it)
    let messageComments = JSON.parse(localStorage.getItem('messageComments') || '{}');
    
    // Check if user is authenticated
    // Using let so token can be updated when merchant is switched
    let token = localStorage.getItem('access_token');
    let user = JSON.parse(localStorage.getItem('user') || '{}');
    
    if (!token) {
        // Redirect to login if not authenticated
        window.location.href = '/login';
        return;
    }
    
    // Store conversation state
    let currentConversationId = null;
    let conversationHistory = [];

    // Abort controller for canceling streaming requests
    let currentAbortController = null;

    // Language state — default Arabic
    let currentLanguage = localStorage.getItem('preferred_language') || 'ar';

    // Language toggle button
    const langToggle = document.getElementById('lang-toggle');
    if (langToggle) {
        updateLangButton();
        langToggle.addEventListener('click', async function() {
            currentLanguage = currentLanguage === 'ar' ? 'en' : 'ar';
            localStorage.setItem('preferred_language', currentLanguage);
            updateLangButton();
            updateWelcomeText();
            // Persist to backend
            try {
                await fetch('/api/user/preferences', {
                    method: 'PATCH',
                    headers: {
                        'Content-Type': 'application/json',
                        'Authorization': `Bearer ${token}`
                    },
                    body: JSON.stringify({ preferred_language: currentLanguage })
                });
            } catch (e) {
                console.error('Failed to save language preference:', e);
            }
        });
    }

    function updateLangButton() {
        if (!langToggle) return;
        if (currentLanguage === 'ar') {
            langToggle.textContent = 'عربي';
            langToggle.classList.add('active-ar');
        } else {
            langToggle.textContent = 'EN';
            langToggle.classList.remove('active-ar');
        }
    }

    function updateWelcomeText() {
        const el = document.getElementById('welcome-text');
        if (!el) return;
        if (currentLanguage === 'ar') {
            el.innerHTML = 'مرحباً! أنا محلل بياناتك الذكي.<br>اسألني أي شيء وراح أجيب لك التحليلات.';
        } else {
            el.innerHTML = 'Hello! I\'m your AI data analyst.<br>Ask anything I\'ll get your insights.';
        }
    }

    // Load user info in header
    displayUserInfo();

    // Initialize merchant selector
    initializeMerchantSelector();

    // Load language preference from backend, then initialize chat
    (async function initializeChat() {
        try {
            const prefResp = await fetch('/api/user/preferences', {
                headers: { 'Authorization': `Bearer ${token}` }
            });
            if (prefResp.ok) {
                const prefs = await prefResp.json();
                currentLanguage = prefs.preferred_language || 'ar';
                localStorage.setItem('preferred_language', currentLanguage);
                updateLangButton();
                updateWelcomeText();
            }
        } catch (e) {
            console.warn('Could not load language preference:', e);
        }

        const hasHistory = await loadChatHistory();

        // Only check for proactive insights if there's no history loaded
        // (insights are shown at start of day, so if we have history, we've already seen them)
        if (!hasHistory) {
            checkForProactiveInsights();
        }
    })();

    // Handle form submission
    chatForm.addEventListener('submit', async function(e) {
        e.preventDefault();
        
        const userQuery = userInput.value.trim();
        if (!userQuery) return;
        
        // Add user message to chat
        addMessage(userQuery, 'user');
        
        // Clear input
        userInput.value = '';
        
        // Smooth scroll to bottom immediately
        chatMessages.scrollTo({
            top: chatMessages.scrollHeight,
            behavior: 'smooth'
        });
        
        // Show loading
        if (loading) {
            loading.classList.add('active');
        }

        try {
            // Always use streaming
            await handleStreamingRequest(userQuery);

        } catch (error) {
            console.error('Chat error:', error);
            addMessage('Sorry, there was an error processing your request. Please try again.', 'ai');
        } finally {
            // Hide loading
            if (loading) {
                loading.classList.remove('active');
            }
        }
    });
    
    // Add message to chat with improved formatting
    function addMessage(content, sender) {
        const messageDiv = document.createElement('div');
        messageDiv.className = `message ${sender}-message`;
        
        // Add unique message ID
        const messageId = 'msg_' + Date.now() + '_' + Math.random().toString(36).substr(2, 9);
        messageDiv.dataset.messageId = messageId;
        
        const messageContent = document.createElement('div');
        messageContent.className = 'message-content';
        
        if (sender === 'ai') {
            // Format AI response for better readability
            messageContent.innerHTML = formatAIResponse(content);
        } else {
            messageContent.textContent = content;
        }
        
        const messageInfo = document.createElement('small');
        messageInfo.textContent = sender === 'user' ? 'You' : 'AI Assistant';
        
        messageDiv.appendChild(messageContent);
        messageDiv.appendChild(messageInfo);
        
        // Add comment button for AI messages
        if (sender === 'ai') {
            addCommentButton(messageDiv, messageId);
        }
        
        // Remove welcome message if it's the first user message
        if (sender === 'user' && conversationHistory.length === 0) {
            const welcomeMessage = document.querySelector('.welcome-message');
            if (welcomeMessage) {
                welcomeMessage.remove();
            }
        }
        
        chatMessages.appendChild(messageDiv);
        
        // Smooth scroll to bottom
        setTimeout(() => {
            chatMessages.scrollTo({
                top: chatMessages.scrollHeight,
                behavior: 'smooth'
            });
        }, 100);
    }
    
    // Format AI response for better aesthetics
    function formatAIResponse(text) {
        // Parse and convert markdown tables to HTML
        text = parseMarkdownTables(text);

        // FIRST: Detect tip sections (Something to consider, etc.) - these get special styling
        // Must be done BEFORE regular headers so they get wrapped in tip box
        const tipHeaders = [
            'something to consider', 'recommendation', 'quick thought', 'tip',
            'key takeaway', 'next steps', 'want to explore more\\?', 'explore further'
        ];

        // Match tip header and everything after it until end of text
        tipHeaders.forEach(header => {
            const regex = new RegExp(`\\*\\*(${header})\\*\\*([\\s\\S]*?)$`, 'gi');
            text = text.replace(regex, '{{TIP_SECTION_START}}{{TIP_HEADER:$1}}$2{{TIP_SECTION_END}}');
        });

        // Known section header names (case insensitive)
        const sectionHeaders = [
            'monthly overview', 'traffic', 'customer activity', 'sales', 'sales & revenue',
            'loyalty', 'loyalty program', 'revenue', 'orders', 'visits',
            'this week\'s activity', 'weekly overview', 'overview'
        ];

        // Detect section headers by known names (handles cases where they're not on their own line)
        sectionHeaders.forEach(header => {
            const regex = new RegExp(`\\*\\*(${header})\\*\\*`, 'gi');
            text = text.replace(regex, '{{SECTION_HEADER:$1}}');
        });

        // Also detect any bold text on its own line as a section header
        text = text.replace(/^\*\*([^*]+)\*\*$/gm, '{{SECTION_HEADER:$1}}');

        // Replace markdown-style formatting with HTML
        let formatted = text
            // Bold text
            .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
            // Italic text
            .replace(/\*(.*?)\*/g, '<em>$1</em>')
            // Headers (order matters - h4 first, then h3, h2, h1)
            .replace(/^#### (.*$)/gm, '<h5>$1</h5>')
            .replace(/^### (.*$)/gm, '<h4>$1</h4>')
            .replace(/^## (.*$)/gm, '<h3>$1</h3>')
            .replace(/^# (.*$)/gm, '<h2 class="insights-title">$1</h2>')
            // Lists - but handle single items differently
            .replace(/^- (.*$)/gm, '<li>$1</li>')
            // Convert lists to proper HTML
            .replace(/(<li>.*<\/li>)/s, '<ul>$1</ul>')
            // Remove multiple consecutive line breaks (3+ newlines become 2)
            .replace(/\n{3,}/g, '\n\n')
            // Line breaks (single \n becomes <br>)
            .replace(/\n/g, '<br>');

        // Remove single-item bullet lists - convert back to plain text
        formatted = formatted.replace(/<ul>\s*<li>(.*?)<\/li>\s*<\/ul>/g, '$1');

        // Convert section header placeholders to styled HTML
        formatted = formatted.replace(/\{\{SECTION_HEADER:([^}]+)\}\}/g,
            '<div class="insight-section-header">$1</div>');

        // Convert tip header placeholder to styled HTML (inside tip box)
        formatted = formatted.replace(/\{\{TIP_HEADER:([^}]+)\}\}/g,
            '<div class="insight-tip-header">$1</div>');

        // Convert tip section placeholders to styled HTML
        formatted = formatted.replace(/\{\{TIP_SECTION_START\}\}/g, '<div class="insight-tip">');
        formatted = formatted.replace(/\{\{TIP_SECTION_END\}\}/g, '</div>');

        // Clean up any stray <br> at start of tip section or after tip header
        formatted = formatted.replace(/<div class="insight-tip"><br>/g, '<div class="insight-tip">');
        formatted = formatted.replace(/<div class="insight-tip-header">([^<]+)<\/div><br>/g,
            '<div class="insight-tip-header">$1</div>');

        return formatted;
    }

    /**
     * Parse markdown tables and convert to HTML with progressive loading
     */
    function parseMarkdownTables(text) {
        // Regex to match markdown tables
        const tableRegex = /(\|[^\n]+\|[\r\n]+\|[-:\s|]+\|[\r\n]+(?:\|[^\n]+\|[\r\n]+)+)/g;

        return text.replace(tableRegex, (match) => {
            const lines = match.trim().split(/[\r\n]+/);

            if (lines.length < 3) return match; // Need at least header, separator, and 1 row

            // Parse header
            const headers = lines[0]
                .split('|')
                .map(h => h.trim())
                .filter(h => h);

            // Parse rows (skip separator line at index 1)
            const rows = [];
            for (let i = 2; i < lines.length; i++) {
                const cells = lines[i]
                    .split('|')
                    .map(c => c.trim())
                    .filter(c => c);

                if (cells.length > 0) {
                    rows.push(cells);
                }
            }

            // Generate HTML table with progressive loading class
            let html = '<div class="data-table-wrapper">';
            html += '<table class="data-table progressive-table">';

            // Table header
            html += '<thead><tr>';
            headers.forEach(header => {
                html += `<th>${header}</th>`;
            });
            html += '</tr></thead>';

            // Table body
            html += '<tbody>';
            rows.forEach((row, idx) => {
                // Add progressive-row class with index for animation delay
                html += `<tr class="progressive-row" data-row-index="${idx}">`;
                row.forEach(cell => {
                    html += `<td>${cell}</td>`;
                });
                html += '</tr>';
            });
            html += '</tbody>';

            html += '</table>';
            html += '</div>';

            return `\n${html}\n`;
        });
    }
    
    // Display user information
    function displayUserInfo() {
        if (user.name) {
            // Add user info to the chat header
            const chatHeader = document.querySelector('.card-header h5');
            if (chatHeader) {
                chatHeader.innerHTML = `
                    <i class="fas fa-comments me-2"></i>
                    Chat with AI Agent
                    <small class="text-muted ms-2">Welcome, ${user.name}!</small>
                `;
            }
        }
    }

    // ═══════════════════════════════════════════════════════════
    // MERCHANT SELECTOR FUNCTIONALITY
    // ═══════════════════════════════════════════════════════════

    /**
     * Initialize the merchant selector dropdown
     * Fetches available merchants from API and populates the dropdown
     */
    async function initializeMerchantSelector() {
        const merchantSelect = document.getElementById('merchant-select');
        if (!merchantSelect) return;

        try {
            // Fetch available merchants from API
            const response = await fetch('/api/merchants', {
                method: 'GET',
                headers: {
                    'Authorization': `Bearer ${token}`,
                    'Content-Type': 'application/json'
                }
            });

            if (!response.ok) {
                console.error('Failed to fetch merchants:', response.status);
                return;
            }

            const data = await response.json();
            console.log('Merchant config loaded:', data);

            // Populate dropdown with options
            merchantSelect.innerHTML = '';
            data.merchants.forEach(merchantId => {
                const option = document.createElement('option');
                option.value = merchantId;
                option.textContent = merchantId;
                if (merchantId === data.default) {
                    option.textContent += ' (default)';
                }
                if (merchantId === data.current) {
                    option.selected = true;
                }
                merchantSelect.appendChild(option);
            });

            // Add change event listener
            merchantSelect.addEventListener('change', handleMerchantChange);

        } catch (error) {
            console.error('Error initializing merchant selector:', error);
        }
    }

    /**
     * Handle merchant selection change
     * Shows confirmation and switches merchant if confirmed
     */
    async function handleMerchantChange(event) {
        const newMerchantId = event.target.value;
        const currentMerchantId = user.merchant_id;

        // If same merchant selected, do nothing
        if (newMerchantId === currentMerchantId) {
            return;
        }

        // Confirm the switch
        const confirmed = confirm(
            `Switch to Merchant ${newMerchantId}?\n\n` +
            `This will:\n` +
            `• Clear your current chat history\n` +
            `• Start a new session with the selected merchant\n\n` +
            `Continue?`
        );

        if (!confirmed) {
            // Reset dropdown to current merchant
            event.target.value = currentMerchantId;
            return;
        }

        // Show loading state
        const merchantSelect = document.getElementById('merchant-select');
        merchantSelect.disabled = true;

        try {
            // Call switch merchant API
            const response = await fetch('/api/switch-merchant', {
                method: 'POST',
                headers: {
                    'Authorization': `Bearer ${token}`,
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({ merchant_id: newMerchantId })
            });

            if (!response.ok) {
                const errorData = await response.json();
                throw new Error(errorData.detail || 'Failed to switch merchant');
            }

            const data = await response.json();
            console.log('Merchant switched successfully:', data);

            // Store new token and user info in localStorage
            localStorage.setItem('access_token', data.access_token);
            localStorage.setItem('user', JSON.stringify(data.user));

            // CRITICAL: Update the local token and user variables so subsequent requests use new merchant
            token = data.access_token;
            user = data.user;

            // Clear chat and reload
            clearChat();

            // Show success message
            addMessage(`✅ Switched to Merchant ${newMerchantId}. You can now ask questions about this merchant's data.`, 'ai');

            // Re-enable dropdown
            merchantSelect.disabled = false;

        } catch (error) {
            console.error('Error switching merchant:', error);
            alert('Failed to switch merchant: ' + error.message);

            // Reset dropdown to current merchant
            event.target.value = currentMerchantId;
            merchantSelect.disabled = false;
        }
    }
    
    // Auto-resize input on focus
    userInput.addEventListener('focus', function() {
        this.style.height = 'auto';
        this.style.height = this.scrollHeight + 'px';
    });
    
    // Handle Enter key in input
    userInput.addEventListener('keydown', function(e) {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            chatForm.dispatchEvent(new Event('submit'));
        }
    });
    
    // Clear chat functionality
    async function clearChat() {
        try {
            // Call API to clear history from MongoDB
            const response = await fetch('/api/chat/history', {
                method: 'DELETE',
                headers: {
                    'Authorization': `Bearer ${token}`,
                    'Content-Type': 'application/json'
                }
            });

            if (!response.ok) {
                console.error('Failed to clear chat history:', response.status);
            } else {
                console.log('Chat history cleared from database');
            }
        } catch (error) {
            console.error('Error clearing chat history:', error);
        }

        // Clear UI regardless of API result
        chatMessages.innerHTML = '';
        conversationHistory = [];
        currentConversationId = null;

        // Add welcome message back
        const welcomeDiv = document.createElement('div');
        welcomeDiv.className = 'welcome-message';
        welcomeDiv.innerHTML = `
            <div class="welcome-icon">
                <i class="fas fa-brain"></i>
            </div>
            <div class="welcome-text" id="welcome-text">
                ${currentLanguage === 'ar'
                    ? 'مرحباً! أنا محلل بياناتك الذكي.<br>اسألني أي شيء وراح أجيب لك التحليلات.'
                    : 'Hello! I\'m your AI data analyst.<br>Ask anything I\'ll get your insights.'}
            </div>
        `;
        chatMessages.appendChild(welcomeDiv);
    }

    // Load chat history from MongoDB on page load
    async function loadChatHistory() {
        try {
            const response = await fetch('/api/chat/history?limit=20', {
                method: 'GET',
                headers: {
                    'Authorization': `Bearer ${token}`,
                    'Content-Type': 'application/json'
                }
            });

            if (!response.ok) {
                console.error('Failed to load chat history:', response.status);
                return false;
            }

            const data = await response.json();
            console.log('Loaded chat history:', data.count, 'messages');

            if (data.messages && data.messages.length > 0) {
                // Remove welcome message since we have history
                const welcomeMessage = document.querySelector('.welcome-message');
                if (welcomeMessage) {
                    welcomeMessage.remove();
                }

                // Add each message to the chat
                for (const msg of data.messages) {
                    // Skip the proactive insights placeholder messages
                    if (msg.user_query === '[First chat of the day - Proactive Insights]') {
                        // Just add the AI response for insights
                        addMessage(msg.ai_response, 'ai');
                    } else {
                        // Add user message
                        addMessage(msg.user_query, 'user');
                        // Add AI response
                        addMessage(msg.ai_response, 'ai');
                    }

                    // Add to conversation history for context
                    conversationHistory.push({
                        user: msg.user_query,
                        ai: msg.ai_response,
                        timestamp: msg.timestamp
                    });
                }

                // Set the conversation ID for continuity
                if (data.conversation_id) {
                    currentConversationId = data.conversation_id;
                }

                return true; // History was loaded
            }

            return false; // No history to load
        } catch (error) {
            console.error('Error loading chat history:', error);
            return false;
        }
    }

    // Logout function
    function logout() {
        localStorage.removeItem('access_token');
        localStorage.removeItem('user');
        window.location.href = '/login';
    }
    
    // Wire up action buttons
    const clearButton = document.querySelector('.btn-clear');
    const logoutButton = document.querySelector('.btn-logout');

    if (clearButton) {
        clearButton.addEventListener('click', clearChat);
    }

    if (logoutButton) {
        logoutButton.addEventListener('click', logout);
    }
    
    // Focus input on page load
    userInput.focus();

    // ═══════════════════════════════════════════════════════════
    // STREAMING FUNCTION (Always Enabled)
    // ═══════════════════════════════════════════════════════════

    /**
     * Handle streaming request using SSE
     */
    async function handleStreamingRequest(userQuery) {
        // Hide loading spinner (we'll show progress tracker instead)
        if (loading) {
            loading.classList.remove('active');
        }

        // Create empty AI message bubble for streaming
        const streamingMessageDiv = createStreamingMessage();

        // Create progress tracker
        const progressTracker = createProgressTracker();
        chatMessages.appendChild(progressTracker);

        // Create cancel button
        const cancelButton = createCancelButton();

        // Create new AbortController for this request
        currentAbortController = new AbortController();

        // Declare fullResponse outside try block so it's accessible in catch
        let fullResponse = '';

        try {
            const response = await fetch('/api/chat/agent/stream', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'Authorization': `Bearer ${token}`
                },
                body: JSON.stringify({
                    user_query: userQuery,
                    conversation_id: currentConversationId,
                    language: currentLanguage
                }),
                signal: currentAbortController.signal  // Add abort signal
            });

            if (!response.ok) {
                if (response.status === 401) {
                    localStorage.removeItem('access_token');
                    localStorage.removeItem('user');
                    window.location.href = '/login';
                    return;
                }
                throw new Error(`HTTP error! status: ${response.status}`);
            }

            // Process the streaming response
            const reader = response.body.getReader();
            const decoder = new TextDecoder();
            let buffer = '';

            while (true) {
                const { done, value } = await reader.read();

                if (done) break;

                // Decode the chunk and add to buffer
                buffer += decoder.decode(value, { stream: true });

                // Process complete SSE messages (format: data: {...}\n\n)
                const lines = buffer.split('\n\n');
                buffer = lines.pop(); // Keep incomplete message in buffer

                for (const line of lines) {
                    if (line.startsWith('data: ')) {
                        const data = line.slice(6); // Remove 'data: ' prefix

                        // Skip keepalive comments
                        if (data.trim().startsWith(':')) continue;

                        try {
                            const event = JSON.parse(data);

                            if (event.type === 'token') {
                                // Append token to message
                                fullResponse += event.content;
                                updateStreamingMessage(streamingMessageDiv, fullResponse);

                            } else if (event.type === 'tool_start') {
                                // Add new stage to progress tracker
                                console.log(`[Progress] Tool started: ${event.tool} - ${event.title}`);
                                addProgressStage(progressTracker, {
                                    tool: event.tool,
                                    icon: event.icon,
                                    title: event.title,
                                    description: event.description
                                });

                            } else if (event.type === 'tool_end') {
                                // Mark stage as completed
                                console.log(`[Progress] Tool completed: ${event.tool}`);
                                completeProgressStage(progressTracker, event.tool);

                            } else if (event.type === 'generating_start') {
                                // Add "Generating Response" stage
                                addProgressStage(progressTracker, {
                                    tool: 'generating',
                                    icon: event.icon,
                                    title: event.title,
                                    description: event.description
                                });

                            } else if (event.type === 'done') {
                                // Stream complete
                                currentConversationId = event.conversation_id;

                                // Mark generating as complete
                                completeProgressStage(progressTracker, 'generating');

                                // Remove progress tracker after a brief delay
                                setTimeout(() => {
                                    removeProgressTracker(progressTracker);
                                }, 1000);

                                // Finalize message
                                finalizeStreamingMessage(streamingMessageDiv, fullResponse);

                                // Add follow-up suggestion chips if provided
                                if (event.suggestions && event.suggestions.length > 0) {
                                    addSuggestionChips(streamingMessageDiv, event.suggestions);
                                }

                                conversationHistory.push({
                                    user: userQuery,
                                    ai: fullResponse,
                                    timestamp: new Date().toISOString()
                                });

                                // Remove cancel button
                                removeCancelButton(cancelButton);

                                console.log('Streaming completed successfully');

                            } else if (event.type === 'error') {
                                // Error occurred
                                removeProgressTracker(progressTracker);
                                removeCancelButton(cancelButton);
                                streamingMessageDiv.remove();
                                addMessage(event.content, 'ai');
                                console.error('Streaming error:', event.content);
                            }

                        } catch (parseError) {
                            console.error('Failed to parse SSE event:', parseError, data);
                        }
                    }
                }
            }

        } catch (error) {
            // Check if it was aborted by user
            if (error.name === 'AbortError') {
                console.log('Streaming canceled by user');
                removeProgressTracker(progressTracker);
                removeCancelButton(cancelButton);

                // Add cancellation message to the streaming bubble
                const messageContent = streamingMessageDiv.querySelector('.message-content');
                if (fullResponse.trim()) {
                    // If we have partial response, show it with cancellation notice
                    messageContent.innerHTML = formatAIResponse(fullResponse) +
                        '<br><em class="text-muted">⚠️ Response generation canceled</em>';
                } else {
                    // No content received, remove the bubble
                    streamingMessageDiv.remove();
                }
                streamingMessageDiv.classList.remove('streaming');

                return; // Don't throw error for user-initiated abort
            }

            // Other errors
            console.error('Streaming error:', error);
            removeProgressTracker(progressTracker);
            removeCancelButton(cancelButton);
            streamingMessageDiv.remove();
            throw error;
        } finally {
            // Clean up abort controller
            currentAbortController = null;
        }
    }

    /**
     * Create an empty streaming message bubble
     */
    function createStreamingMessage() {
        const messageDiv = document.createElement('div');
        messageDiv.className = 'message ai-message streaming';

        // Add unique message ID
        const messageId = 'msg_' + Date.now() + '_' + Math.random().toString(36).substr(2, 9);
        messageDiv.dataset.messageId = messageId;

        const messageContent = document.createElement('div');
        messageContent.className = 'message-content';
        messageContent.innerHTML = '<span class="typing-indicator">●●●</span>';

        const messageInfo = document.createElement('small');
        messageInfo.textContent = 'AI Assistant';

        messageDiv.appendChild(messageContent);
        messageDiv.appendChild(messageInfo);

        chatMessages.appendChild(messageDiv);
        chatMessages.scrollTop = chatMessages.scrollHeight;

        return messageDiv;
    }

    /**
     * Update streaming message with new content
     */
    function updateStreamingMessage(messageDiv, content) {
        const messageContent = messageDiv.querySelector('.message-content');
        messageContent.innerHTML = formatAIResponse(content) + '<span class="cursor-blink">▋</span>';
        chatMessages.scrollTop = chatMessages.scrollHeight;
    }

    /**
     * Finalize streaming message (remove cursor)
     */
    function finalizeStreamingMessage(messageDiv, content) {
        const messageContent = messageDiv.querySelector('.message-content');
        messageContent.innerHTML = formatAIResponse(content);
        messageDiv.classList.remove('streaming');

        // Trigger progressive table loading animation
        triggerProgressiveTableLoading(messageContent);

        // Add comment button
        const messageId = messageDiv.dataset.messageId;
        if (messageId) {
            addCommentButton(messageDiv, messageId);
        }

        chatMessages.scrollTop = chatMessages.scrollHeight;
    }

    /**
     * Trigger progressive loading animation for tables
     */
    function triggerProgressiveTableLoading(container) {
        const tables = container.querySelectorAll('.progressive-table');

        tables.forEach(table => {
            const rows = table.querySelectorAll('.progressive-row');

            rows.forEach((row, index) => {
                // Stagger the animation for each row
                setTimeout(() => {
                    row.classList.add('loaded');
                }, index * 50); // 50ms delay between each row
            });
        });
    }

    /**
     * Add clickable suggestion chips below an AI message
     */
    function addSuggestionChips(messageDiv, suggestions) {
        if (!suggestions || suggestions.length === 0) return;

        // Create suggestions container
        const suggestionsContainer = document.createElement('div');
        suggestionsContainer.className = 'suggestion-chips';

        // Add each suggestion as a clickable chip
        suggestions.forEach(suggestion => {
            const chip = document.createElement('button');
            chip.className = 'suggestion-chip';
            chip.textContent = suggestion;
            chip.title = 'Click to ask this question';

            // Handle click - send this as a new message
            chip.addEventListener('click', () => {
                // Remove all suggestion chips (they're one-time use)
                document.querySelectorAll('.suggestion-chips').forEach(el => el.remove());

                // Set the input value and submit
                userInput.value = suggestion;
                chatForm.dispatchEvent(new Event('submit'));
            });

            suggestionsContainer.appendChild(chip);
        });

        // Append to the message div (after the content)
        messageDiv.appendChild(suggestionsContainer);

        // Scroll to show suggestions
        chatMessages.scrollTop = chatMessages.scrollHeight;
    }

    /**
     * Create progress tracker with pipeline stages
     */
    function createProgressTracker() {
        const trackerDiv = document.createElement('div');
        trackerDiv.className = 'progress-tracker';
        trackerDiv.innerHTML = `
            <div class="progress-stages">
                <!-- Stages will be added dynamically -->
            </div>
        `;
        return trackerDiv;
    }

    /**
     * Add a progress step to the tracker (or reactivate existing)
     */
    function addProgressStage(trackerDiv, stepData) {
        const stepsContainer = trackerDiv.querySelector('.progress-stages');
        const toolName = stepData.tool || 'generating';

        // Safeguard: Ensure title and description have values (fix "undefined" issue)
        const title = stepData.title || 'Processing...';
        const description = stepData.description || 'Working on your request';

        // FIRST: Hide all other active steps to ensure only one shows
        const allSteps = stepsContainer.querySelectorAll('.progress-step');
        allSteps.forEach(step => {
            step.classList.remove('active');
            step.classList.add('completed');
            step.style.display = 'none';
        });

        // Check if this tool already has a step
        let stepDiv = trackerDiv.querySelector(`[data-tool="${toolName}"]`);

        if (stepDiv) {
            // Reactivate existing step
            stepDiv.classList.remove('completed');
            stepDiv.classList.add('active');
            stepDiv.style.display = 'flex';

            // Reset spinner
            const statusIcon = stepDiv.querySelector('.step-status i');
            if (statusIcon) {
                statusIcon.className = 'fas fa-circle-notch fa-spin';
            }
        } else {
            // Create new step (spinner first, text second)
            stepDiv = document.createElement('div');
            stepDiv.className = 'progress-step active';
            stepDiv.dataset.tool = toolName;
            stepDiv.style.display = 'flex';
            stepDiv.innerHTML = `
                <div class="step-status">
                    <i class="fas fa-circle-notch fa-spin"></i>
                </div>
                <div class="step-content">
                    <div class="step-title">${title}</div>
                    <div class="step-description">${description}</div>
                </div>
            `;

            stepsContainer.appendChild(stepDiv);
        }

        // Scroll to bottom to show new step
        trackerDiv.scrollTop = trackerDiv.scrollHeight;

        return stepDiv;
    }

    /**
     * Mark a progress step as completed (hide it since we only show current step)
     */
    function completeProgressStage(trackerDiv, toolName) {
        const step = trackerDiv.querySelector(`[data-tool="${toolName}"]`);
        if (step) {
            step.classList.remove('active');
            step.classList.add('completed');
            step.style.display = 'none'; // Force hide with inline style
        }
    }

    /**
     * Remove progress tracker
     */
    function removeProgressTracker(trackerDiv) {
        if (trackerDiv && trackerDiv.parentNode) {
            trackerDiv.style.opacity = '0';
            trackerDiv.style.transform = 'translateY(-10px)';
            setTimeout(() => {
                trackerDiv.remove();
            }, 300);
        }
    }

    /**
     * Create cancel button for aborting streaming (ChatGPT style)
     */
    function createCancelButton() {
        const cancelBtn = document.createElement('button');
        cancelBtn.type = 'button';
        cancelBtn.className = 'btn btn-stop-icon';
        cancelBtn.innerHTML = '<i class="fas fa-stop"></i>';
        cancelBtn.title = 'Stop generating';

        // Add click handler to abort the stream
        cancelBtn.addEventListener('click', () => {
            if (currentAbortController) {
                currentAbortController.abort();
                cancelBtn.disabled = true;
                cancelBtn.classList.add('stopped');
                cancelBtn.innerHTML = '<i class="fas fa-check"></i>';
            }
        });

        // Replace send button with cancel button
        const sendBtn = document.querySelector('.btn-send');
        const inputForm = document.querySelector('.input-form');

        if (sendBtn) {
            sendBtn.style.display = 'none';
        }

        if (inputForm) {
            inputForm.appendChild(cancelBtn);
        }

        return cancelBtn;
    }

    /**
     * Remove cancel button and restore send button
     */
    function removeCancelButton(cancelBtn) {
        if (cancelBtn && cancelBtn.parentNode) {
            // Fade out animation
            cancelBtn.style.opacity = '0';
            setTimeout(() => {
                cancelBtn.remove();

                // Show send button again
                const sendBtn = document.querySelector('.btn-send');
                if (sendBtn) {
                    sendBtn.style.display = '';
                }
            }, 200);
        }
    }

    // Check for proactive insights on chat initialization
    async function checkForProactiveInsights() {
        try {
            // Check URL for testing parameter
            const urlParams = new URLSearchParams(window.location.search);
            const forceInsights = urlParams.get('test_insights') === 'true';

            // Build URL with optional testing parameter
            let url = '/api/chat/initial';
            if (forceInsights) {
                url += '?force_insights=true';
                console.log('🧪 TESTING MODE: Forcing insights display');
            }

            // Call the initial message endpoint to check if insights should be shown
            const response = await fetch(url, {
                method: 'GET',
                headers: {
                    'Authorization': `Bearer ${token}`,
                    'Content-Type': 'application/json'
                }
            });

            if (!response.ok) {
                console.error('Failed to check for insights:', response.status);
                return;
            }

            const data = await response.json();
            console.log('Initial message check:', data);

            if (data.type === 'proactive_insights' && data.should_stream) {
                // Stream proactive insights as the first message
                await streamProactiveInsights();
            }
            // If type is 'greeting', we don't need to do anything - user can just start chatting

        } catch (error) {
            console.error('Error checking for proactive insights:', error);
            // Silently fail - user can still use chat normally
        }
    }

    // Stream proactive insights on first chat of the day
    async function streamProactiveInsights() {
        try {
            // Remove welcome message if it exists
            const welcomeMessage = document.querySelector('.welcome-message');
            if (welcomeMessage) {
                welcomeMessage.remove();
            }

            // Create abort controller for this request
            currentAbortController = new AbortController();

            // Create AI message bubble for streaming (with insights-message class)
            const messageDiv = document.createElement('div');
            messageDiv.className = 'message ai-message insights-message streaming';
            messageDiv.innerHTML = `
                <div class="message-content">
                    <div class="progress-tracker">
                        <span class="loading-dots">
                            <span class="dot"></span>
                            <span class="dot"></span>
                            <span class="dot"></span>
                        </span>
                        <span>Analyzing your business data...</span>
                    </div>
                    <div class="response-text"></div>
                </div>
                <small>AI Assistant</small>
            `;
            chatMessages.appendChild(messageDiv);

            const responseText = messageDiv.querySelector('.response-text');
            const progressTracker = messageDiv.querySelector('.progress-tracker');

            // Make streaming request with empty user_query to trigger insights
            const response = await fetch('/api/chat/agent/stream', {
                method: 'POST',
                headers: {
                    'Authorization': `Bearer ${token}`,
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({
                    user_query: '',  // Empty query triggers proactive insights
                    conversation_id: currentConversationId,
                    language: currentLanguage
                }),
                signal: currentAbortController.signal
            });

            if (!response.ok) {
                throw new Error(`HTTP error! status: ${response.status}`);
            }

            // Read the stream
            const reader = response.body.getReader();
            const decoder = new TextDecoder();
            let fullResponse = '';

            while (true) {
                const { value, done } = await reader.read();
                if (done) break;

                const chunk = decoder.decode(value);
                const lines = chunk.split('\n');

                for (const line of lines) {
                    if (line.startsWith('data: ')) {
                        const jsonStr = line.slice(6);
                        try {
                            const event = JSON.parse(jsonStr);

                            if (event.type === 'generating_start') {
                                progressTracker.innerHTML = `
                                    <span class="loading-dots">
                                        <span class="dot"></span>
                                        <span class="dot"></span>
                                        <span class="dot"></span>
                                    </span>
                                    <span>${event.message}</span>
                                `;
                            } else if (event.type === 'token') {
                                fullResponse += event.content;
                                responseText.innerHTML = formatAIResponse(fullResponse);
                                chatMessages.scrollTop = chatMessages.scrollHeight;
                            } else if (event.type === 'done') {
                                // Remove streaming indicator
                                messageDiv.classList.remove('streaming');
                                progressTracker.style.display = 'none';

                                // Store conversation ID
                                if (event.conversation_id) {
                                    currentConversationId = event.conversation_id;
                                }

                                // Format final response
                                responseText.innerHTML = formatAIResponse(fullResponse);

                                // Trigger progressive table loading animation
                                triggerProgressiveTableLoading(responseText);

                                chatMessages.scrollTop = chatMessages.scrollHeight;
                            } else if (event.type === 'error') {
                                console.error('Streaming error:', event.content);
                                progressTracker.innerHTML = `
                                    <span>Unable to load insights</span>
                                `;
                            }
                        } catch (e) {
                            // Skip malformed JSON
                            console.warn('Failed to parse SSE event:', e);
                        }
                    }
                }
            }

            // Clear abort controller
            currentAbortController = null;

        } catch (error) {
            if (error.name === 'AbortError') {
                console.log('Insights stream aborted');
            } else {
                console.error('Error streaming proactive insights:', error);
                // Show error to user instead of silently failing
                const messageDiv = document.querySelector('.insights-message');
                if (messageDiv) {
                    const progressTracker = messageDiv.querySelector('.progress-tracker');
                    const responseText = messageDiv.querySelector('.response-text');
                    if (progressTracker) progressTracker.style.display = 'none';
                    if (responseText) {
                        responseText.innerHTML = `<p class="text-muted">Unable to load insights right now. You can still ask me questions below!</p>`;
                    }
                    messageDiv.classList.remove('streaming');
                }
            }
            currentAbortController = null;
        }
    }

    // ========================================
    // Comment Functionality
    // ========================================

    /**
     * Add comment button to AI message
     */
    function addCommentButton(messageDiv, messageId) {
        // Create actions container
        const actionsDiv = document.createElement('div');
        actionsDiv.className = 'message-actions';

        // Create comment button
        const commentBtn = document.createElement('button');
        commentBtn.className = 'btn-comment';
        commentBtn.innerHTML = '<i class="fas fa-comment"></i> Add Note';
        commentBtn.dataset.messageId = messageId;

        // Check if comment exists
        if (messageComments[messageId]) {
            commentBtn.classList.add('has-comment');
            commentBtn.innerHTML = '<i class="fas fa-comment"></i> Edit Note';
            
            // Show existing comment
            const commentDiv = createCommentDisplay(messageComments[messageId]);
            messageDiv.querySelector('.message-content').appendChild(commentDiv);
        }

        commentBtn.addEventListener('click', function() {
            toggleCommentInput(messageDiv, messageId);
        });

        actionsDiv.appendChild(commentBtn);
        messageDiv.querySelector('.message-content').appendChild(actionsDiv);
    }

    /**
     * Toggle comment input
     */
    function toggleCommentInput(messageDiv, messageId) {
        const messageContent = messageDiv.querySelector('.message-content');
        let inputContainer = messageContent.querySelector('.comment-input-container');

        if (inputContainer) {
            inputContainer.remove();
            return;
        }

        // Remove any existing comment display
        const existingComment = messageContent.querySelector('.message-comment');
        if (existingComment) {
            existingComment.remove();
        }

        // Create input container
        inputContainer = document.createElement('div');
        inputContainer.className = 'comment-input-container';

        const textarea = document.createElement('textarea');
        textarea.className = 'comment-input';
        textarea.placeholder = 'Add your note here...';
        textarea.value = messageComments[messageId] || '';

        const actionsDiv = document.createElement('div');
        actionsDiv.className = 'comment-actions';

        const saveBtn = document.createElement('button');
        saveBtn.className = 'btn-save-comment';
        saveBtn.innerHTML = '<i class="fas fa-save"></i> Save';
        saveBtn.addEventListener('click', function() {
            saveComment(messageDiv, messageId, textarea.value);
        });

        const cancelBtn = document.createElement('button');
        cancelBtn.className = 'btn-cancel-comment';
        cancelBtn.innerHTML = '<i class="fas fa-times"></i> Cancel';
        cancelBtn.addEventListener('click', function() {
            inputContainer.remove();
            // Restore comment display if it existed
            if (messageComments[messageId]) {
                const commentDiv = createCommentDisplay(messageComments[messageId]);
                messageContent.appendChild(commentDiv);
            }
        });

        actionsDiv.appendChild(saveBtn);
        actionsDiv.appendChild(cancelBtn);

        inputContainer.appendChild(textarea);
        inputContainer.appendChild(actionsDiv);

        messageContent.appendChild(inputContainer);
        textarea.focus();
    }

    /**
     * Save comment
     */
    function saveComment(messageDiv, messageId, comment) {
        const messageContent = messageDiv.querySelector('.message-content');
        const inputContainer = messageContent.querySelector('.comment-input-container');
        const commentBtn = messageContent.querySelector('.btn-comment');

        if (comment.trim()) {
            // Save to storage
            messageComments[messageId] = comment.trim();
            localStorage.setItem('messageComments', JSON.stringify(messageComments));

            // Update button
            commentBtn.classList.add('has-comment');
            commentBtn.innerHTML = '<i class="fas fa-comment"></i> Edit Note';

            // Remove input, show comment
            inputContainer.remove();
            const commentDiv = createCommentDisplay(comment.trim());
            messageContent.appendChild(commentDiv);
        } else {
            // Delete comment if empty
            delete messageComments[messageId];
            localStorage.setItem('messageComments', JSON.stringify(messageComments));

            commentBtn.classList.remove('has-comment');
            commentBtn.innerHTML = '<i class="fas fa-comment"></i> Add Note';

            inputContainer.remove();
        }
    }

    /**
     * Create comment display
     */
    function createCommentDisplay(comment) {
        const commentDiv = document.createElement('div');
        commentDiv.className = 'message-comment';

        const headerDiv = document.createElement('div');
        headerDiv.className = 'comment-header';
        headerDiv.innerHTML = '<i class="fas fa-sticky-note"></i> Your Note:';

        const textDiv = document.createElement('div');
        textDiv.textContent = comment;

        commentDiv.appendChild(headerDiv);
        commentDiv.appendChild(textDiv);

        return commentDiv;
    }

    // ========================================
    // PDF Export Functionality
    // ========================================

    const exportPdfBtn = document.getElementById('export-pdf');
    if (exportPdfBtn) {
        exportPdfBtn.addEventListener('click', function(e) {
            e.preventDefault();
            // Open browser print dialog (user can save as PDF)
            window.print();
        });
    }


});
