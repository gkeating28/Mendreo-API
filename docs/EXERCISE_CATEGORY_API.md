# Exercise category API

Frontend reference for attaching a `category` to exercises and filtering the list.

**Auth:** `Authorization: Bearer <access_token>`  
**Base path:** `/exercises`  
**Content-Type:** `application/json`

`category` is an optional free-text string (`max_length` 255). Matching on list is **case-insensitive**.

---

## Endpoints that include `category`

| Method | Path | Who | Notes |
|---|---|---|---|
| `POST` | `/exercises` | Admin | Set `category` on create |
| `GET` | `/exercises` | Consumer / Admin | List includes `category`; filter with `?category=` |
| `GET` | `/exercises/<id>` | Consumer / Admin | Detail includes `category` |
| `PATCH` | `/exercises/<id>` | Admin | Update `category` |

Consumers only receive **published** exercises on list/detail.

---

## Create (admin)

`POST /exercises`

### Request body (category-relevant fields highlighted)

```json
{
  "title": "Flexible Thinking",
  "subtitle": "Interpreting a situation",
  "category": "Thinking",
  "description": "Exercise authoring / coach instructions…",
  "status": "published",
  "icon": "leaf",
  "icon_svg": null,
  "icon_background_color": "tan",
  "pre_exercise_enabled": false,
  "pre_exercise_description": null,
  "pre_exercise_instruction": null,
  "pre_exercise_goal": null,
  "pre_exercise_completion_prompt": null,
  "pre_exercise_start_button_label": "Start exercise",
  "steps": [
    {
      "tags": [],
      "title": "Step 1",
      "description": "…",
      "instructions": "…",
      "completion_criteria": "…",
      "completion_label": "…",
      "completion_prompt": "…",
      "success_title": "Well Done!"
    }
  ],
  "questions": []
}
```

| Field | Type | Required | Notes |
|---|---|---|---|
| `category` | string | No | Omit or `""` if unset. Max 255 chars. |
| `title` | string | Yes | |
| `subtitle` | string | Yes | |
| `description` | string | Yes | |
| `status` | string | Yes | `draft` \| `archived` \| `published` |
| `icon` | string | Yes | |
| `icon_svg` | string \| null | No | |
| `icon_background_color` | string | Yes | |
| `steps` | array | Yes | Non-empty |
| `questions` | array | No | |
| `pre_exercise_*` | mixed | No | Existing pre-exercise fields |

### Response `201` (admin detail shape)

```json
{
  "id": "exrcs_xxxxxxxx",
  "title": "Flexible Thinking",
  "subtitle": "Interpreting a situation",
  "category": "Thinking",
  "icon": "leaf",
  "icon_svg": null,
  "icon_background_color": "tan",
  "steps_no": 1,
  "order": 1,
  "created_at": "2026-08-09T12:34:56.789012Z",
  "updated_at": "2026-08-09T12:34:56.789012Z",
  "average_duration": 300,
  "pre_exercise_enabled": false,
  "pre_exercise_start_button_label": "Start exercise",
  "status": "published",
  "description": "Exercise authoring / coach instructions…",
  "completions_no": 0,
  "steps": [
    {
      "id": "step_xxxxxxxx",
      "tags": [],
      "title": "Step 1",
      "description": "…",
      "instructions": "…",
      "completion_criteria": "…",
      "completion_label": "…",
      "completion_prompt": "…",
      "average_duration": 300,
      "success_title": "Well Done!"
    }
  ],
  "questions": [],
  "pre_exercise_description": null,
  "pre_exercise_instruction": null,
  "pre_exercise_goal": null,
  "pre_exercise_completion_prompt": null
}
```

---

## List (consumer / admin)

`GET /exercises`

### Query params

| Param | Description |
|---|---|
| `category` | Case-insensitive exact match, e.g. `Thinking` |
| `paginated=false` | Return a plain array (recommended for simple UIs) |
| `search_term` | Title contains (existing) |
| `status` | Admin only (`draft` / `archived` / `published`). Consumers are forced to `published`. |
| `pre_exercise` | `all` \| `enabled` \| `disabled` (existing) |
| `page_size` | When paginated |
| `order_by` | e.g. `order` |

### Example

```http
GET /exercises?category=Mindfulness&paginated=false
```

### Response `200` — consumer list item (`paginated=false`)

```json
[
  {
    "id": "exrcs_xxxxxxxx",
    "title": "Breathing",
    "subtitle": "A short reset",
    "category": "Mindfulness",
    "icon": "leaf",
    "icon_svg": null,
    "icon_background_color": "tan",
    "steps_no": 3,
    "order": 1,
    "created_at": "2026-08-09T12:34:56.789012Z",
    "updated_at": "2026-08-09T12:34:56.789012Z",
    "average_duration": 900,
    "pre_exercise_enabled": true,
    "pre_exercise_start_button_label": "Start exercise"
  }
]
```

### Admin list extras

Admin list responses also include:

```json
{
  "status": "published",
  "description": "…",
  "completions_no": 12
}
```

(plus the consumer list fields above, including `category`).

---

## Get one

`GET /exercises/<id>`

### Response `200` — consumer detail

Consumer list fields **plus**:

```json
{
  "id": "exrcs_xxxxxxxx",
  "title": "Breathing",
  "subtitle": "A short reset",
  "category": "Mindfulness",
  "icon": "leaf",
  "icon_svg": null,
  "icon_background_color": "tan",
  "steps_no": 3,
  "order": 1,
  "created_at": "2026-08-09T12:34:56.789012Z",
  "updated_at": "2026-08-09T12:34:56.789012Z",
  "average_duration": 900,
  "pre_exercise_enabled": true,
  "pre_exercise_start_button_label": "Start exercise",
  "description": "…",
  "steps": [],
  "questions": [],
  "pre_exercise_description": null,
  "pre_exercise_instruction": null,
  "pre_exercise_goal": null,
  "pre_exercise_completion_prompt": null
}
```

Admin detail also includes `status`, `completions_no`, and fuller step admin fields.

---

## Update category (admin)

`PATCH /exercises/<id>`

### Request body

```json
{
  "category": "Sleep"
}
```

`category` is optional on PATCH (along with other exercise fields). You can send only `category` to change it.

### Response `200`

Updated exercise object (admin detail shape), including the new `category`.

---

## Suggested UI mapping

| UI | API |
|---|---|
| Category picker / text on create form | `category` in `POST /exercises` |
| Category chips / filter tabs on exercise library | `GET /exercises?category=<name>&paginated=false` |
| Show category on cards | `category` from list/detail |
| Edit category in admin | `PATCH /exercises/<id>` with `{ "category": "…" }` |

---

## Errors

| Status | When |
|---|---|
| `400` | Invalid create/edit payload |
| `401` | Missing/invalid token |
| `403` | Consumer trying to create/edit; or role missing exercise permission |
| `404` | Exercise not found (or not published for consumer) |
