# Mendreo API & Database Deep Dive

This document is a deep technical companion to [`API.md`](./API.md). Where `API.md`
is a shallow endpoint reference (method / path / purpose), this document explains,
for every API module under `mendreo/api/*`:

- the models behind each endpoint and their fields/relationships,
- the exact database **reads** (querysets, filters, related lookups) each endpoint performs,
- the exact database **writes** (creates, updates, soft-deletes) each endpoint performs,
- the shared `Smart*` view machinery that governs filtering, pagination, transactions,
  soft-deletes and PII obscuring, and
- the non-CRUD flows (sessions, the message → LLM → write loop, exercise duplication,
  Supabase Storage uploads, Stripe subscriptions) and which of their side effects hit the DB vs. an
  external system.

Everything below was verified against the source in `mendreo/api/`.

---

## 1. Data-model overview

All domain models inherit `SmartModel` (`api/utils/Models.py`), an abstract base that adds:

- `deleted_at` (nullable, indexed) — soft-delete marker,
- `updated_at` (`auto_now`, indexed),
- `created_at` (`auto_now_add`, indexed),
- two managers: `objects` (alive rows only, `deleted_at IS NULL`) and `all_objects`
  (every row including soft-deleted),
- `delete()` overridden to set `deleted_at = now()` and `save()` (a soft delete),
  plus `hard_delete()` for a real SQL `DELETE`.

Primary keys are CUID strings via `CharIDField` (`api/utils/Fields.py`), each model using a
human-readable prefix (e.g. `usr_`, `ssn_`, `msg_`, `exrcs_`). `EnumField` is a
`varchar(255)` with Python-side `choices`.

### 1.1 Identity & access

| Model | PK / key fields | Important relationships |
|---|---|---|
| **User** (`api/user/models.py`) | `id` (`usr_`), `email` (unique), `type` (`consumer`/`admin`), `first_name`, `last_name`, `full_name` (computed on save, indexed), `password`, `status` (`active`/`suspended`), `email_verified`, `verification_code`, `verification_code_sent_at`, `last_seen`, `phone_*` | `AbstractBaseUser`; `USERNAME_FIELD = email`. Owns `consumer` / `admin` (OneToOne, reverse). Note: it declares its own `deleted_at`/`created_at`/`updated_at` (it does **not** inherit `SmartModel`). |
| **Admin** (`api/admin/models.py`) | `user` (OneToOne PK) | `role` → `Role` (`SET_NULL`). |
| **Consumer** (`api/consumer/models.py`) | `user` (OneToOne PK) | `agent` → `Agent` (`DO_NOTHING`); `stripe_customer_id`; `date_of_birth`; `onboarded`; `surveyed`; `last_onboarding_flow_completed_at`; `last_onboarding_flow_variant`. Reverse: `attributes`, `sessions`, `participants`, `events`, `subscription`, `summary`, `exercise_summaries`, `payments`, `knowledge_entries`, `observations`. |
| **Role** (`api/role/models.py`) | `id` (`rol_`), `name`, `is_default` | OneToOne `permissions`. |
| **Permissions** (`api/permissions/models.py`) | `role` (OneToOne PK) | Array columns: `users`, `sessions`, `signups`, `feedback`, `exercises`, `assets`, `questions`, `roles`, `pii`, `knowledge`. Each holds a subset of `view/create/edit/delete`. |

### 1.2 Agent / AI configuration

| Model | Key fields | Relationships |
|---|---|---|
| **Agent** (`api/agent/models.py`) | `id` (`agt_`), `name`, `default`, `description`, `model` (default `gemini-2.5-flash`), `context`, `consumers_no` | `avatar` OneToOne → `Image` (`DO_NOTHING`); `created_by` → `User`. Reverse `consumers`, `participants`. |

### 1.3 Sessions, messages, participants

| Model | Key fields | Relationships |
|---|---|---|
| **Session** (`api/session/models.py`) | `id` (`ssn_`), `messages_no`, `consumer_messages_no`, `agent_messages_no`, `subject`, `rating` (Decimal 0–10), `rating_reason`, `risk_level` (enum), `total_steps_no`, `completed`, `current_step_no` (0 during pre-exercise check-in), `cached_prompt` (Text), `cached_history` (JSON), `usage` (JSON), `pre_exercise_prompt_summary`, `pre_exercise_completed_at` | `consumer` → `Consumer`; `last_asset` → `Asset` (`SET_NULL`); `last_message` → `Message` (`SET_NULL`); `exercise` → `Exercise` (`SET_NULL`). Reverse `messages`, `participants`, `session_steps`, `questions`, `knowledge_entries`. |
| **SessionStep** (`api/session/models.py`) | `id` (`ssnstp_`), `completed`, `completion_label`, `completion_result`, `order` | `step` → `Step`; `session` → `Session`; `last_asset` → `Asset`. |
| **Participant** (`api/participant/models.py`) | `id` (`ptcp_`) | `consumer` (nullable), `agent` (nullable), `session`. One participant row per (consumer or agent) per session. |
| **Message** (`api/message/models.py`) | `id` (`msg_`), `text`, `reasoning`, `suggested_responses` (ArrayField), `step_no`, `completion_label`, `completion_result`, `is_step_complete`, `usage` (JSON) | `session` → `Session`; `sender` → `Participant`; `asset` → `Asset` (`SET_NULL`); `exercise` → `Exercise` (`SET_NULL`). |
| **Summary** (`api/summary/models.py`) | `consumer` (OneToOne PK), `detailed`, `observations`, `next_steps` | Per-consumer rolling AI summary. |

