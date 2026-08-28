DA / PA / Spam Score exports go in THIS folder.

Accepted: .csv  .xlsx  .tsv  .txt   -- columns are auto-detected, so you never
need to rename a file or reorder anything.

Files named README / instructions / notes are SKIPPED, so this file is never
mistaken for data. (It used to be, and the example table below was parsed as
real metrics.)


Workflow
--------
1. Run an audit:

       python -m seo_audit

   It writes  output\da_pa_queue.txt  with the domains that need a lookup,
   already split into paste-ready batches.

   Note what is NOT in that file: anything already dead or already spam. Stages
   1 to 3 disqualify those before the DA/PA stage, so you only ever check the
   survivors. On a real batch of 20 domains that was 5 lookups instead of 20.

2. Open a bulk checker and paste ONE batch:

       https://tools.guestpostlinks.net/bulk-da-pa-checker-tool/   (100 per batch)
       https://www.dapachecker.org/
       https://dapacheckerpro.com/

3. Export or copy the result table into this folder.

4. Re-run the audit. Metrics are matched by registered domain and cached for 30
   days, so no domain is ever checked twice.


Formats understood automatically
--------------------------------
  URL,DA,PA,SS,TB,QB
  https://en.wikipedia.org/,98,82,1%,2340111,1900000

  Website,Domain Authority,Page Authority,Spam Score
  glassdoor.com,92,75,2

  example.com   45   38   5          <- headerless paste, tab or space separated

Percent signs, thousands separators and "N/A" are all handled. The header row
can sit anywhere in the first 25 rows, so a checker that prints a title above
its table is fine.


Prefer not to paste at all?
--------------------------
Set metrics.provider in config.yaml to moz, dataforseo or rapidapi, put the key
in .env, and this folder stops mattering. See the DA/PA section of README.md.
