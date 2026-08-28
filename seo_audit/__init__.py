"""
SEO Backlink Audit.

A staged backlink auditor: check each link is live, check the page around it,
check the site around the page, and only then spend anything on authority
metrics.

Layout
------
    appconfig.py     config.yaml + .env loading
    inputs.py        reading backlink lists (csv / xlsx / txt)
    pipeline.py      the per-link stages, in order
    cli.py           command line entry point and orchestration

    net/             fetch ladder, DNS, robots.txt, browser rendering
    analysis/        domains, trust tiers, page analysis, spam, relevance,
                     home page, sitewide sampling, archive recovery
    scoring/         stage gates, composite score, anchors, link networks
    providers/       DA/PA metrics, hosting (ASN) lookups
    reporting/       reports, run-over-run diff, disavow diff
    store/           on-disk state (resume cache)
"""

__version__ = "2.0.0"