### 1.4 Exercises & content

| Model | Key fields | Relationships |
|---|---|---|
| **Exercise** (`api/exercise/models.py`) | `id` (`exrcs_`), `title`, `subtitle`, `description`, `status` (`draft`/`archived`/`published`), `steps_no`, `icon`, `icon_svg`, `icon_background_color`, `completions_no`, `average_duration`, `order`, `pre_exercise_enabled`, `pre_exercise_description`, `pre_exercise_instruction`, `pre_exercise_goal`, `pre_exercise_completion_prompt`, `pre_exercise_start_button_label` | Reverse `steps`, `questions`, `sessions`, `messages`, `exercise_summaries`. |
| **Step** (`api/step/models.py`) | `id` (`step_`), `title`, `description`, `instructions`, `completion_criteria`, `completion_label`, `completion_prompt`, `order`, `average_duration`, `success_title` | `exercise` → `Exercise`; `tags` M2M → `Tag`. |
| **Question** (`api/question/models.py`) | `id` (`qstn_`), `type` (incl. `slider`), `attribute_key`, `title`, `suggested_responses` (Array), `order`, `survey`, `pre_exercise` (form flag ≠ exercise pre-exercise prompt), `can_complete_exercise`, `complete_on_value`, `complete_text`, `anchor_labels`, `value_labels`, `min_selections`, `max_selections` | `exercise` → `Exercise` (nullable); `session` → `Session` (nullable). Reverse `attributes`. |
| **Attribute** (`api/attribute/models.py`) | `id` (`attr_`), `key`, `value` | `consumer` → `Consumer`; `question` → `Question`. A consumer's stored answer to a question. |
| **ExerciseSummary** (`api/exercise_summary/models.py`) | `id` (`exsmry_`), `detailed`, `observations`, `next_steps` | `consumer` → `Consumer`; `exercise` → `Exercise`. |
| **Post** (`api/post/models.py`) | `id` (`pst_`), `status`, `type` (`video`/`podcast`/`article`), `published_at`, `title`, `subtitle`, `body`, `views_no`, `impressions_no` | `created_by` → `User`; `thumbnail`/`banner` → `Image` (`DO_NOTHING`); `file` → `File` (`SET_NULL`). |
| **Asset** (`api/asset/models.py`) | `id` (`ast_`), `context` | Nullable FKs `post`, `file`, `image`; `tags` M2M → `Tag`. A polymorphic content wrapper the AI can surface. |
| **Tag** (`api/tag/models.py`) | `id` (`tag_`), `name` | M2M targets from `Asset`, `Step`. |
| **Event** (`api/event/models.py`) | `id` (`evt_`), `type` (`view`/`impression`) | `consumer` → `Consumer`; `post` → `Post`. Analytics rows; bumps `Post.views_no`/`impressions_no`. |
| **Feedback** (`api/feedback/models.py`) | `id` (`fdbk_`), `positive`, `reason`, `value` | `user` → `User`; `message` → `Message`. |

### 1.5 Media

| Model | Key fields | Relationships |
|---|---|---|
| **Image** (`api/image/models.py`) | `id` (`img_`), `original` (Supabase Storage key), `name`, `width`, `height`, `blur_hash`, `uploaded`, `extension`, `size`, `token` | `created_by` → `User` (`CASCADE`). `Image.generate()` calls the AI image API and uploads to Supabase Storage. |
| **File** (`api/file/models.py`) | `id` (`file_`), `name`, `extension`, `content_type`, `url`, `size`, `duration`, `token`, `uploaded` | `created_by` → `User` (`DO_NOTHING`). `get_url()` prefixes the Supabase Storage public object URL. |

### 1.6 Billing

| Model | Key fields | Relationships |
|---|---|---|
| **Currency** (`api/currency/models.py`) | `id` (`cur_`), `name`, `symbol`, `code`, `iso_code` | — |
| **Price** (`api/price/models.py`) | `id` (`prc_`), `amount`, `frequency` (`monthly`/`yearly`), `apple_id`, `google_id` | `currency` → `Currency`. |
| **Package** (`api/package/models.py`) | `id` (`pkg_`), `title`, `default` | `price` → `Price`. `get_default()` returns the free (`amount=0`, `default=True`) package. |
| **Payment** (`api/payment/models.py`) | `id` (`pay_`), Apple/Google/Stripe receipt & subscription IDs (unique, some md5-hashed on save) | `price` → `Price`; `consumer` → `Consumer`. |
| **Subscription** (`api/subscription/models.py`) | `consumer` (OneToOne PK), `title`, `active`, `subscribed_at`, `unsubscribed_at`, `last_checked_at` | `payment` OneToOne → `Payment` (nullable); `package` → `Package`. `Subscription.create()` seeds a default inactive sub. |
| **Setting** (`api/setting/models.py`) | `id` (`stng_`), `key` (unique), `value` | Key/value config: `survey_enabled`, `general_prompt`, `therapeutic_prompt`, `refresh_onboarding_cadence_days`, `observations_enabled`, `observations_instruction`, `observations_tone_guide`, `observations_max_length`. |

