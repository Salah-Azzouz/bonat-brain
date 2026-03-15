import logging
import uvicorn
import sys
import os
import signal
import traceback
import psutil
from fastapi import FastAPI, HTTPException, Request, Depends, status, BackgroundTasks
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from datetime import datetime, timezone
import uuid
import json
import asyncio
from agent.auth import (
    auth_service,
    UserRegistration,
    UserLogin,
    UserResponse,
    TokenResponse,
    ChatRequest,
    ChatResponse,
    SwitchMerchantRequest,
    UserPreferencesUpdate,
)
from agent.config import get_mongodb_collections, get_db_connection, get_mongodb_client, ALLOWED_MERCHANTS, DEFAULT_MERCHANT, set_callbacks, clear_callbacks
from agent.utils.cost_tracker import CostTrackingCallback

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# ============================================
# CRASH DIAGNOSTICS - Signal handlers & memory tracking
# ============================================

def get_memory_usage():
    """Get current memory usage in MB."""
    try:
        process = psutil.Process(os.getpid())
        memory_mb = process.memory_info().rss / 1024 / 1024
        return f"{memory_mb:.1f}MB"
    except Exception as e:
        return f"unknown ({e})"

def log_system_state(context: str):
    """Log current system state for debugging."""
    try:
        process = psutil.Process(os.getpid())
        memory = process.memory_info()
        cpu = process.cpu_percent()
        threads = process.num_threads()

        logger.warning(f"[DIAGNOSTICS] {context}")
        logger.warning(f"  Memory: RSS={memory.rss/1024/1024:.1f}MB, VMS={memory.vms/1024/1024:.1f}MB")
        logger.warning(f"  CPU: {cpu}%, Threads: {threads}")
        logger.warning(f"  Open files: {len(process.open_files())}")
    except Exception as e:
        logger.warning(f"[DIAGNOSTICS] {context} - Failed to get stats: {e}")

def signal_handler(signum, frame):
    """Handle shutdown signals with detailed logging."""
    signal_name = signal.Signals(signum).name
    logger.critical(f"[SHUTDOWN] Received signal: {signal_name} (signum={signum})")
    log_system_state(f"State at {signal_name}")

    # Log the stack trace to see what was running
    logger.critical("[SHUTDOWN] Stack trace at signal:")
    for line in traceback.format_stack(frame):
        for subline in line.strip().split('\n'):
            logger.critical(f"  {subline}")

    # Exit gracefully
    logger.critical("[SHUTDOWN] Exiting due to signal...")
    sys.exit(0)

# Register signal handlers
signal.signal(signal.SIGTERM, signal_handler)
signal.signal(signal.SIGINT, signal_handler)

# Log startup
logger.info(f"[STARTUP] Application starting, PID={os.getpid()}, Memory={get_memory_usage()}")

class HealthCheckFilter(logging.Filter):
    """Filter out health check endpoint logs"""
    def filter(self, record: logging.LogRecord) -> bool:
        return record.getMessage().find("/health") == -1

# Apply filter to uvicorn access logger
logging.getLogger("uvicorn.access").addFilter(HealthCheckFilter())

app = FastAPI(title="Bonat AI Agent API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory="web/static"), name="static")
templates = Jinja2Templates(directory="web/templates")
security = HTTPBearer()

async def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)) -> UserResponse:
    user = auth_service.get_current_user(credentials.credentials)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user

@app.get("/health")
async def health_check():
    """Health check endpoint that verifies database connectivity"""
    health_status = {
        "status": "healthy",
        "services": {
            "mysql": "unknown",
            "mongodb": "unknown"
        }
    }
    
    # Check MySQL connectivity
    try:
        mysql_conn = get_db_connection()
        if mysql_conn:
            mysql_conn.close()
            health_status["services"]["mysql"] = "healthy"
        else:
            health_status["services"]["mysql"] = "unhealthy"
            health_status["status"] = "degraded"
    except Exception as e:
        health_status["services"]["mysql"] = f"unhealthy: {str(e)}"
        health_status["status"] = "degraded"
    
    # Check MongoDB connectivity
    try:
        mongo_client = get_mongodb_client()
        if mongo_client:
            # Test connection with a simple ping
            mongo_client.admin.command('ping')
            health_status["services"]["mongodb"] = "healthy"
        else:
            health_status["services"]["mongodb"] = "unhealthy"
            health_status["status"] = "degraded"
    except Exception as e:
        health_status["services"]["mongodb"] = f"unhealthy: {str(e)}"
        health_status["status"] = "degraded"
    
    return health_status

@app.get("/")
async def home(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

@app.get("/login")
async def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})

