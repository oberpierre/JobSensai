**Board**:
One start URL, fetched as one source per crawl. A source that filters and pages on its side gets one board per region, and a source that answers with everything at once gets a single board whose regions are repeated `filter.` values.
_Avoid_: site, career page, feed

**Start URL**:
A board's configured URL, as entered on the admin screen, `filter.` parameters included.
_Avoid_: board URL, feed URL

**Request URL**:
The start URL as actually sent, with its `filter.` parameters removed.
_Avoid_: fetch URL

**Posting URL**:
A posting's identity, the page a candidate opens, stored as the `url` column in Bronze and Silver.
_Avoid_: job link, detail URL

**Content URL**:
Where an index mapping says a posting's content is fetched from, when that differs from its posting URL.
_Avoid_: detail URL, fetch URL

**Source URL**:
The response a Bronze row's content was taken from: the request URL for a posting already in a feed, otherwise the posting URL or content URL that was fetched.
_Avoid_: origin URL
