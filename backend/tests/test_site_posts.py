"""marketing/site_posts.py: which sitemap URLs are posts, and reading a post page."""
from datetime import datetime

from marketing import site_posts

SITE = {"key": "COGENTIX", "url": "https://cogentixresearch.com", "prefix": "/blog/"}
PANEL = {"key": "SFW", "url": "https://surveyfieldwork.com", "prefix": "/blog/"}


def test_blog_urls_keeps_posts_only():
    xml = """<urlset><url><loc>https://cogentixresearch.com/</loc></url>
      <url><loc>https://cogentixresearch.com/blog.html</loc></url>
      <url><loc>https://cogentixresearch.com/blog/esg-consumer-insights.html</loc></url>
      <url><loc> https://cogentixresearch.com/blog/fmcg-market-research.html </loc></url>
      <url><loc>https://cogentixresearch.com/panel.html</loc></url></urlset>"""
    assert site_posts.blog_urls(SITE, xml) == ["https://cogentixresearch.com/blog/esg-consumer-insights.html",
                                               "https://cogentixresearch.com/blog/fmcg-market-research.html"]


def test_blog_urls_skips_the_blog_index():
    xml = "<loc>https://surveyfieldwork.com/blog/</loc><loc>https://surveyfieldwork.com/blog/paid-online-surveys-us</loc>"
    assert site_posts.blog_urls(PANEL, xml) == ["https://surveyfieldwork.com/blog/paid-online-surveys-us"]
    assert site_posts.blog_urls(PANEL, None) == []


def test_page_meta_reads_title_description_and_dates():
    html = """<head><title>Long title | Brand</title><meta name="description" content="What it is &amp; why.">
      <meta property="article:published_time" content="2026-11-27">
      <script type="application/ld+json">{"dateModified": "2026-11-28T10:00:00Z"}</script></head>
      <body><h1>Brand tracking <em>essentials</em></h1></body>"""
    m = site_posts.page_meta(html)
    assert m["title"] == "Brand tracking essentials"
    assert m["excerpt"] == "What it is & why."
    assert m["published_at"] == datetime(2026, 11, 27)
    assert m["modified_at"] == datetime(2026, 11, 28, 10, 0)


def test_page_meta_tolerates_missing_fields():
    assert site_posts.page_meta("")["title"] == ""
    assert site_posts.page_meta("<title>Only title</title>")["published_at"] is None
