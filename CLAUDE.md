# CLAUDE.md — وکیل تو (yourlawyer-backend)

این فایل راهنمای Claude Code برای کار روی این ریپوست. قبل از هر تغییر در pipeline بخوان.

## پروژه چیست

بک‌اند RAG حقوقی فارسی برای قوانین جمهوری اسلامی ایران.
Stack: FastAPI + LangChain + Chroma (vector DB) + Postgres (ذخیره مکالمات) + Redis (کش).
مزیت اصلی محصول: **پاسخ قابل‌ردیابی و مستند** به ماده/قانون، نه پاسخ عمومی از دانش مدل.

## اصل غیرقابل‌مذاکره پروژه

> **هیچ تغییری در pipeline (embedding، chunking، retrieval، threshold، prompt) بدون اجرای
> `eval/run_questions_eval.py` قبل و بعد از تغییر، و مقایسه با baseline انجام نشود.**

این یعنی:
- قبل از هر PR که فایل‌های زیر را لمس می‌کند، baseline فعلی را از `eval/results/baseline_roadmap.json`
  بخوان و بعد از تغییر، run جدید را با آن مقایسه کن:
  `app/services/rag.py`, `app/services/ingestion.py`, `app/services/enhanced_retrieval.py`,
  `app/services/reranker.py`, `app/services/vectorstore.py`, `app/core/config.py`
- افت answered-rate یا میانگین relevance score بیش از حد آستانه (فعلاً پیشنهادی ۵٪) یعنی تغییر را
  rollback کن یا دلیل افت را توضیح بده، نه این‌که مستقیم merge شود.
- هیچ threshold (مثل `MIN_SOURCE_RELEVANCE_SCORE`) را بدون دلیل مکتوب و بدون baseline جدید تغییر نده.

## معماری pipeline (وضعیت فعلی، تأییدشده با کد)

```
Ingestion (PDF/DOCX/TXT)
  → normalize_persian_pdf_text (NFKC + ی/ک)  [فقط روی PDF ingest, نه DOCX/TXT, نه query]
  → _legal_chunk_documents (chunk بر اساس ماده/اصل/تبصره؛ fallback به RecursiveCharacterTextSplitter)
  → _build_chunk_metadata (source, domain, article_number, content_hash, ...)
  → prefix_passage("passage: " + text) → embed با intfloat/multilingual-e5-base → Chroma (legal-texts-v2)

Query
  → prefix_query("query: " + question) → dense search (Chroma, top_k=8)
  → rerank با CrossEncoder mmarco-mMiniLMv2-L12-H384-v1، فیلتر MIN_SOURCE_RELEVANCE_SCORE=0.15
  → (اگر context خالی/زیر آستانه) → refusal_guidance → پیام امتناع یا general_guidance (فعلاً OFF)
  → PERSIAN_LEGAL_SYSTEM_PROMPT (grounded، ممنوعیت استفاده از دانش عمومی) → LLM → validate_citations
```

فایل‌های کلیدی:
- `app/core/config.py` — همه env vars و threshold ها
- `app/services/ingestion.py` — normalize، chunk، metadata
- `app/services/vectorstore.py` — embedding model، prefix_query/prefix_passage
- `app/services/enhanced_retrieval.py` — retrieval logic
- `app/services/reranker.py` — CrossEncoder rerank
- `app/services/rag.py` — orchestration، prompt، fallback، citation validation
- `app/services/refusal_guidance.py` — پیام‌های امتناع، general guidance
- `app/services/query_trace.py` — لاگ `refusal_reason` برای مانیتورینگ
- `eval/run_questions_eval.py`, `eval/questions.jsonl` (۱۲۰ سؤال واقعی), `eval/hard_questions_eval_set.jsonl`

## مشکلات شناخته‌شده — قبل از کار روی این‌ها اطلاع بده، بدون تأیید fix نکن

