"""Fetch the eval feed universe into a flat corpus JSON.

Reuses the production parser (`news_ingestion._fetch_single_feed`) so the corpus
contains exactly what the app would have ingested — same field extraction, same
`content:encoded` handling, same image logic.
"""
import asyncio, json, os, sys, time
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import httpx
from app.services.news_ingestion import _fetch_single_feed
from evals.feeds import FEEDS

OUT = os.path.join(os.path.dirname(__file__), "corpus.json")


async def main():
    sem = asyncio.Semaphore(12)
    started = time.time()

    async with httpx.AsyncClient(timeout=25.0, follow_redirects=True) as client:
        async def one(name, url, vertical):
            async with sem:
                try:
                    arts = await _fetch_single_feed(client, url)
                except Exception as e:
                    return name, url, vertical, [], repr(e)[:80]
                return name, url, vertical, arts, None

        results = await asyncio.gather(*[one(*f) for f in FEEDS])

    corpus, seen = [], set()
    ok = dead = 0
    print(f"{'source':<20} {'vertical':<14} {'n':>4}  status")
    print("-" * 62)
    for name, url, vertical, arts, err in sorted(results, key=lambda r: r[2]):
        if err or not arts:
            dead += 1
            print(f"{name:<20} {vertical:<14} {0:>4}  DEAD {err or 'no entries'}")
            continue
        ok += 1
        kept = 0
        for a in arts:
            u = (a.get("url") or "").strip()
            if not u or u in seen or not a.get("title"):
                continue
            seen.add(u)
            pub = a.get("published_at")
            corpus.append({
                "id": f"a{len(corpus):05d}",
                "url": u,
                "title": a["title"],
                "summary": a.get("summary") or "",
                "content": (a.get("content") or "")[:4000],
                "source": name,
                "feed_vertical": vertical,
                "category": a.get("category") or vertical,
                "image_url": a.get("image_url"),
                "published_at": pub.isoformat() if isinstance(pub, datetime) else None,
            })
            kept += 1
        print(f"{name:<20} {vertical:<14} {kept:>4}  ok")

    with open(OUT, "w") as f:
        json.dump({
            "built_at": datetime.now(timezone.utc).isoformat(),
            "feeds_ok": ok, "feeds_dead": dead,
            "articles": corpus,
        }, f)

    print("-" * 62)
    print(f"{len(corpus)} unique articles from {ok} live feeds ({dead} dead) "
          f"in {time.time()-started:.1f}s")
    with_body = sum(1 for a in corpus if len(a["content"]) >= 600)
    print(f"full text already in feed: {with_body}/{len(corpus)} "
          f"({100*with_body/max(len(corpus),1):.0f}%)")
    print(f"-> {OUT}")

asyncio.run(main())
