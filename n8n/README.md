# n8n workflow

`ai-document-extractor.workflow.json` is the same pipeline as the Python service:

1. A PDF arrives (a manual sample, or an unread email attachment).
2. The text is read.
3. A model is asked only for the fields.
4. A code node checks required fields and sets the date status.
5. The row is appended to Google Sheets.
6. A separate daily branch emails rows whose date is inside 30 days.

Import it from the n8n menu: **Workflows → Import from File**. n8n may offer to update a node after import. Accept that, then attach credentials. Nothing in the file contains a real key.

## What you attach after import

| Node | Credential |
| --- | --- |
| Ask the model for fields | Header Auth. Name `Authorization`, value `Bearer YOUR_OPENAI_KEY`. |
| Append sheet row, Read sheet rows | Google Sheets. Put the spreadsheet ID on each sheet node. Share the sheet with that Google account. |
| New email | IMAP. Optional. If you skip email, use **Manual sample**. |
| Send reminder | SMTP. Change the from and to addresses on the node. |
| Alert Slack | Slack. Optional. The review branch can be deleted if you do not want it. |

The manual sample uses fictional Northwind text so you can see the shape of the data. Replace the expiry date if you want it inside a 30-day window on the day you try it.

## When to choose n8n

Choose n8n when the people who will change the workflow are comfortable in a visual editor, the steps are mostly “read a file, call a model, write a row, send mail,” and you want to adjust the window or the email text without a deploy.

It is a good fit when Google Sheets and the inbox already live in n8n, and the document layout is stable.

## When to choose the Python service

Choose the code in this repository when you need:

- a tested rule for status and reminders, with the tests in `tests/`
- retries and a schema check when the model returns a bad shape
- a review flag that code can raise even if the model is confident
- more than one document type, with the same storage and dashboard
- a run that works with no Google account and no API key (`make demo`)
- a place to put scanned-PDF handling, idempotent reprocessing, or a real database later

The workflow repeats the date rule in a code node on purpose. If that rule grows (business days, different windows per customer, “do not remind a row that failed review”), keep it in Python so one test covers it. You can still call the Python API from n8n with an HTTP node pointed at `POST /api/documents`.

## What this export does not do

It does not store a local CSV, and it does not include the offline mock extractor. Those live in the Python app so someone can try the project before creating API keys. The sheet nodes also do not update an existing row; the Python service upserts by id. For a first version, append is usually enough. Switch the sheet node to “update” when the same certificate might be processed twice.