| مشکل | وضعیت | severity |
|---|---|---|
| نرمال‌سازی فارسی (NFKC + ی/ک) روی query کاربر اعمال نمی‌شود، فقط روی PDF ingest | ✅ رفع شد (۲۰۲۶-۰۸-۲۳، `text_normalize.py` مشترک بین ingest و query) | — |
| نتایج eval در `.gitignore`، هیچ CI gate روی PRهای pipeline نیست | فرآیندی، هنوز رفع نشده (`baseline_locked.json` هم gitignore است) | **بحرانی** |
| Hybrid dense+BM25 در retrieval | ✅ پیاده و فعال شد (۲۰۲۶-۰۸-۲۳، `ENABLE_HYBRID_RETRIEVAL=true`) — قبل از رسیدن unclassified به زیر ۲۰٪ به‌درخواست صریح کاربر، چون evidence نشان داد dense-only حتی در top-200 هم چانک درست را برای اصطلاحات خاص (مثل «هبه») پیدا نمی‌کرد | — |
| ~۳۳٪ chunkها `unclassified` (domain) | ✅ به ۱۹.۳۳٪ رسید (۲۰۲۶-۰۸-۲۳، باگ نرمال‌سازی آ/ئ در الگوهای `domain_law_map.py` رفع شد + ~۲۰ قاعده جدید) — `scripts/backfill_domain_tags.py` روی corpus واقعی اجرا شد | کم — زیر آستانه ۲۰٪ |
| `ENABLE_DOMAIN_FILTERED_RETRIEVAL=false` | همچنان عمدی خاموش — کاهش unclassified این فلگ را خودکار روشن نکرد؛ روشن‌کردنش هنوز نیاز به درخواست صریح کاربر دارد | — |
| Fallback extractive وقتی هیچ LLM تنظیم نشده | fail-open (dump خام context) به‌جای fail-closed | متوسط |
| `ENABLE_GENERAL_GUIDANCE_FALLBACK=false` | عمدی، منتظر review دستی نمونه‌ها | کم |
| intent_detector «meta_capability» سؤالات درباره مفهوم سند را با درخواست تنظیم سند اشتباه می‌گرفت | ✅ رفع شد (۲۰۲۶-۰۸-۲۳، prompt دقیق‌تر شد) | — |

## قوانین کاری برای Claude Code در این ریپو

1. **قبل از خواندن یا تغییر فایل‌های pipeline، اول `eval/results/baseline_roadmap.json` و
   `docs/roadmap_status.md` (اگر هست) را بخوان** تا بدانی وضعیت فعلی چیست — حدس نزن.
2. هیچ‌وقت مقدار threshold (`MIN_SOURCE_RELEVANCE_SCORE`, `DEFAULT_TOP_K`, `CHUNK_SIZE`,
   `CHUNK_OVERLAP`, `GENERAL_GUIDANCE_MIN_CLASSIFY_CONFIDENCE`) را بدون درخواست صریح کاربر تغییر نده.
3. برای هر تغییر در `ingestion.py` یا `vectorstore.py`، چک کن که `prefix_query`/`prefix_passage`
   و نرمال‌سازی فارسی هنوز به‌طور یکسان در مسیر query و passage اعمال می‌شوند (نه فقط یکی).
4. flagهای `ENABLE_DOMAIN_FILTERED_RETRIEVAL` و `ENABLE_GENERAL_GUIDANCE_FALLBACK` را روشن نکن مگر
   کاربر صریحاً بخواهد — این‌ها عمداً خاموش نگه داشته شده‌اند تا معیار گیت رعایت شود.
5. هر تغییر کد در pipeline باید با یک پیشنهاد اجرای eval (قبل/بعد) همراه شود، حتی اگر خودِ اجرا را
   کاربر انجام دهد.
6. متن‌های حقوقی فارسی را هرگز حدس نزن یا از حافظه تولید نکن — فقط از corpus/retrieval استفاده کن.
7. تغییرات را commit نکن مگر درخواست صریح شود؛ diff را نشان بده و منتظر تأیید بمان.

## دستورهای مفید

```bash
# اجرای eval کامل (local/inprocess)
python eval/run_questions_eval.py --via inprocess --out eval/results/run_$(date +%s).json

# اجرای سریع (smoke, ۴۰ سؤال)
python eval/run_questions_eval.py --via inprocess --limit 40 --out eval/results/ci_smoke.json

# اجرای سرور
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

## Env vars مهم (پیش‌فرض‌ها را بدون دلیل عوض نکن)

```
EMBEDDING_MODEL=intfloat/multilingual-e5-base
DEFAULT_TOP_K=8
CHUNK_SIZE=800
CHUNK_OVERLAP=120
MIN_SOURCE_RELEVANCE_SCORE=0.15
ENABLE_DOMAIN_FILTERED_RETRIEVAL=false
ENABLE_GENERAL_GUIDANCE_FALLBACK=false
```
