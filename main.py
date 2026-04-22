import asyncio
import sys
import uuid
import os
from fastapi import FastAPI, BackgroundTasks, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from datetime import datetime

# Windows asyncio fix
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

# ── App Setup ─────────────────────────────────────────
app = FastAPI(title="SiteIQ API", version="2.0")

# CORS — must be configured carefully for local file:// and browser access
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,  # Set to False if origins is ["*"]
    allow_methods=["*"],
    allow_headers=["*"],
)

from crawler import crawl_website, make_website_id
from database import (
    get_website_from_registry,
    save_website_to_registry,
    update_registry,
    update_registry_first_crawled,
    search_pages,
    save_chat_session,
    add_message_to_session,
    get_chat_sessions,
    db
)

# ── Groq AI Setup ────────────────────────────────────
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")

async def generate_ai_answer(question: str, context: str) -> str:
    """Use Groq LLM to generate a nicely formatted answer from context."""
    if not GROQ_API_KEY:
        print("⚠️ GROQ_API_KEY not found in environment!")
        return format_fallback_answer(question, context)

    try:
        from groq import Groq
        client = Groq(api_key=GROQ_API_KEY)

        # Truncate context to stay within token limits (llama-3.1-8b has 128k context but we'll stay safe)
        safe_context = context[:12000] 

        completion = client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are SiteIQ, a professional web intelligence AI. "
                        "Your goal is to answer questions based strictly on the provided website content. "
                        "\n\nRules:\n"
                        "1. Use Markdown for formatting (bolding, lists, etc).\n"
                        "2. If the user asks something NOT in the content, say: 'I'm sorry, but I couldn't find information about that on this website.'\n"
                        "3. Be concise but thorough.\n"
                        "4. If you see contact information, prices, or dates, report them accurately."
                    )
                },
                {
                    "role": "user",
                    "content": (
                        f"Here is the content of the website:\n---\n{safe_context}\n---\n\n"
                        f"Question: {question}\n\n"
                        "Answer based ONLY on the above content:"
                    )
                }
            ],
            temperature=0.2,
            max_tokens=800,
        )
        return completion.choices[0].message.content
    except Exception as e:
        print(f"⚠️ Groq API error: {e}")
        return format_fallback_answer(question, context)


def format_fallback_answer(question: str, context: str) -> str:
    """Format answer when Groq is unavailable — extract relevant snippets."""
    lines = context.split("\n")
    keywords = [w.lower() for w in question.split() if len(w) > 2]
    relevant = []
    for line in lines:
        line_lower = line.lower()
        if any(kw in line_lower for kw in keywords):
            clean = line.strip()
            if clean and clean not in relevant:
                relevant.append(clean)
    if relevant:
        return "Here's what I found on the website:\n\n" + "\n".join(f"• {r}" for r in relevant[:10])
    return context[:1500] if context else "No relevant information found."


# ── Request Models ────────────────────────────────────
class CrawlRequest(BaseModel):
    url: str

class QuestionRequest(BaseModel):
    session_id: str
    question: str
    website_id: str  
    url: str  


# ── Background Crawl ─────────────────────────────────
async def background_crawl(url: str, website_id: str, is_new: bool):
    try:
        print(f"🚀 Background crawl started: {url}")
        total_pages = await crawl_website(url, website_id)
        update_registry(url, total_pages)
        if is_new:
            update_registry_first_crawled(url)
        print(f"🎉 Done: {url} — {total_pages} pages")
    except Exception as e:
        print(f"❌ Background crawl failed: {e}")
        db["websites_registry"].update_one(
            {"original_url": url},
            {"$set": {"status": "failed"}}
        )


# ── Routes ────────────────────────────────────────────

@app.get("/")
def health_check():
    return {"status": "running", "message": "SiteIQ API is live! 🚀"}


@app.post("/crawl")
async def crawl(request: CrawlRequest, background_tasks: BackgroundTasks):
    url = request.url.strip().rstrip("/")
    website_id = make_website_id(url)
    existing = get_website_from_registry(url)

    if existing:
        if existing.get("status") == "crawling":
            return {
                "status": "in_progress",
                "website_id": website_id,
                "total_pages": existing.get("total_pages", 0),
                "message": "⏳ Still crawling! Ask your question in a few minutes."
            }
        if existing.get("status") == "complete":
            # Re-crawl in background for freshness
            background_tasks.add_task(background_crawl, url, website_id, False)
            return {
                "status": "ready",
                "website_id": website_id,
                "total_pages": existing.get("total_pages", 0),
                "message": f"✅ Ready! ({existing['total_pages']} pages). Ask your question now!"
            }

    save_website_to_registry(url, website_id)
    background_tasks.add_task(background_crawl, url, website_id, True)
    return {
        "status": "crawling_started",
        "website_id": website_id,
        "total_pages": 0,
        "message": "🚀 Crawling started! Wait 2-3 minutes then ask your question."
    }


@app.get("/status")
async def check_status(url: str):
    clean_url = url.strip().rstrip("/")
    existing = get_website_from_registry(clean_url)
    if not existing:
        return {"status": "not_found", "total_pages": 0}
    return {
        "status": existing["status"],
        "total_pages": existing.get("total_pages", 0)
    }


# @app.post("/start-session")
# def start_session(request: CrawlRequest):
#     url = request.url.strip().rstrip("/")
#     website_id = make_website_id(url)
#     session_id = str(uuid.uuid4())
#     save_chat_session(session_id, url, website_id)
#     return {
#         "session_id": session_id,
#         "website_id": website_id,
#         "message": "Session started!"
#     }
class SessionRequest(BaseModel):
    website_id: str

@app.post("/start-session")
def start_session(request: SessionRequest):
    session_id = str(uuid.uuid4())
    save_chat_session(session_id, "", request.website_id)
    return {
        "session_id": session_id,
        "website_id": request.website_id,
        "message": "Session started!"
    }

@app.post("/ask")
async def ask_question(request: QuestionRequest):
    results = search_pages(request.website_id, request.question)
    print("GROQ KEY STATUS:", "SET" if os.environ.get("GROQ_API_KEY") else "NOT SET")
    print("Question:", request.question)
    print("Website ID:", request.website_id)
    if not results:
        add_message_to_session(request.session_id, "user", request.question)
        answer = "I couldn't find any information related to your question on this website. Try rephrasing or asking about a different topic."
        add_message_to_session(request.session_id, "assistant", answer)
        return {
            "answer": answer,
            "sources": []
        }

    # Build context from search results
    context = "\n\n".join([
        f"Page: {r.get('title', 'Untitled')}\n"
        f"URL: {r.get('page_url', '')}\n"
        f"Content: {r.get('content', '')[:30000]}"
        for r in results
    ])

    sources = [r.get("page_url") for r in results if r.get("page_url")]

    # Save user message
    add_message_to_session(request.session_id, "user", request.question)

    # Generate AI answer
    answer = await generate_ai_answer(request.question, context)

    # Save AI response
    add_message_to_session(request.session_id, "assistant", answer)

    return {
        "answer": answer,
        "sources": sources
    }


@app.get("/sessions")
def get_sessions():
    """Get all chat sessions for the sidebar."""
    sessions = get_chat_sessions()
    return {"sessions": sessions}