@app.get("/register")
async def register_page(request: Request):
    return templates.TemplateResponse("register.html", {"request": request})

@app.get("/chat")
async def chat_page(request: Request):
    return templates.TemplateResponse("chat.html", {"request": request})

@app.post("/register")
async def register_user(user_data: UserRegistration):
    try:
        user = auth_service.register_user(user_data)
        return {"message": "User registered successfully", "user": user}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/login", response_model=TokenResponse)
async def login_user(user_data: UserLogin):
    try:
        # Authenticate and get token
        token_response = auth_service.login_user(user_data)

        # Update login timestamps for proactive insights
        # We need to preserve the PREVIOUS login date to calculate the data window
        collections = get_mongodb_collections()
        if collections:
            from datetime import timezone
            now = datetime.now(timezone.utc)

            # Get current user data to preserve previous_login
            current_user_data = collections['users'].find_one(
                {"user_id": token_response.user.user_id}
            )

            # Move current last_login to previous_login before updating
            update_fields = {"last_login": now}

            if current_user_data and current_user_data.get("last_login"):
                # Normal flow - move current last_login to previous_login
                update_fields["previous_login"] = current_user_data["last_login"]

            # Update user with new login time
            collections['users'].update_one(
                {"user_id": token_response.user.user_id},
                {"$set": update_fields}
            )
            logging.info(f"Updated last_login for user: {token_response.user.email}")

        return token_response
    except ValueError as e:
        raise HTTPException(status_code=401, detail=str(e))


# ============================================
# MERCHANT SWITCHING ENDPOINTS
# ============================================

@app.get("/api/merchants")
async def get_available_merchants(
    current_user: UserResponse = Depends(get_current_user)
):
    """
    Get list of available merchant IDs that the user can switch between.

    Returns:
        - merchants: List of allowed merchant IDs
        - default: The default merchant ID
        - current: The user's currently selected merchant ID
    """
    return {
        "merchants": ALLOWED_MERCHANTS,
        "default": DEFAULT_MERCHANT,
        "current": current_user.merchant_id
    }


@app.post("/api/switch-merchant", response_model=TokenResponse)
async def switch_merchant(
    request: SwitchMerchantRequest,
    current_user: UserResponse = Depends(get_current_user)
):
    """
    Switch to a different merchant ID and get a new token.

    This endpoint:
    1. Validates the requested merchant_id is in the allowed list
    2. Creates a new JWT token with the new merchant_id
    3. Returns the new token for the frontend to store

    The frontend should:
    1. Store the new token
    2. Clear the chat history
    3. Reload the chat interface
    """
    try:
        token_response = auth_service.switch_merchant(current_user, request.merchant_id)
        logging.info(f"User {current_user.email} switched from merchant {current_user.merchant_id} to {request.merchant_id}")
        return token_response
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/user/preferences")
async def get_user_preferences(
    current_user: UserResponse = Depends(get_current_user)
):
    """Get user preferences (language, etc.)."""
    preferences = auth_service.get_user_preferences(current_user.user_id)
    return preferences


@app.patch("/api/user/preferences")
async def update_user_preferences(
    preferences: UserPreferencesUpdate,
    current_user: UserResponse = Depends(get_current_user)
):
    """Update user preferences (language, etc.)."""
    auth_service.update_user_preferences(current_user.user_id, preferences)
    logging.info(f"User {current_user.email} updated preferences: language={preferences.preferred_language}")
    return {"message": "Preferences updated", "preferred_language": preferences.preferred_language}