### 1.7 Knowledge & Progress (V2)

| Model | Key fields | Relationships |
|---|---|---|
| **KnowledgeField** (`api/knowledge/models.py`) | `id` (`knf_`), `key` (unique), `label`, `category`, `value_type`, `sensitive`, `active` | Reverse `questions`, `entries`. |
| **KnowledgeQuestion** (`api/knowledge/models.py`) | `id` (`knq_`), `prompt`, `trigger`, `trigger_config`, `suggested_responses`, `extraction_prompt`, `flows`, `order_by_flow`, `response_type`, slider/multi-select metadata, `order`, `active` | `target_field` → `KnowledgeField`. |
| **KnowledgeEntry** (`api/knowledge/models.py`) | `id` (`kne_`), `value`, `source` (`onboarding`/`question`/`ai`/`admin`), `confidence` | `consumer`, `field`, optional `knowledge_question` / `session` / `attribute` / `created_by`. Append-only; current = latest per (consumer, field). |
| **UserObservation** (`api/progress/models.py`) | `id` (`uobs_`), `text`, `topic_tag`, `generated_at` | `consumer` → `Consumer`. Patterns card = latest row; failed generation retains prior. |

Progress field-key defaults: mood = `mood` (slider 0–10), stress = `stress_points` (comma-joined multi-select). Streaks/dates use Django `TIME_ZONE` (v1; no per-user TZ yet).

---

## 2. Shared conventions — the `Smart*` view machinery

All views subclass one of three bases in `api/utils/Views.py`. Understanding these
explains 90% of the DB behavior; per-resource sections below mostly note deviations.

### 2.1 `SmartAPIView` (base)

- Default `permission_classes = [IsAdminPermission]` (subclasses widen this, often to
  `IsAdminPermission | IsConsumerPermission`, `api/utils/Permissions.py`). Permission
  classes only check `request.user.type`; they perform **no** DB query.
- Request-type helpers: `is_consumer_request()`, `is_admin_request()`,
  `get_consumer_from_request()` (→ `request.user.consumer`),
  `get_admin_from_request()` (→ `request.user.admin`). The latter two lazily trigger
  a related-object fetch.
- **Role-based permissions** (opt-in via `role_permission = True`): `get_admin_permissions()`
  reads `admin.role.permissions` (the `Permissions` row). `has_role_permission(method, model)`
  maps HTTP method → permission verb (`GET`→`view`, `POST/PUT`→`create`, `PATCH`→`edit`,
  `DELETE`→`delete`) and checks membership in the model's array column (the column name comes
  from the model's `get_permission_key()`). Consumers always pass. This reads the
  `role` and `permissions` rows via the admin relation.
- **PII obscuring** (`should_obscure_pii` / `handle_obscure_pii` / `_obscure_pii`): if the
  request is an admin whose role lacks `view` in the `pii` array, response dicts have
  `first_name`, `last_name`, `full_name`, `email`, `date_of_birth` replaced with the
  `ANON_*` constants (recursively). Admin PII is never obscured. This is a
  response-transformation step only — no DB write.
- `inject_user(request, key)` mutates `request.data[key] = request.user.id` before serializer
  validation (used to stamp `created_by`/`consumer`/`user`).

### 2.2 `SmartDetailAPIView` (`/<id>` routes)

Handles `GET` / `PATCH` / `DELETE` on a single object.

- `queryset(request, id)` selects the base rows. Honours `?objects=` :
  `all` → `model.all_objects.filter(id=id)` (includes soft-deleted),
  `deleted` → `all_objects.filter(id=id, deleted_at__isnull=False)`,
  otherwise `model.objects.filter(id=id)` (alive only). Subclasses commonly override this
  to scope to the caller (e.g. subscription/file/image scope by consumer or `created_by`).
- **GET**: `queryset → filter_queryset(method) → add_filters(request)`; `.first()`; 404 if
  missing; serialize with `get_detail_serializer` (admin variant if defined and admin);
  `override_response_data` then PII obscuring. Read-only.
- **PATCH** (`@transaction.atomic`): same read chain, then `override_patch_data`, then
  `edit_serializer(data, partial=self.partial, instance=instance)` → `is_valid` →
  `serializer.update(...)`. All writes run inside a single transaction. Response re-serialized
  with the detail serializer and PII-obscured.
- **DELETE** (`@transaction.atomic`): only if `deletable = True` **and** permission checks
  pass. Loads the instance, then `handle_delete(instance)` which by default calls
  `instance.delete()` → **soft delete** (`deleted_at = now()`). Returns `204`. Subclasses can
  override `handle_delete` (e.g. subscriptions run Stripe cancellation instead).

### 2.3 `PaginationAPIView` / `SmartPaginationAPIView` (collection routes)

`SmartPaginationAPIView` adds `GET` (list), `POST` (create) and `PUT` (bulk create) on a
collection; `PaginationAPIView` supplies pagination.

