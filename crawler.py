import hashlib
import re
from datetime import datetime
from crawl4ai import AsyncWebCrawler
from database import get_page, save_page, update_page

def make_website_id(url: str) -> str:
    name = re.sub(r'https?://', '', url)
    name = re.sub(r'[^a-zA-Z0-9]', '_', name)
    return f"site_{name[:50]}"

def generate_hash(content: str) -> str:
    return hashlib.md5(content.encode()).hexdigest()

async def crawl_website(url: str, website_id: str):
    total_pages = 0
    visited = set()
    to_visit = [url]

    async with AsyncWebCrawler() as crawler:
        while to_visit:
            current_url = to_visit.pop(0)

            if current_url in visited:
                continue

            visited.add(current_url)

            try:
                print(f"🔍 Crawling: {current_url}")
                result = await crawler.arun(url=current_url)

                if not result.success:
                    continue

                content = result.markdown or ""
                title = result.metadata.get("title", "") if result.metadata else ""
                links = result.links.get("internal", []) if result.links else []

                pdfs_found = []
                all_links = result.links.get("external", []) + links if result.links else []
                for link in all_links:
                    href = link.get("href", "")
                    if href.endswith(".pdf"):
                        pdfs_found.append({"name": href.split("/")[-1], "url": href})

                content_hash = generate_hash(content)
                link_urls = [l.get("href", "") for l in links if l.get("href")]

                for link_url in link_urls:
                    if link_url not in visited and url in link_url:
                        to_visit.append(link_url)

                # ── Change Detection ──
                existing_page = get_page(current_url)

                if existing_page is None:
                    save_page(website_id, {
                        "page_url": current_url,
                        "title": title,
                        "content": content,
                        "links_found": link_urls,
                        "pdfs_found": pdfs_found,
                        "content_hash": content_hash,
                        "is_updated": False,
                        "crawled_at": datetime.utcnow(),
                        "last_checked": datetime.utcnow()
                    })
                    total_pages += 1
                    print(f"✅ Saved: {current_url}")

                elif existing_page["content_hash"] != content_hash:
                    update_page(current_url, {
                        "title": title,
                        "content": content,
                        "content_hash": content_hash,
                        "links_found": link_urls,
                        "pdfs_found": pdfs_found,
                        "is_updated": True,
                        "last_checked": datetime.utcnow()
                    })
                    total_pages += 1
                    print(f"🔄 Updated: {current_url}")

                else:
                    print(f"⏭️ No change: {current_url}")

            except Exception as e:
                print(f"❌ Error: {current_url}: {e}")
                continue

    print(f"🎉 Done! Total pages: {total_pages}")
    return total_pages