@app.post("/api/chat/agent", response_model=ChatResponse)
async def chat_with_agent_toolcalling(
    request: ChatRequest,
    current_user: UserResponse = Depends(get_current_user)
):
    """
    Tool-calling agent endpoint (non-streaming).

    This endpoint uses the Main Agent architecture with tool-calling capabilities.
    For streaming responses, use /api/chat/agent/stream instead.
    """
    try:
        collections = get_mongodb_collections()
        if not collections:
            raise HTTPException(status_code=500, detail="Failed to connect to the database.")

        conversation_id = request.conversation_id or str(uuid.uuid4())

        # 1. Fetch conversation history (SAME as V1)
        chat_history = []
        if request.conversation_id:
            history_cursor = collections['history'].find(
                {"conversation_id": request.conversation_id}
            ).sort("timestamp", -1).limit(10)  # Fetch last 10 messages for better context

            recent_messages = list(history_cursor)
            recent_messages.reverse()

            # Convert to LangChain message format
            from langchain_core.messages import HumanMessage, AIMessage
            for message in recent_messages:
                chat_history.append(HumanMessage(content=message['user_query']))
                chat_history.append(AIMessage(content=message['ai_response']))

        # 2. Create Main Agent with merchant isolation
        from agent.main_agent import create_main_agent, invoke_main_agent

        logging.info(f"[API Agent] Creating Main Agent for merchant: {current_user.merchant_id}")
        agent_executor = create_main_agent(merchant_id=current_user.merchant_id, user_query=request.user_query, language=request.language)

        # 3. Invoke the agent
        logging.info(f"[API Agent] Invoking agent with query: {request.user_query}")
        ai_response = invoke_main_agent(
            agent_executor=agent_executor,
            user_query=request.user_query,
            merchant_id=current_user.merchant_id,
            chat_history=chat_history
        )

        logging.info(f"[API Agent] Agent response received. Length: {len(str(ai_response))}")

        # 4. Save to history
        message_id = str(uuid.uuid4())
        current_timestamp = datetime.now(timezone.utc)

        collections['history'].insert_one({
            "message_id": message_id,
            "conversation_id": conversation_id,
            "user_id": current_user.user_id,
            "user_query": request.user_query,
            "ai_response": ai_response,
            "timestamp": current_timestamp
        })

        collections['conversations'].update_one(
            {"conversation_id": conversation_id},
            {
                "$setOnInsert": {"user_id": current_user.user_id, "start_time": current_timestamp},
                "$set": {"last_updated": current_timestamp, "last_message_preview": ai_response[:100]}
            },
            upsert=True
        )

        logging.info(f"[API Agent] Response saved for conversation: {conversation_id}")

        return ChatResponse(
            ai_response=ai_response,
            conversation_id=conversation_id,
            message_id=message_id
        )

    except Exception as e:
        logging.error(f"[API Agent] Error occurred: {e}\n{traceback.format_exc()}")
        raise HTTPException(status_code=500, detail="An internal server error occurred.")


@app.post("/api/reset-insights")
async def reset_insights(current_user: UserResponse = Depends(get_current_user)):
    """Reset insights flag for testing purposes"""
    try:
        collections = get_mongodb_collections()
        result = collections['users'].update_one(
            {"user_id": current_user.user_id},
            {"$set": {"last_insight_date": None, "insight_shown_count": 0}}
        )
        logging.info(f"Reset insights for {current_user.email}")
        return {"message": "Insights reset successfully", "modified": result.modified_count}
    except Exception as e:
        logging.error(f"Error resetting insights: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/chat/initial")
async def get_initial_message(
    current_user: UserResponse = Depends(get_current_user),
    force_insights: bool = False  # Testing parameter
):
    """
    Checks if proactive insights OR monthly report should be shown on chat initialization.

    Returns:
        - type: "proactive_insights" if daily insights should be shown
        - type: "monthly_report" if monthly report prompt should be shown
        - type: "greeting" for standard greeting

    Query Params:
        - force_insights: Set to true to force insights for testing (e.g., ?force_insights=true)
    """
    try:
        from agent.insights import should_show_proactive_insights, should_offer_monthly_report

        collections = get_mongodb_collections()
        if not collections:
            raise HTTPException(status_code=500, detail="Database connection failed")

        # Get user data to check if insights should be shown
        user_data = collections['users'].find_one({"user_id": current_user.user_id})

        if not user_data:
            raise HTTPException(status_code=404, detail="User not found")

        # Determine preferred language
        preferred_language = user_data.get("preferred_language", "ar")

        # TESTING MODE: Force insights if query param is set
        if force_insights:
            logging.info(f"🧪 TESTING MODE: Force showing insights for {current_user.email}")
            from datetime import datetime, timezone, timedelta
            data_since = datetime.now(timezone.utc) - timedelta(hours=24)
            return {
                "type": "proactive_insights",
                "should_stream": True,
                "data_since": data_since.isoformat(),
                "language": preferred_language
            }

        # PRIORITY 1: Check if monthly report should be offered
        # Monthly report takes priority over daily insights
        should_offer_monthly, monthly_reason = should_offer_monthly_report(user_data)
        if should_offer_monthly:
            logging.info(f"Initial message check: Monthly report should be offered to {current_user.email} ({monthly_reason})")
            return {
                "type": "proactive_insights",  # Use same type - stream handler will detect monthly
                "should_stream": True,
                "is_monthly": True,
                "reason": monthly_reason,
                "language": preferred_language
            }

        # PRIORITY 2: Check if we should show daily proactive insights
        show_insights, data_since = should_show_proactive_insights(user_data)

        if show_insights and data_since:
            logging.info(f"Initial message check: Daily insights should be shown for {current_user.email}")
            return {
                "type": "proactive_insights",
                "should_stream": True,
                "data_since": data_since.isoformat(),
                "language": preferred_language
            }
        else:
            logging.info(f"Initial message check: Standard greeting for {current_user.email}")
            greeting = "مرحباً! كيف أقدر أساعدك اليوم؟" if preferred_language == "ar" else "Hello! How can I help you today?"
            return {
                "type": "greeting",
                "message": greeting,
                "should_stream": False,
                "language": preferred_language
            }

    except Exception as e:
        logging.error(f"Error in initial message check: {e}")
        # Fallback to greeting on error (default Arabic)
        return {
            "type": "greeting",
            "message": "مرحباً! كيف أقدر أساعدك اليوم؟",
            "should_stream": False,
            "language": "ar"
        }