- **Pagination**: cursor-based by default (`CursorSetPagination`, ordered `-created_at`,
  page size 20). `?pagination_type=page` switches to `PageBasedPagination`
  (`PageNumberPagination`). `?order_by=` overrides ordering (cursor mode rejects nested
  `__` lookups). `?page_size=` is clamped to `[min_page_size, max_page_size]`.
  `?paginated=false` (only if `allow_disable_pagination`) returns the full set unpaginated.
- **Query optimisation**: `paginated_response` calls `serializer_class.optimise(queryset)`
  when available, applying `select_related(*get_select_related_fields())` and
  `prefetch_related(*get_prefetch_related_fields())` so list serialization avoids N+1
  queries. If the serializer lacks `optimise`, a yellow console warning is printed.
- **Export**: `?export=...` routes the queryset through `Export.queryset(...)` instead of a
  JSON response.
- **GET**: `queryset(request) → filter_queryset → add_filters → get_list_serializer`
  (admin list serializer if defined and admin) → `paginated_response`. `queryset` honours the
  same `?objects=all|deleted` switch as detail views. Read-only.
- **POST** (`@transaction.atomic`): `override_post_data` (often stamps FKs) → `create_serializer`
  → `is_valid` → `save()`. Response uses the detail serializer, PII-obscured, `201`. All
  writes (including nested/related writes, see below) are one transaction.
- **PUT** (`@transaction.atomic`): bulk create via `bulk_serializer` → `bulk_detail_serializer`.
- Row-level scoping/filtering is done per view in `add_filters` (e.g. consumers see only
  their own sessions/messages).

### 2.4 Nested writes (`api/utils/Serializers.py`)

`BaseModelSerializer.create/update` support declarative nested relations, used heavily by
Exercise (steps + questions) and Consumer (nested user). For each declared nested relation:

- `create_before_model=True` relations are created first, then linked (e.g. a Consumer's
  `User` is created before the Consumer row).
- OneToOne relations go through `update_one_to_one_relation` (create or edit + relink).
- Reverse FK "many" relations go through `update_foreign_key_relation`, which **deletes any
  existing related rows not present in the payload** (soft delete via the queryset `delete()`),
  reorders by list index when `ordered`, and creates/edits the rest. This is how editing an
  exercise reconciles its step/question set.

All of this executes within the enclosing view's `@transaction.atomic`.

---

## 3. Authentication & user — `/user`

Views in `api/user/views.py` are hand-written (not `Smart*` CRUD). Consumer/Admin **creation**
happens through the consumer/admin collection endpoints and the social-auth pipeline, not here.

| Endpoint | DB reads | DB writes / external |
|---|---|---|
| `POST /user/login` | `User.objects.get(email__iexact=...)`; `check_if_user_active` reads `deleted_at`/`status`; `get_detailed` loads `Admin`+role or `Consumer`+subscription (and may run subscription validation, §10). | `update_last_login` writes `last_seen`; issues JWT via `Token.create` (writes `OutstandingToken`); may enqueue verification email (Celery, not DB). |
| `POST /user/login/` (+ social) | `rest_social_auth` + `SOCIAL_AUTH_PIPELINE`; `api.user.social_pipeline.create_client` creates the customer object. | Creates `User` + `Consumer` (+ Summary/Subscription via consumer create path) on first social login; returns JWT. |
| `GET /user/facebook-code` | none (calls Facebook Graph API). | none (external only). |
| `POST /user/logout` | Looks up the `OutstandingToken` for the refresh token, excluding already-blacklisted ones. | Creates a `BlacklistedToken` row. |
| `POST /user/refresh-token` | Reads `OutstandingToken`; `check_if_user_active`. | Blacklists the old token, issues a new JWT pair (writes a new outstanding token). |
| `GET /user/info` | `get_detailed` (Admin/Consumer + subscription validation). | Writes `user.last_seen`; may write subscription during validation. |
| `POST /user/request-reset-password` | `User.objects.filter(email__iexact=...)`; rate-limit check on `verification_code_sent_at`. | Enqueues `send_code` (Celery task writes `verification_code`/`verification_code_sent_at`). |
| `POST /user/reset-password` | `User.objects.filter(email__iexact=...)`; compares `verification_code`. | Writes hashed `password`, clears `verification_code`. |
| `POST /user/request-verify-email` | rate-limit check. | Enqueues verification-code email (Celery). |
| `POST /user/verify-email` | compares `verification_code`. | Sets `email_verified=True`, clears `verification_code`. |

`get_detailed` is the fan-out that turns a bare `User` into the admin/consumer payload and,
for consumers whose `last_checked_at` is older than an hour, triggers
`SubscriptionUtils.validate_subscription` (may cancel/downgrade — see §10).

---

## 4. Uniform CRUD resources

These modules are thin `SmartPaginationAPIView` (`ListCreate`) + `SmartDetailAPIView` (`Detail`)
pairs. Reads = `model.objects.filter()` (alive rows) with optional `add_filters`; writes =
serializer create/update (transactional) and soft-delete on `DELETE` when `deletable=True`.
Serializer `optimise()` applies `select_related`/`prefetch_related` for list reads.

