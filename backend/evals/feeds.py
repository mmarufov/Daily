"""Feed universe for persona evaluation.

Deliberately broader than any one persona needs: each persona's signal has to be
found *among* the others' news plus general noise, which is the actual job.
"""

FEEDS = [
    # ── US national / general ──────────────────────────────────────────
    ("NPR",                "https://feeds.npr.org/1001/rss.xml",                          "general"),
    ("NPR World",          "https://feeds.npr.org/1004/rss.xml",                          "world"),
    ("BBC",                "https://feeds.bbci.co.uk/news/rss.xml",                       "general"),
    ("BBC World",          "https://feeds.bbci.co.uk/news/world/rss.xml",                 "world"),
    ("Guardian US",        "https://www.theguardian.com/us-news/rss",                     "general"),
    ("Guardian World",     "https://www.theguardian.com/world/rss",                       "world"),
    ("Al Jazeera",         "https://www.aljazeera.com/xml/rss/all.xml",                   "world"),
    ("DW",                 "https://rss.dw.com/rdf/rss-en-all",                           "world"),

    # ── New Jersey / NY metro (persona 1) ──────────────────────────────
    ("NJ.com",             "https://www.nj.com/arc/outboundfeeds/rss/?outputType=xml",    "local-nj"),
    ("NJ Spotlight",       "https://www.njspotlightnews.org/feed/",                       "local-nj"),
    ("Gothamist",          "https://gothamist.com/feed",                                  "local-nj"),
    ("NJ Monitor",         "https://newjerseymonitor.com/feed/",                          "local-nj"),

    # ── Sports / NHL (persona 1) ───────────────────────────────────────
    ("ESPN",               "https://www.espn.com/espn/rss/news",                          "sports"),
    ("ESPN NHL",           "https://www.espn.com/espn/rss/nhl/news",                      "sports"),
    ("ESPN NFL",           "https://www.espn.com/espn/rss/nfl/news",                      "sports"),
    ("CBS Sports NHL",     "https://www.cbssports.com/rss/headlines/nhl/",                "sports"),
    ("Yahoo Sports NHL",   "https://sports.yahoo.com/nhl/rss.xml",                        "sports"),

    # ── Tech / software engineering (persona 2) ────────────────────────
    ("Ars Technica",       "https://feeds.arstechnica.com/arstechnica/index",             "technology"),
    ("The Verge",          "https://www.theverge.com/rss/index.xml",                      "technology"),
    ("TechCrunch",         "https://techcrunch.com/feed/",                                "technology"),
    ("Wired",              "https://www.wired.com/feed/rss",                              "technology"),
    ("Hacker News",        "https://news.ycombinator.com/rss",                            "programming"),
    ("InfoQ",              "https://feed.infoq.com/",                                     "programming"),
    ("The Register",       "https://www.theregister.com/headlines.atom",                  "technology"),
    ("Engadget",           "https://www.engadget.com/rss.xml",                            "technology"),
    ("ZDNet",              "https://www.zdnet.com/news/rss.xml",                          "technology"),
    ("BleepingComputer",   "https://www.bleepingcomputer.com/feed/",                      "cybersecurity"),

    # ── Singapore / Southeast Asia (persona 2) ─────────────────────────
    ("Straits Times",      "https://www.straitstimes.com/news/singapore/rss.xml",         "singapore"),
    ("CNA Singapore",      "https://www.channelnewsasia.com/api/v1/rss-outbound-feed?_format=xml&category=10416", "singapore"),
    ("Business Times SG",  "https://www.businesstimes.com.sg/rss/singapore",              "singapore"),
    ("e27",                "https://e27.co/feed/",                                        "singapore"),

    # ── Central Asia / Russia / Eurasia (persona 3) ────────────────────
    ("Eurasianet",         "https://eurasianet.org/rss",                                  "central-asia"),
    ("The Diplomat",       "https://thediplomat.com/feed/",                               "central-asia"),
    ("Astana Times",       "https://astanatimes.com/feed/",                               "central-asia"),
    ("Times of Cent.Asia", "https://timesca.com/feed/",                                   "central-asia"),
    ("Asia-Plus TJ",       "https://asiaplustj.info/en/rss.xml",                          "central-asia"),
    ("Moscow Times",       "https://www.themoscowtimes.com/rss/news",                     "russia"),
    ("bne IntelliNews",    "https://www.intellinews.com/feed",                            "central-asia"),
    ("Meduza EN",          "https://meduza.io/rss/en/all",                                "russia"),

    # ── Business / finance (personas 2 & 3) ────────────────────────────
    ("CNBC",               "https://www.cnbc.com/id/100003114/device/rss/rss.html",       "business"),
    ("Fortune",            "https://fortune.com/feed/",                                   "business"),
    ("Guardian Business",  "https://www.theguardian.com/business/rss",                    "business"),
    ("MarketWatch",        "https://feeds.content.dowjones.io/public/rss/mw_topstories",  "business"),

    # ── Noise: none of the personas asked for these ────────────────────
    ("Polygon",            "https://www.polygon.com/rss/index.xml",                       "gaming"),
    ("PC Gamer",           "https://www.pcgamer.com/rss/",                                "gaming"),
    ("Variety",            "https://variety.com/feed/",                                   "entertainment"),
    ("Hollywood Reporter", "https://www.hollywoodreporter.com/feed/",                     "entertainment"),
    ("ScienceDaily",       "https://www.sciencedaily.com/rss/all.xml",                    "science"),
    ("Space.com",          "https://www.space.com/feeds/all",                             "space"),
    ("Guardian Culture",   "https://www.theguardian.com/culture/rss",                     "entertainment"),
    ("CoinDesk",           "https://www.coindesk.com/arc/outboundfeeds/rss/",             "crypto"),
]