@app.get("/api/chat/history")
async def get_chat_history(
    current_user: UserResponse = Depends(get_current_user),
    limit: int = 20
):
    """
    Fetches recent chat history for the current user and merchant.

    Returns the most recent messages (up to limit) for the user's current merchant,
    allowing chat to persist across page refreshes.

    Query Params:
        - limit: Maximum number of messages to return (default: 20)
    """
    try:
        collections = get_mongodb_collections()
        if not collections:
            raise HTTPException(status_code=500, detail="Database connection failed")

        # Fetch recent messages for this user and merchant
        # Sort by timestamp descending, then reverse to get chronological order
        history_cursor = collections['history'].find(
            {
                "user_id": current_user.user_id,
                "merchant_id": current_user.merchant_id
            }
        ).sort("timestamp", -1).limit(limit)

        messages = list(history_cursor)
        messages.reverse()  # Chronological order (oldest first)

        # Format for frontend
        formatted_messages = []
        for msg in messages:
            formatted_messages.append({
                "message_id": msg.get("message_id"),
                "conversation_id": msg.get("conversation_id"),
                "user_query": msg.get("user_query"),
                "ai_response": msg.get("ai_response"),
                "timestamp": msg.get("timestamp").isoformat() if msg.get("timestamp") else None
            })

        # Get the most recent conversation_id for continuity
        latest_conversation_id = messages[-1].get("conversation_id") if messages else None

        logging.info(f"[Chat History] Returned {len(formatted_messages)} messages for user {current_user.user_id}, merchant {current_user.merchant_id}")

        return {
            "messages": formatted_messages,
            "conversation_id": latest_conversation_id,
            "count": len(formatted_messages)
        }

    except Exception as e:
        logging.error(f"Error fetching chat history: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to fetch chat history")


@app.delete("/api/chat/history")
async def clear_chat_history(
    current_user: UserResponse = Depends(get_current_user)
):
    """
    Clears chat history for the current user and merchant.
    This allows users to start fresh conversations.
    """
    try:
        collections = get_mongodb_collections()
        if not collections:
            raise HTTPException(status_code=500, detail="Database connection failed")

        # Delete all history for this user and merchant
        result = collections['history'].delete_many({
            "user_id": current_user.user_id,
            "merchant_id": current_user.merchant_id
        })

        logging.info(f"[Chat History] Cleared {result.deleted_count} messages for user {current_user.user_id}, merchant {current_user.merchant_id}")

        return {
            "success": True,
            "deleted_count": result.deleted_count,
            "message": "Chat history cleared successfully"
        }

    except Exception as e:
        logging.error(f"Error clearing chat history: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to clear chat history")