| Resource | Routes | Model | Permissions & notable filters/writes |
|---|---|---|---|
| **Agents** | `GET,POST /agents`, `GET,PATCH,DELETE /agents/<id>` | `Agent` | Admin. Serializers `select_related('avatar')`. Agent has a required `avatar` OneToOne `Image` and `created_by`. |
| **Admins** | `/admins` | `Admin` | Admin. Creating an Admin also creates the underlying `User` (nested, `create_before_model`). PII never obscured for the Admin model. |
| **Consumers** | `/consumers` | `Consumer` | Admin (+ own consumer for some reads). Create (`ConsumerCreateSerializer`) is a multi-write flow — see §5. |
| **Roles** | `/roles` | `Role` | Admin, `role_permission`. Creating a role typically also creates its `Permissions` row. |
| **Posts** | `/posts` | `Post` | Admin. `thumbnail`/`banner` (Image), optional `file`. AI article generation is a separate flow (§9). |
| **Questions** | `/questions` | `Question` | Admin, `role_permission` (`questions`). `Question.get_with_attributes` joins a consumer's `attributes` onto questions (used by onboarding/survey). |
| **Attributes** | `/attributes` | `Attribute` | Admin. Consumer answers; writing an attribute is what advances onboarding/survey status. |
| **Packages** | `/packages` | `Package` | Admin. `select_related('price__currency')`. |
| **Tags** | `/tags` | `Tag` | Admin. |
| **Assets** | `/assets` | `Asset` | Admin, `role_permission` (`assets`). `select_related` over `post/file/image`; `prefetch_related('tags')`. |
| **Settings** | `GET,POST /settings` | `Setting` | Admin. Key/value writes (`survey_enabled`, prompts). |

`Detail` views for these resolve rows via the shared `queryset(request, id)` (honouring
`?objects=all|deleted`), and `DELETE` performs a soft delete via `instance.delete()`.

---

## 5. Consumer creation — a multi-write flow

