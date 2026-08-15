# API ``response_type`` values (AskResponse / ChatResponse)

## Values

| `response_type` | Meaning | Frontend suggestion |
|--|--|--|
| `grounded` | Answer built from retrieved legal chunks with citations | Current citation + confidence UI |
| `refused` | No usable grounded answer; user-facing refusal explanation | Neutral/error text, no fake citations |
| `general_guidance` | Level-3 orientation only (domain / general law name / see a lawyer) — **not** a legal holding | Amber/warning chrome + label «راهنمایی کلی — بدون استناد به سند خاص» |

## Rules

- Never show `general_guidance` with the same visual weight as `grounded`.
- `sources` for `general_guidance` / `refused` should be empty.
- `grounded` remains `false` for both `refused` and `general_guidance`.

Backend flag: `ENABLE_GENERAL_GUIDANCE_FALLBACK` (default `false`).