@app.post("/api/chat/agent/stream")
async def chat_with_agent_stream(
    request: ChatRequest,
    background_tasks: BackgroundTasks,
    current_user: UserResponse = Depends(get_current_user)
):
    """
    Tool-calling agent endpoint with SSE streaming.

    This endpoint streams tokens as they're generated by the LLM, providing
    real-time feedback to users. It also sends status updates when tools are invoked.

    Event types sent:
    - tool_start: When a tool (query_db, agentic_rag, validate) starts execution
    - token: Individual tokens from the LLM response
    - done: Final event with complete response
    - error: Error occurred during generation

    The complete response is saved to MongoDB asynchronously via background task.
    """
    try:
        from agent.insights import should_show_proactive_insights, generate_proactive_insights, mark_insights_shown

        collections = get_mongodb_collections()
        if not collections:
            raise HTTPException(status_code=500, detail="Failed to connect to the database.")

        conversation_id = request.conversation_id or str(uuid.uuid4())
        message_id = str(uuid.uuid4())

        # Check if this is first chat of the day (proactive insights)
        user_data = collections['users'].find_one({"user_id": current_user.user_id})

        show_insights, data_since = should_show_proactive_insights(user_data)

        # Check if monthly report should be offered
        from agent.insights import should_offer_monthly_report, generate_monthly_report, mark_monthly_report_offered, mark_monthly_prompt_shown, is_awaiting_monthly_response
        should_offer_monthly, monthly_reason = should_offer_monthly_report(user_data)
        awaiting_monthly_response = is_awaiting_monthly_response(user_data)

        # ============================================
        # MONTHLY REPORT PROMPT FLOW (Ask First) - Takes Priority
        # ============================================
        # When monthly report is due, show ONLY monthly report prompt (skip daily insights)
        if should_offer_monthly and request.user_query == "":
            logging.info(f"[API Stream] Offering monthly report to {current_user.email}")

            # Mark prompt as shown IMMEDIATELY (prevents showing again on page refresh)
            mark_monthly_prompt_shown(collections, current_user.user_id)

            # Also mark daily insights as shown (since monthly takes priority for today)
            # This prevents daily insights from showing after monthly prompt
            mark_insights_shown(collections, current_user.user_id)

            async def monthly_prompt_generator():
                """Generate SSE events for monthly report prompt"""
                try:
                    prompt_message = "Hey! I noticed it's been a while since your last monthly summary. I've been analyzing the last 30 days of your business - visits, customer segments, orders, revenue, and loyalty trends.\n\nWant me to walk you through it?"

                    # Stream the prompt
                    words = prompt_message.split(' ')
                    for word in words:
                        token_event = {"type": "token", "content": word + ' '}
                        yield f"data: {json.dumps(token_event)}\n\n"
                        await asyncio.sleep(0.05)

                    # Send done event with monthly_report_prompt flag
                    done_event = {
                        "type": "done",
                        "conversation_id": conversation_id,
                        "message_id": message_id,
                        "insight_type": "monthly_report_prompt"
                    }
                    yield f"data: {json.dumps(done_event)}\n\n"

                except Exception as e:
                    logging.error(f"[API Stream] Error generating monthly report prompt: {e}")
                    error_event = {"type": "error", "content": f"Error: {str(e)}"}
                    yield f"data: {json.dumps(error_event)}\n\n"

            return StreamingResponse(
                monthly_prompt_generator(),
                media_type="text/event-stream",
                headers={"Cache-Control": "no-cache", "Connection": "keep-alive"}
            )

        # ============================================
        # MONTHLY REPORT GENERATION (User accepted)
        # ============================================
        # Trigger if: user says "yes" or similar AND we recently showed them the monthly prompt
        monthly_accept_phrases = ["yes", "show me", "show report", "monthly report", "sure", "okay", "ok", "go ahead"]
        if any(phrase in request.user_query.lower() for phrase in monthly_accept_phrases) and awaiting_monthly_response:
            logging.info(f"[API Stream] Generating monthly report for {current_user.email}")

            # Mark monthly report as shown IMMEDIATELY (before streaming)
            # This prevents it from showing again if connection drops mid-stream
            mark_monthly_report_offered(collections, current_user.user_id, accepted=True)

            async def monthly_report_generator():
                """Generate SSE events for monthly report"""
                try:
                    yield f"data: {json.dumps({'type': 'generating_start', 'message': 'Generating your monthly report...'})}\n\n"

                    # Start report generation as a task so we can send keepalives
                    generation_task = asyncio.create_task(
                        generate_monthly_report(
                            merchant_id=current_user.merchant_id,
                            user_email=current_user.email
                        )
                    )

                    # Send keepalive pings every 3 seconds while generating
                    # This prevents proxy/HTTP2 timeouts during the ~30 second generation
                    while not generation_task.done():
                        await asyncio.sleep(3)
                        if not generation_task.done():
                            yield ": keepalive\n\n"  # SSE comment (ignored by client)
                            logging.debug("[Monthly Report] Sent keepalive ping")

                    # Get the generated report
                    report = await generation_task

                    # Stream the report word by word
                    words = report.split(' ')
                    for word in words:
                        token_event = {"type": "token", "content": word + ' '}
                        yield f"data: {json.dumps(token_event)}\n\n"
                        await asyncio.sleep(0.05)

                    done_event = {
                        "type": "done",
                        "conversation_id": conversation_id,
                        "message_id": message_id,
                        "insight_type": "monthly_report"
                    }
                    yield f"data: {json.dumps(done_event)}\n\n"

                except Exception as e:
                    logging.error(f"[API Stream] Error generating monthly report: {e}", exc_info=True)
                    error_event = {"type": "error", "content": f"Error: {str(e)}"}
                    yield f"data: {json.dumps(error_event)}\n\n"

            return StreamingResponse(
                monthly_report_generator(),
                media_type="text/event-stream",
                headers={
                    "Cache-Control": "no-cache",
                    "Connection": "keep-alive",
                    "X-Accel-Buffering": "no",  # Disable nginx buffering
                    "Content-Type": "text/event-stream"
                }
            )

        # ============================================
        # DAILY INSIGHTS FLOW (Auto-show)
        # ============================================
        # Trigger if: insights should show AND user_query is empty (initial load)
        # Daily insights take priority - monthly report only shows AFTER daily insights were shown
        if show_insights and data_since and request.user_query == "":
            logging.info(f"[API Stream] Showing proactive insights for {current_user.email}")

            async def insights_event_generator():
                """Generate SSE events for proactive insights"""
                try:
                    # Signal that we're generating insights
                    yield f"data: {json.dumps({'type': 'generating_start', 'message': 'Preparing your daily insights...'})}\n\n"

                    # Start generation as a task so we can send keepalives
                    logging.info(f"[Insights] Calling generate_proactive_insights for merchant {current_user.merchant_id}")
                    generation_task = asyncio.create_task(
                        generate_proactive_insights(
                            merchant_id=current_user.merchant_id,
                            data_since=data_since,
                            user_email=current_user.email
                        )
                    )

                    # Send keepalive pings every 3 seconds while generating
                    while not generation_task.done():
                        await asyncio.sleep(3)
                        if not generation_task.done():
                            yield ": keepalive\n\n"  # SSE comment (ignored by client)

                    # Get the generated message
                    proactive_message = await generation_task

                    # Mark insights as shown only AFTER successful generation
                    # If generation fails, the user can retry on next page load
                    mark_insights_shown(collections, current_user.user_id)

                    logging.info(f"[Insights] Generated message length: {len(proactive_message)} characters")
                    logging.info(f"[Insights] Message preview: {proactive_message[:200]}...")

                    # Stream the message word by word to simulate natural streaming
                    words = proactive_message.split(' ')
                    logging.info(f"[Insights] Streaming {len(words)} words")

                    for i, word in enumerate(words):
                        token_event = {
                            "type": "token",
                            "content": word + ' '
                        }
                        yield f"data: {json.dumps(token_event)}\n\n"
                        # Small delay to simulate natural streaming
                        await asyncio.sleep(0.05)

                    # Send done event
                    done_event = {
                        "type": "done",
                        "conversation_id": conversation_id,
                        "message_id": message_id,
                        "insight_type": "proactive"
                    }
                    yield f"data: {json.dumps(done_event)}\n\n"

                    # Save to conversation history
                    background_tasks.add_task(
                        save_conversation_history,
                        collections=collections,
                        message_id=message_id,
                        conversation_id=conversation_id,
                        user_id=current_user.user_id,
                        user_query="[First chat of the day - Proactive Insights]",
                        ai_response=proactive_message,
                        merchant_id=current_user.merchant_id
                    )

                except Exception as e:
                    logging.error(f"[API Stream] Error generating proactive insights: {e}", exc_info=True)
                    error_event = {
                        "type": "error",
                        "content": f"Unable to generate insights: {str(e)}"
                    }
                    yield f"data: {json.dumps(error_event)}\n\n"

            return StreamingResponse(
                insights_event_generator(),
                media_type="text/event-stream",
                headers={
                    "Cache-Control": "no-cache",
                    "Connection": "keep-alive",
                    "X-Accel-Buffering": "no",
                    "Content-Type": "text/event-stream"
                }
            )

        # ============================================
        # NORMAL CHAT FLOW
        # ============================================

        # 1. Fetch conversation history (same as V2)
        chat_history = []
        entity_context = {}
        if request.conversation_id:
            history_cursor = collections['history'].find(
                {"conversation_id": request.conversation_id}
            ).sort("timestamp", -1).limit(10)

            recent_messages = list(history_cursor)

            # Aggregate entity context from recent messages (before reversing)
            from agent.entity_tracker import aggregate_entity_context
            entity_context = aggregate_entity_context(recent_messages)
            logging.info(f"[API Stream] Entity context loaded: {entity_context}")

            recent_messages.reverse()

            from langchain_core.messages import HumanMessage, AIMessage
            for message in recent_messages:
                chat_history.append(HumanMessage(content=message['user_query']))
                chat_history.append(AIMessage(content=message['ai_response']))

        # Search for relevant past insights
        past_insights = []
        try:
            from agent.insights_memory import search_past_insights
            past_insights = search_past_insights(
                query=request.user_query,
                merchant_id=current_user.merchant_id,
                limit=2,
                min_score=0.72
            )
            if past_insights:
                logging.info(f"[API Stream] Found {len(past_insights)} relevant past insights")
        except Exception as insight_error:
            logging.warning(f"[API Stream] Failed to search insights (non-critical): {insight_error}")
            past_insights = []

        # 2. Create Main Agent and Cost Tracking Callback
        from agent.main_agent import create_main_agent, stream_main_agent

        logging.info(f"[API Stream] Creating Main Agent for merchant: {current_user.merchant_id}")
        agent_executor = create_main_agent(
            merchant_id=current_user.merchant_id,
            entity_context=entity_context,
            past_insights=past_insights,
            user_query=request.user_query,
            language=request.language
        )

        # Create cost tracking callback for this request
        cost_callback = CostTrackingCallback()

        # Set callbacks in context so ALL LLM calls (including pipeline nodes) are tracked
        set_callbacks([cost_callback])

        # 3. Define SSE event generator
        async def event_generator():
            """
            Generates Server-Sent Events from the agent stream.

            SSE format:
                data: {json}\n\n

            Each event is a JSON object with 'type' and relevant data.
            Sends keepalive pings every 15s during long tool executions
            to prevent proxy/load balancer connection timeouts.
            """
            full_response = ""

            try:
                # Stream events from the agent with cost tracking
                # Use asyncio.wait with keepalive to prevent connection
                # timeouts during long-running tool executions (e.g. slow DB queries)
                #
                # IMPORTANT: We use asyncio.wait (not wait_for) because wait_for
                # cancels the awaitable on timeout, which destroys the async generator.
                # asyncio.wait leaves the task running so we can keep checking it.
                _STREAM_DONE = object()

                agent_stream = stream_main_agent(
                    agent_executor=agent_executor,
                    user_query=request.user_query,
                    merchant_id=current_user.merchant_id,
                    chat_history=chat_history,
                    callbacks=[cost_callback]
                )
                agent_iter = agent_stream.__aiter__()

                async def _safe_anext(aiter):
                    """Wraps __anext__ to return sentinel instead of raising StopAsyncIteration."""
                    try:
                        return await aiter.__anext__()
                    except StopAsyncIteration:
                        return _STREAM_DONE

                next_event_task = asyncio.ensure_future(_safe_anext(agent_iter))

                while True:
                    # Wait for the next event with a 15s timeout
                    done, _ = await asyncio.wait({next_event_task}, timeout=15)

                    if not done:
                        # Timeout: task still running, send keepalive to keep connection alive
                        yield ": keepalive\n\n"
                        continue

                    # Task completed - get the result
                    event = next_event_task.result()
                    if event is _STREAM_DONE:
                        break

                    # Start waiting for the next event immediately
                    next_event_task = asyncio.ensure_future(_safe_anext(agent_iter))

                    event_type = event.get("type")

                    if event_type == "token":
                        # Stream individual token
                        token = event.get("content", "")
                        full_response += token

                        # Send as SSE
                        yield f"data: {json.dumps(event)}\n\n"

                    elif event_type == "tool_start":
                        # Send tool status update
                        logging.info(f"[API Stream] Tool started: {event.get('tool')}")
                        yield f"data: {json.dumps(event)}\n\n"

                    elif event_type == "done":
                        # Get full response and cost data from event
                        full_response = event.get("full_response", full_response)
                        queried_table = event.get("queried_table")
                        cost_data = event.get("cost_data")

                        logging.info(f"[API Stream] Stream completed. Length: {len(full_response)}")
                        if cost_data:
                            logging.info(
                                f"[API Stream] Cost: ${cost_data.get('cost_usd', 0):.6f}, "
                                f"tokens: {cost_data.get('total_tokens', 0)}"
                            )

                        # Generate contextual follow-up suggestions using LLM
                        from agent.suggestions import get_follow_up_suggestions
                        suggestions = get_follow_up_suggestions(
                            user_query=request.user_query,
                            table_name=queried_table,
                            num_suggestions=3
                        )

                        # Send done event with metadata and suggestions
                        done_event = {
                            "type": "done",
                            "conversation_id": conversation_id,
                            "message_id": message_id,
                            "suggestions": suggestions
                        }
                        yield f"data: {json.dumps(done_event)}\n\n"

                        # Schedule background save to MongoDB with cost data
                        background_tasks.add_task(
                            save_conversation_history,
                            collections=collections,
                            message_id=message_id,
                            conversation_id=conversation_id,
                            user_id=current_user.user_id,
                            user_query=request.user_query,
                            ai_response=full_response,
                            merchant_id=current_user.merchant_id,
                            cost_data=cost_data
                        )

                        break

                    elif event_type == "error":
                        # Send error event
                        logging.error(f"[API Stream] Error event: {event.get('content')}")
                        yield f"data: {json.dumps(event)}\n\n"
                        break

            except Exception as e:
                logging.error(f"[API Stream] Error in event generator: {e}\n{traceback.format_exc()}")

                error_event = {
                    "type": "error",
                    "content": "An internal server error occurred during streaming."
                }
                yield f"data: {json.dumps(error_event)}\n\n"

            finally:
                # Clear callbacks after request completes
                clear_callbacks()

        # 4. Return StreamingResponse with SSE
        return StreamingResponse(
            event_generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",  # Disable nginx buffering
            }
        )

    except Exception as e:
        logging.error(f"[API Stream] Error setting up stream: {e}\n{traceback.format_exc()}")
        raise HTTPException(status_code=500, detail="Failed to initialize streaming.")