`ConsumerCreateSerializer` (`api/consumer/serializers.py`) is a good example of the nested-write
machinery in action. On `POST /consumers` (inside the view's `@transaction.atomic`):

1. `validate()` sets `attrs["agent"] = Agent.get_default()` — a **read** that picks the
   `default=True` agent, falling back to the oldest agent by `created_at`.
2. The nested `user` relation is `create_before_model`, so a **`User` row is inserted first**
   (`UserConsumerCreateSerializer`), then the **`Consumer` row** referencing it and the default agent.
3. `post_create` performs two more inserts: `Summary.get_or_create(consumer)` (per-consumer
   summary row) and `Subscription.create(consumer)` (a default, inactive subscription tied to
   the free package via `Package.get_default()`).
4. If the user's email is unverified, a verification-code email is enqueued (Celery — not DB).

The social variant (`ConsumerSocialCreateSerializer`) drops the DOB/name requirements but runs
the same post-create writes; it is what the social-auth pipeline calls on first login.

`ConsumerEditSerializer.post_update` re-runs `consumer.update_onboarding_status()` and
`update_surveyed_status()` — each reads the consumer's answered `question_id`s and, if no
required questions remain, flips `onboarded`/`surveyed` to `True` and saves.

---

## 6. Sessions — `/sessions`

Views: `List`, `Today`, `Start`, `Detail`, `Summary` (`api/session/views.py`).

### `GET /sessions` — `List` (`SmartPaginationAPIView`)
- Permissions: Admin **or** Consumer, `role_permission` (`sessions`).
- `add_filters` reads `?exercise_id`, `?consumer_id`, `?risk_level`, `?min_rating`,
  `?max_rating`. **Consumers are force-scoped** to their own `consumer_id`
  (`consumer.user_id`). Filters translate to `filter(consumer_id=…)`,
  `filter(exercise_id=…)`, `filter(risk_level=…)`, `rating__gte/lte`.
- Read-only, paginated.

### `GET /sessions/today` — `Today` (Consumer only)
- Reads today's **general** session: `Session.objects.filter(created_at__date=today,
  consumer=…, exercise__isnull=True).first()`.
- If none exists, calls `Session.get_or_create(consumer)` — a **write** path (see below).
- Returns `SessionDetailSerializer`.

### `GET /sessions/start` — `Start` (Consumer only)
- Optional `?exercise_id` → `Exercise.objects.get(id=…)` (read).
- Calls `Session.get_or_create(consumer, exercise)` — write path.

### `Session.get_or_create(consumer, exercise=None)` — the session-bootstrap write flow
Reads today's most-recent matching session; if it exists and isn't completed, returns it
(no write). Otherwise it **creates** a `Session` (for exercises: `current_step_no=1`,
`total_steps_no=exercise.steps_no`, `completed=False`) and then:
- For exercises: `SessionStep.create(...)` **bulk-inserts** one `SessionStep` per exercise
  step (ordered), and **clones each of the exercise's questions** onto the session (new rows
  with `exercise=None, session=session`).
- Always creates the two `Participant` rows (consumer + the consumer's agent).
- For exercises, it seeds the conversation: builds a consumer `Message`, calls
  `Agent.get_response(...)` (the full LLM loop — §7), then updates `last_message`,
  `messages_no`, `agent_messages_no` and saves.

### `GET,PATCH,DELETE /sessions/<id>` — `Detail`
- Admin or Consumer, `role_permission`. Consumers are scoped in `add_filters`
  (`filter(consumer=…)`). Standard read / transactional patch / soft-delete.

### `GET /sessions/<id>/summary` — `Summary` (Consumer only)
- `get_object_or_404(Session, id=…, consumer=…, completed=True, exercise__isnull=False)`.
- `ExerciseSummary.get_or_create(consumer, session.exercise)` — **read-or-create** (may insert
  a blank exercise-summary row).
- Computes `time_taken` from `last_message.created_at - session.created_at`.
- `get_usage()` runs an **aggregate query**: sessions in the last 10 days for this consumer +
  exercise, grouped by `TruncDate('created_at')` with `Count('id')`, returned as a per-day
  count array.

---

## 7. Messages & the LLM write loop — `/messages`

Only the collection route exists: `GET,POST /messages` → `ListCreate`
(`api/message/views.py`, `SmartPaginationAPIView`). Admin or Consumer.

### `GET /messages`
- `add_filters` reads `?session_id`, `?consumer_id`; consumers are force-scoped to their own
  user id. Translates to `filter(session_id=…)` and `filter(session__consumer_id=…)` (a join
  onto session). `MessageListSerializer.optimise` `select_related`s sender/agent/avatar,
  consumer/user, and asset (file/image/post + post's file/banner/thumbnail) to avoid N+1.

### `POST /messages` — the core AI turn
`override_post_data` stamps `consumer = request.user.consumer.user_id`. The write happens in
`MessageCreateSerializer.handle_create` (all within the view's `@transaction.atomic`):

1. **Validate**: reads the `Participant` for (session, consumer); rejects if the caller isn't a
   participant or the session is already `completed`. Sets `sender = participant`.
2. **Insert the consumer message** (`super().handle_create`).
3. **`Agent.get_response(user_message, session)`** (`api/agent/models.py`) — this is the
   LLM step and it **also inserts the agent's `Message` row**:
   - Special QA shortcuts (message text like `qa skip step`, `qa asset image/post/file`,
     `qa exercise`) bypass the LLM and read a matching `Asset`/`Exercise` directly.
   - Otherwise `AgentUtils.get_response` (§8) calls the pydantic-ai Google model. This reads
     the session's `cached_prompt`/`cached_history`, may invoke tools that **read** `Asset`
     (random by step tags) or `Exercise`, and on success **writes** `session.cached_history`
     (JSON) via `update_chat_history`.
   - It then creates the agent `Message` (text, reasoning, usage JSON, suggested responses,
     step metadata, optional asset/exercise) with `sender` = the agent participant.
4. **Exercise progression** (only when `session.exercise_id`):
   - If an asset was returned, sets `session.last_asset` and the current `SessionStep.last_asset`.
   - If the step is **not** complete, nulls the agent message's `completion_result`.
   - If the step **is** complete: copies the step's `completion_label` onto the message, marks
     the `SessionStep` completed with its `completion_result`/`completion_label`, and either
     advances `current_step_no` or, on the last step, sets `session.completed=True` and
     **increments `Exercise.completions_no`** via `F('completions_no') + 1`.
   - Detaches any `exercise` accidentally attached to the agent message.
5. **Session bookkeeping**: sets `last_message`, `messages_no += 2`, `agent_messages_no += 1`,
   `consumer_messages_no += 1`, saves.

Net DB writes per successful turn: 2 `Message` inserts, session update, possibly `SessionStep`
update, session `cached_history` update, and an exercise `completions_no` bump. The only
external call is the LLM (Google) via pydantic-ai.

---

## 8. Agent / summarization internals (`api/utils/Agent.py`)

Not an endpoint, but the engine behind §7 and summaries.

- **`get_response(session, consumer_message)`**: builds a pydantic-ai `Agent` on
  `GoogleModel(consumer.agent.model)`, output schema `ExerciseResponse` (exercise sessions) or
  `GeneralResponse`. Runs `agent.run_sync(...)` with `message_history=session.get_chat_history()`
  and a 2-tool-call limit. Registered tools:
  - `get_asset(step_no)` — reads the step, then `Asset.objects.filter(tags__in=step.tags)` and
    picks a random one (`order_by('?')`); stashes it on `deps.asset`.
  - `get_exercise(exercise_id)` — reads a published `Exercise`; stashes on `deps.matched_exercise`.
  On success, persists chat history (`session.update_chat_history` → `cached_history` JSON). On
  any exception it returns a canned apology response (no history write).
- **`_prepare_prompt(session)`**: returns `session.cached_prompt` if set. Otherwise reads the
  consumer summary (`Summary`), the general/therapeutic prompts (`Setting`), and either the
  exercise's steps + `ExerciseSummary` (create-or-get) or the list of published exercises;
  renders a template file (`api/utils/files/{general,exercise}_prompt.txt`); then **writes
  `session.cached_prompt`**.
- **`update_summary(summary, date, freezer)`**: reads a day's sessions+messages
  (`Session.get_with_messages`), appends a chat log to **Supabase Storage** (private bucket,
  `consumers/<id>/chat_log.txt`),
  asks the LLM for updated `detailed`/`observations`/`next_steps` and **saves** the `Summary`.
  Per session it also runs `update_session` which asks the LLM for `subject`/`rating`/
  `rating_reason`/`risk_level`, aggregates message `usage`, and **saves the `Session`**.
  (These run from background tasks, not directly from a request handler.)

---

## 9. Exercises — `/exercises`

Views: `ListCreate`, `Detail`, `DuplicateExerciseView` (`api/exercise/views.py`).

### `GET,POST /exercises` — `ListCreate`
- Admin or Consumer, `role_permission` (`exercises`). `has_permission` allows `GET` for anyone
  authenticated but restricts writes to admins.
- `add_filters`: `?status`, `?search_term` (→ `title__icontains`). **Consumers are forced to
  `status=published`** so they never see drafts.
- Create uses `ExerciseCreateSerializer` with **nested `steps` and `questions`** (each a
  `nested_relation`). One `POST` therefore inserts the exercise plus all its steps and questions
  in one transaction (via `update_foreign_key_relation`, which also reconciles/deletes on edit).
- Admin vs consumer read serializers differ (`ExerciseAdmin*` expose more).

### `GET,PATCH,DELETE /exercises/<id>` — `Detail`
- Same permission split. `deletable=True` → soft delete. Editing reconciles nested step/question
  sets (extra rows soft-deleted, order re-derived from list index).

### `POST /exercises/duplicate` — `DuplicateExerciseView` (Admin only)
- `ExerciseDuplicateSerializer.create` reads the source `Exercise` and calls
  `Duplicate.instance(source, exclude_fields=["completions_no"])` (`api/utils/Duplicate.py`).
  This deep-clones the exercise **and its reverse FK / O2O / M2M relations** — new `Step` rows
  (with their `tags` M2M copied), new `Question` rows, etc., each inserted with a fresh id.
  Excluded counters (`completions_no`) reset to 0.
- Sets the new title, forces `status=draft`, saves, then `_update_average_duration()`
  (reads the cloned steps, sums `average_duration`, writes it back).

### Exercise summaries — `/exercise-summaries/<id>`
- Only the detail route is wired (`api/exercise_summary/urls.py`); the collection view exists in
  code but isn't routed. `GET,PATCH,DELETE` on an `ExerciseSummary` row.

---

## 10. Subscriptions — `/subscriptions/<id>`

Only a detail route (`api/subscription/views.py`, Consumer only). `partial=False`, `deletable=True`.

- **`queryset`** is overridden to `Subscription.objects.filter(consumer=<caller>)` — a consumer
  can only touch their own subscription (PK is the consumer).
- **`PATCH`** via `SubscriptionEditSerializer` (transactional):
  - Reads current package/payment; rejects re-subscribing to the same active package or
    changing package while an external (Apple/Google/Stripe) payment is attached.
  - If `payment` data is supplied, it creates a `Payment` (via `PaymentCreateSerializer`,
    which may validate against Apple/Google/Stripe) and links it; sets `active=True`,
    `subscribed_at=now()`, clears `unsubscribed_at`, copies the package title.
  - `post_update` re-evaluates `update_onboarding_status()` / `update_surveyed_status()`.
- **`DELETE`** overrides `handle_delete` to call `SubscriptionUtils.cancel(...)` instead of a
  soft delete: it rejects cancelling store-managed (Apple/Google) subs, calls
  `StripeSubscription.cancel(...)` (**external**) when a Stripe sub id exists, then **writes**
  the row (`payment=None`, `unsubscribed_at=now()`, `active=False`, `package=default`) and sets
  the consumer `onboarded=False`.
- **Validation side effects** (`api/utils/Subscription.py`, invoked from `get_detailed` on
  login/info when stale): `validate_subscription` may confirm the sub against Apple/Google/Stripe
  and, if invalid, run the same `cancel` write path; always updates `last_checked_at`.

External vs DB: Stripe/Apple/Google calls are external; the subscription/payment/consumer row
mutations are DB writes.

---

## 11. Files & images (Supabase Storage uploads) — `/files`, `/images`

Object storage is **Supabase Storage**, accessed via its S3-compatible API (still `boto3`
under the hood, just pointed at Supabase's endpoint instead of AWS — see
`docs/DEPLOYMENT_HYBRID.md`). Both endpoints follow a **presigned-URL** pattern: the API
creates a DB record and returns a presigned PUT URL; the client uploads the bytes directly
to storage; a follow-up `PATCH` marks the record uploaded.

### `POST /files` — `Create` (Admin) / `POST /images` — `Create` (Admin or Consumer)
- `inject_user(request, "created_by")` stamps the owner.
- Create serializer inserts the `File`/`Image` row (with the intended storage key in `url`/`original`).
- `File.get_upload_link(...)` / `File.get_upload_link(image.original)` generates a **presigned
  PUT URL** (`api/utils/File.py`, `boto3.generate_presigned_url`, 1-hour expiry). For files a
  `token` (shortuuid) is generated and **saved** for later verification.
- Response: `{ pre_signed_url, file|image, filename }`. No bytes touch the server.

### `GET,PATCH,DELETE /files/<id>` and `/images/<id>` — `Edit` (`SmartDetailAPIView`)
- `queryset` is overridden to require the correct `token` (from the body, mandatory) **and**
  `created_by=request.user` — so only the uploader, holding the token, can finalize the record.
- `PATCH` (`partial=False`) typically flips `uploaded=True` and stores final metadata.
- `Image.generate(...)` (used by AI post generation, §12) is a server-side variant: it calls the
  AI image API, **inserts** an `Image` row, uploads bytes to storage via `File.upload`, then sets
  `uploaded=True`.

Supabase Storage is the external system here; the `File`/`Image` rows are the DB side.

---

## 12. AI content generation — `/ai`

`GET,POST /ai` → `Create` (`SmartPaginationAPIView`, Admin only) with `model=Post`.

- `POST` (`AICreateSerializer`) is a **generation kickoff**: it reads the first admin `User`,
  **inserts** a placeholder `Image` and a placeholder `Post` (`status=generating`), then enqueues
  `generate_post.delay_on_commit(post.id, theme)` (Celery). The Celery task later calls
  `Post.generate` → `AI.generate_article` + `Image.generate` and **updates** the post with the
  AI title/subtitle/body and generated banner/thumbnail image.
- The synchronous response returns the placeholder post; the real content is filled in
  asynchronously. External systems: the LLM (article text) and AI image API + Supabase Storage (banner).

---

## 13. Feedback, onboarding, survey

### `GET,POST /feedback` — `Create`
- Inserts a `Feedback` row (linked to `user` and optionally a `message`), storing
  `positive`/`reason`/`value`.

### Knowledge write paths

- Admin CRUD under `/knowledge-*`; consumer profile under `/consumers/<id>/knowledge`.
- Runtime helper `write_knowledge_entry` appends rows and invalidates `session.cached_prompt` for that consumer.
- V2 onboarding answers (`POST /onboarding/answers`) write `source=question` only (no Attribute dual-write). Legacy Attribute onboarding remains; Celery `backfill_knowledge_from_onboarding` bridges Attribute → Entry by key.

### Pre-exercise session start

- `Session.get_or_create`: if exercise enabled + prior completed session for that exercise → `current_step_no=0` and check-in greeting.
- `POST /sessions/<id>/complete-pre-exercise` stamps summary/`completed_at`, sets step to 1, clears cached prompt, starts exercise greeting.
- `MessageFlow` ignores step completion while `current_step_no == 0`.

### Progress reads — `/progress/*` (`api/progress/services.py`)

- Mood: KnowledgeEntries for `mood` in range; one point per local day (latest); gaps omitted; summary vs previous equal-length period.
- Exercises: `Session` with `completed=True` + exercise; heatmap via day set; breakdown by exercise.
- Patterns: latest `UserObservation` (if settings enabled) + stress aggregation from `stress_points` entries.
- Streaks: distinct local activity days; current counts backward from today (or yesterday if today empty); best = longest contiguous run.
- Celery `generate_user_observations` / `generate_user_observation`: ≤1/24h; AI via `AI.ask`; retain prior on failure.

### `GET /onboarding` — `Onboarding` (Consumer only, `api/onboarding/views.py`)
- Reads non-survey, non-exercise `Question`s and joins the consumer's `attributes`
  (`Question.get_with_attributes` → per-question `attribute` payload; boolean questions get
  `["Yes","No"]`).
- If the consumer has no `date_of_birth`, prepends a synthetic DOB question.
- Reads non-default `Package`s (optimised) for the paywall.
- Returns `{ onboarded, questions, packages }`. **Read-only.**

### V2 onboarding flows — `/onboarding/status|flow|answers`

- Status computes `refresh_due` from `last_onboarding_flow_completed_at` + `refresh_onboarding_cadence_days`.
- Flow lists active `KnowledgeQuestion` rows whose `flows` contain the variant, sorted by `order_by_flow[variant]` (fallback `order`); prompts resolved with `{{knowledge.*}}` / `{{user.first_name}}` tokens.
- Answers validate slider/choice/multi-select bounds, append KnowledgeEntries, and on `complete=true` update consumer onboarding timestamps (Initial also sets `onboarded=True`).

### `GET /survey` — `Survey` (Consumer only, `api/survey/views.py`)
- Reads the `survey_enabled` setting; computes task completion by querying: `consumer.onboarded`,
  whether a `view` event exists, whether any session exists, and whether ≥3 consumer messages
  exist. Reads survey questions + the consumer's attributes to attach answers.
- Returns tasks, questions, `surveyed`, and survey link config from `Api`. **Read-only.**

---

## 14. Misc & external-system summary

- `GET /` returns a health/status JSON; `/__debug__/...` is the Django Debug Toolbar, only when
  `DEBUG=True` (`mendreo/api/urls.py`, `mendreo/mendreo/settings.py`).
- **Database**: PostgreSQL (Supabase in production), configured from `DATABASE_*` env vars.
  Everything above operates through Django's ORM against this single default DB.
- **External systems** (writes to these are *not* DB writes):
  - **LLM (Google Gemini via pydantic-ai)** — message responses (§7/§8), summaries, article and
    session grading text.
  - **Supabase Storage** — file/image bytes and the appended per-consumer chat logs (§8/§11).
  - **Stripe / Apple / Google** — subscription lifecycle and receipt validation (§10).
  - **SendGrid (email) via Celery** — verification/reset codes and notifications (task enqueues,
    not DB writes, though the tasks themselves may stamp `verification_code*` on `User`).

---

*For the flat method/path/purpose reference, see [`API.md`](./API.md).*
