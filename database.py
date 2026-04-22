from pymongo import MongoClient, TEXT

# Direct connection
MONGODB_URI = "mongodb+srv://mhusnainali_db:mhusnainali@cluster0.mws0bmt.mongodb.net/"
DB_NAME = "web_agent_db"

# Connect to MongoDB
client = MongoClient(MONGODB_URI)
db = client[DB_NAME]

# Create indexes on startup
def create_indexes():
    # Drop old conflicting text index if it exists
    try:
        db["pages"].drop_index("content_text")
    except:
        pass  # index didn't exist, no problem

    # Now create the correct one with title weights
    db["pages"].create_index(
        [("content", TEXT), ("title", TEXT)],
        weights={"title": 10, "content": 1},
        name="content_text_title_text"
    )

    db["pages"].create_index("page_url", unique=True)
    db["websites_registry"].create_index("original_url", unique=True)
    db["chat_sessions"].create_index("session_id", unique=True)

# ─── Registry Functions ───────────────────────────────

def get_website_from_registry(url: str):
    """Check if website already crawled"""
    return db["websites_registry"].find_one({"original_url": url})

def save_website_to_registry(url: str, website_id: str):
    """Save new website to registry"""
    db["websites_registry"].update_one(
        {"original_url": url},
        {"$setOnInsert": {
            "original_url": url,
            "website_id": website_id,
            "first_crawled": None,
            "last_checked": None,
            "total_pages": 0,
            "status": "crawling"
        }},
        upsert=True
    )

def update_registry(url: str, total_pages: int):
    """Update registry after crawling done"""
    from datetime import datetime
    db["websites_registry"].update_one(
        {"original_url": url},
        {"$set": {
            "last_checked": datetime.utcnow(),
            "total_pages": total_pages,
            "status": "complete"
        }}
    )

def update_registry_first_crawled(url: str):
    """Set first crawled date"""
    from datetime import datetime
    db["websites_registry"].update_one(
        {"original_url": url},
        {"$set": {"first_crawled": datetime.utcnow()}}
    )

# ─── Pages Functions ──────────────────────────────────

def get_page(page_url: str):
    """Get single page by URL"""
    return db["pages"].find_one({"page_url": page_url})

def save_page(website_id: str, page_data: dict):
    """Save new page to pages collection"""
    page_data["website_id"] = website_id
    try:
        db["pages"].insert_one(page_data)
    except Exception as e:
        print(f"⚠️ Page already exists: {e}")

def update_page(page_url: str, new_data: dict):
    """Update existing page if content changed"""
    db["pages"].update_one(
        {"page_url": page_url},
        {"$set": new_data}
    )

def search_pages(website_id: str, query: str):
    """Search pages of specific website only"""
    return list(db["pages"].find(
        {
            "website_id": website_id,
            "$text": {"$search": query}
        },
        {
            "score": {"$meta": "textScore"},
            "content": 1,
            "page_url": 1,
            "title": 1
        }
    ).sort([("score", {"$meta": "textScore"})]).limit(5))

def get_all_pages(website_id: str):
    """Get all pages of a specific website"""
    return list(db["pages"].find(
        {"website_id": website_id},
        {"page_url": 1, "title": 1}
    ))

# ─── Chat Session Functions ───────────────────────────

def save_chat_session(session_id: str, website_url: str, website_id: str):
    """Create new chat session"""
    from datetime import datetime
    db["chat_sessions"].insert_one({
        "session_id": session_id,
        "website_url": website_url,
        "website_id": website_id,
        "messages": [],
        "created_at": datetime.utcnow()
    })

def add_message_to_session(session_id: str, role: str, message: str):
    """Add message to existing session"""
    from datetime import datetime
    db["chat_sessions"].update_one(
        {"session_id": session_id},
        {"$push": {"messages": {
            "role": role,
            "message": message,
            "timestamp": datetime.utcnow()
        }}}
    )

def get_chat_sessions():
    """Get all chat sessions for sidebar"""
    sessions = list(db["chat_sessions"].find(
        {},
        {"session_id": 1, "website_url": 1, "website_id": 1, "created_at": 1, "messages": 1, "_id": 0}
    ).sort("created_at", -1).limit(50))
    # Add message count and trim messages from response
    for s in sessions:
        s["message_count"] = len(s.get("messages", []))
        s.pop("messages", None)
        # Convert datetime for JSON
        if s.get("created_at"):
            s["created_at"] = s["created_at"].isoformat()
    return sessions