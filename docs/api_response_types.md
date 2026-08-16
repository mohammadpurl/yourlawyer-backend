# API ``response_type`` values (AskResponse / ChatResponse)

## Values

| `response_type` | Meaning | Frontend suggestion |
|--|--|--|
| `grounded` | Answer built from retrieved legal chunks with citations | Current citation + confidence UI |
| `refused` | No usable grounded answer; user-facing refusal explanation | Neutral/error text, no fake citations |
| `general_guidance` | Level-3 orientation only (domain / general law name / see a lawyer) — **not** a legal holding | Amber/warning chrome + label «راهنمایی کلی — بدون استناد به سند خاص» |
| `canned` | Pre-RAG short-circuit (`is_canned_response: true`) for meta/greeting/out_of_scope | No citation list, no confidence badge; plain assistant message |

## Rules

- Never show `general_guidance` with the same visual weight as `grounded`.
- `sources` for `general_guidance` / `refused` / `canned` should be empty.
- `grounded` remains `false` for `refused`, `general_guidance`, and `canned`.
- When `is_canned_response` is true, also check `intent` (`meta_capability` / `greeting_chitchat` / `out_of_scope`).

Backend flags:
- `ENABLE_GENERAL_GUIDANCE_FALLBACK` (default `false`)
- `ENABLE_INTENT_DETECTION` (default `true`)
