"""SQLite persistence: schema, migrations, lap-blob storage, eviction.

Built in M2. Raw lap samples are stored as one compressed blob per lap
(nothing queries individual samples by SQL); everything queryable — lap
metadata, quality flags, corner landmarks, metric values, findings, evidence
refs, reference envelopes, sync state, coaching outputs, chat transcripts,
config history — lives in compact relational rows. Retention: newest 100 raw
laps per driver/car/track cohort; compact summaries are permanent; eviction is
transactional and preserves trend contributions. Migrations under test.
"""