def save_conversation_history(
    collections,
    message_id: str,
    conversation_id: str,
    user_id: str,
    user_query: str,
    ai_response: str,
    merchant_id: str = None,
    cost_data: dict = None
):
    """
    Background task to save conversation history to MongoDB with cost tracking.

    This runs asynchronously after the stream completes, so we don't block
    the response from being sent to the user.

    Args:
        collections: MongoDB collections dict
        message_id: Unique message identifier
        conversation_id: Conversation identifier
        user_id: User identifier
        user_query: The user's query
        ai_response: The AI's response
        merchant_id: Optional merchant identifier
        cost_data: Optional cost tracking data dict with keys:
            - input_tokens: Number of input tokens
            - output_tokens: Number of output tokens
            - total_tokens: Total tokens used
            - cost_usd: Total cost in USD
            - model: Model name used
            - latency_ms: Response latency
            - llm_calls: Number of LLM calls
            - tools_used: List of tools invoked
    """
    try:
        current_timestamp = datetime.now(timezone.utc)

        # Extract entities from user query for context tracking
        from agent.entity_tracker import extract_entities
        extracted_entities = extract_entities(user_query)

        # Save to history collection with cost data embedded
        history_doc = {
            "message_id": message_id,
            "conversation_id": conversation_id,
            "user_id": user_id,
            "user_query": user_query,
            "ai_response": ai_response,
            "timestamp": current_timestamp,
            "entities": extracted_entities  # Entity tracking for session context
        }
        if merchant_id:
            history_doc["merchant_id"] = merchant_id

        # Add cost tracking data if available
        if cost_data:
            history_doc["cost"] = {
                "input_tokens": cost_data.get("input_tokens", 0),
                "output_tokens": cost_data.get("output_tokens", 0),
                "total_tokens": cost_data.get("total_tokens", 0),
                "cost_usd": cost_data.get("cost_usd", 0.0),
                "model": cost_data.get("model", "unknown"),
                "latency_ms": cost_data.get("latency_ms", 0),
                "llm_calls": cost_data.get("llm_calls", 0),
                "tools_used": cost_data.get("tools_used", [])
            }

        collections['history'].insert_one(history_doc)

        # Store insight in vector database for future retrieval (async-safe, non-blocking on failure)
        try:
            from agent.insights_memory import store_conversation_insight
            store_conversation_insight(
                message_id=message_id,
                merchant_id=merchant_id,
                user_query=user_query,
                ai_response=ai_response,
                entities=extracted_entities
            )
        except Exception as insight_error:
            logging.warning(f"[Background] Failed to store insight (non-critical): {insight_error}")

        # Upsert conversation document with accumulated cost
        update_fields = {
            "last_updated": current_timestamp,
            "last_message_preview": ai_response[:100]
        }

        # Build the update operation
        # NOTE: Don't put total_cost_usd/total_tokens in $setOnInsert if using $inc
        # MongoDB doesn't allow the same field in both operators
        update_op = {
            "$setOnInsert": {
                "user_id": user_id,
                "start_time": current_timestamp
            },
            "$set": update_fields,
            "$inc": {"message_count": 1}
        }

        # Increment accumulated cost if we have cost data
        # $inc will create fields with the increment value if they don't exist
        if cost_data:
            update_op["$inc"]["total_cost_usd"] = cost_data.get("cost_usd", 0.0)
            update_op["$inc"]["total_tokens"] = cost_data.get("total_tokens", 0)

        collections['conversations'].update_one(
            {"conversation_id": conversation_id},
            update_op,
            upsert=True
        )

        if cost_data:
            logging.info(
                f"[Background] Saved message {message_id} with cost: "
                f"${cost_data.get('cost_usd', 0):.6f}, {cost_data.get('total_tokens', 0)} tokens"
            )
        else:
            logging.info(f"[Background] Saved conversation history for message: {message_id}")

    except Exception as e:
        logging.error(f"[Background] Failed to save conversation history: {e}", exc_info=True)


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
