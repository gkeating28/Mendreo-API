# Mood check-ins API

Frontend reference for the dedicated mood tracking endpoints.

**Auth:** `Authorization: Bearer <access_token>`  
**Base path:** `/mood-entries`  
**Content-Type:** `application/json`

Multiple entries per day are allowed. Timestamp is `created_at`.

> This is separate from `GET /progress/mood` (older Knowledge 0–10 chart). Use `/mood-entries` for the 1–5 check-in flow.

---

## Score scale

| `mood_score` | `mood_label` |
|---|---|
| `1` | Low |
| `2` | Flat |
| `3` | Okay |
| `4` | Good |
| `5` | Great |

---

## Endpoints

| Method | Path | Description |
|---|---|---|
| `POST` | `/mood-entries` | Create a mood entry |
| `GET` | `/mood-entries` | List mood entries |
| `GET` | `/mood-entries/<id>` | Get one entry |
| `PATCH` | `/mood-entries/<id>` | Update an entry |
| `DELETE` | `/mood-entries/<id>` | Soft-delete an entry |

Consumers can only access their own entries.

---

## Create

`POST /mood-entries`

### Request body

```json
{
  "mood_score": 4,
  "note": "Felt steady after a walk"
}
```

| Field | Type | Required | Notes |
|---|---|---|---|
| `mood_score` | integer | Yes | `1`–`5` |
| `note` | string | No | Omit or `""` if empty |

Do **not** send `consumer` from the consumer/mobile app — the API sets it from the JWT.

### Response `201`

```json
{
  "id": "mood_xxxxxxxx",
  "consumer": "usr_xxxxxxxx",
  "mood_score": 4,
  "mood_label": "Good",
  "note": "Felt steady after a walk",
  "created_at": "2026-08-09T12:34:56.789012Z",
  "updated_at": "2026-08-09T12:34:56.789012Z"
}
```

---

## List

`GET /mood-entries`

### Query params

| Param | Description |
|---|---|
| `paginated=false` | Return a plain array (recommended for simple UIs) |
| `mood_score` | Filter by score (`1`–`5`) |
| `from` | Start date `YYYY-MM-DD` (filters on `created_at` date) |
| `to` | End date `YYYY-MM-DD` |
| `page_size` | Page size when paginated |
| `order_by` | e.g. `-created_at` (default newest first) |

### Example

```http
GET /mood-entries?paginated=false&from=2026-08-01&to=2026-08-09
```

### Response `200` (`paginated=false`)

```json
[
  {
    "id": "mood_xxxxxxxx",
    "consumer": "usr_xxxxxxxx",
    "mood_score": 4,
    "mood_label": "Good",
    "note": "Felt steady after a walk",
    "created_at": "2026-08-09T12:34:56.789012Z",
    "updated_at": "2026-08-09T12:34:56.789012Z"
  }
]
```

---

## Get one

`GET /mood-entries/<id>`

### Response `200`

Same object shape as create.

---

## Update

`PATCH /mood-entries/<id>`

### Request body

```json
{
  "mood_score": 5,
  "note": "Better now"
}
```

Both fields are optional.

### Response `200`

Updated object (same shape as create).

---

## Delete

`DELETE /mood-entries/<id>`

### Response

`204 No Content` (soft delete)

---

## Errors

| Status | When |
|---|---|
| `400` | Invalid `mood_score` (not 1–5) or bad payload |
| `401` | Missing/invalid token |
| `403` | Not allowed |
| `404` | Entry not found / not owned by this user |

---

## Suggested UI mapping

| UI element | API field |
|---|---|
| Score control (1–5) | `mood_score` |
| Display label | `mood_label` (or local map above) |
| Text box | `note` |
| Timestamp display | `created_at` |
| History list | `GET /mood-entries?paginated=false` (optional `from` / `to`) |
