# Deploy checklist: legal-texts-v2

## Server `.env` (manual — do not rely on repo alone)

```env
CHROMA_COLLECTION=legal-texts-v2
CHROMA_DB_DIR=/app/storage/chroma
```

Confirm on server before rebuild:
`grep CHROMA_COLLECTION .env`

Also sync the local Chroma persist dir that contains `legal-texts-v2`
(currently on this machine: `storage/chroma_old_backup`, ~2018 vectors after آیین‌نامه ingest)
into the server volume mounted at `./storage/chroma`.

## Deploy steps

1. `git pull` (on server)
2. Ensure server `.env` has `CHROMA_COLLECTION=legal-texts-v2`
3. Copy/rsync updated Chroma data into `./storage/chroma` if rebuilt locally
4. `docker compose up -d --build your-lowyer-backend`
5. Smoke tests on https://yourlawyeer.ir :
   - شرایط طلاق توافقی چیست
   - مهلت مرکز مشاوره خانواده برای تصمیم‌گیری چقدر است؟
6. Check backend logs for `PIPELINE_TIMING` and `stages.retrieve`

## Rollback

Set `CHROMA_COLLECTION=legal-texts` (old contaminated corpus) only if needed for emergency,
then restart the backend container.
