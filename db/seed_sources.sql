INSERT INTO edge_ingest.sources (source_key, name, feed_url, enabled)
VALUES
  ('sciencedaily', 'ScienceDaily Top Technology', 'https://www.sciencedaily.com/rss/top/technology.xml', TRUE),
  ('arxiv',        'arXiv cs.AI RSS',            'https://rss.arxiv.org/rss/cs.AI', TRUE),
  ('bbc',          'BBC Technology (UK Edition)', 'http://newsrss.bbc.co.uk/rss/newsonline_uk_edition/technology/rss.xml', TRUE)
ON CONFLICT (feed_url) DO NOTHING;
