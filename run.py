import asyncio
import sys
import os

# Windows asyncio fix
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

# Load .env file
from dotenv import load_dotenv
load_dotenv()

import uvicorn

if __name__ == "__main__":
    print("🚀 Starting SiteIQ API Server...")
    print(f"   GROQ_API_KEY: {'✅ Set' if os.environ.get('GROQ_API_KEY') else '⚠️  Not set (fallback mode)'}")
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=False)