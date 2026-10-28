# Workato Connector SDK internals (ground truth from gem source)

Source of truth: workato-connector-sdk gem v1.3.19, read directly from
`~/.claude/workato-kb/corpus/github/workato-connector-sdk/` (all paths below are relative to that root).
Canonical connector examples: `~/.claude/workato-kb/corpus/github/custom-connector-docs/custom_connectors/` (96 files).
Purpose: ground truth for building connectors and for filing informed product feedback.
This doc covers the SDK gem and connector code only, not the platform REST/Recipe APIs.

# 1. SDK architecture map

## Gem layout

- `lib/workato-connector-sdk.rb` — entry. Requires ActiveSupport (all), Binary/UnicodeString types, ~20 Ruby monkey-patch extensions (`lib/workato/extension/*`), then `sdk/core.rb`. Forces `ENV['TZ']='UTC'` at require time (warns if TZ differs) and sets `Time.zone` to `DEFAULT_TIME_ZONE = 'Pacific Time (US & Canada)'` (`lib/workato/connector/sdk/core.rb:31`). Local runs are UTC env + Pacific Rails zone; both matter for date parsing.
- `lib/workato/connector/sdk/core.rb` — constants defining the local project contract:
  paths `connector.rb`, `settings.yaml` / `settings.yaml.enc`, `master.key` (env `WORKATO_CONNECTOR_MASTER_KEY`), `account_properties.yaml(.enc)`, `lookup_tables.yaml`, `workato_schemas.json`; envs `WORKATO_API_EMAIL`, `WORKATO_API_TOKEN`, `WORKATO_BASE_URL` (default `https://app.workato.com`).
- `lib/workato/connector/sdk/connector.rb` — `Connector` class. `Connector.from_file` does `eval(File.read(path), binding, path)` (line 22): the connector definition is a Ruby file evaluated top-level, returning a hash. Proxies lazily instantiate per-section runtime objects: `ActionsProxy`, `TriggersProxy`, `MethodsProxy`, `PickListsProxy`, `ObjectDefinitions`, `Connection`, `Streams`. `test:` becomes an Action.
- `lib/workato/connector/sdk/operation.rb` — `Operation` is the universal evaluator. Actions, triggers, streams, methods, object-definition field blocks, pick lists all evaluate through it. Includes DSL modules: `Dsl::Global`, `Dsl::AWS`, `Dsl::HTTP`, `Dsl::Call`, `Dsl::Error`, `Dsl::ExecutionContext`.
- `lib/workato/connector/sdk/{action,trigger,stream}.rb` — thin subclasses of `Operation` adding retry (Action), poll/webhook protocol (Trigger), chunking (Stream).
- `lib/workato/connector/sdk/connection.rb` — connection fields evaluation, `Authorization` (acquire/refresh/apply/detect), settings store with MonitorMixin.
- `lib/workato/connector/sdk/request.rb` — HTTP executor built on RestClient. Lazy SimpleDelegator.
- `lib/workato/connector/sdk/schema.rb` + `schema/field/*` — input/output field schema engine and converters.
- `lib/workato/connector/sdk/dsl/*` — stdlib packages: `workato` (jwt/aes/csv/net/stream), `http`, `aws`, lookup tables, account properties, error, reinvoke.
- `lib/workato/cli/*` — the `workato` CLI (Thor): exec, push, oauth2, edit, new, generate, schema.
- `lib/workato/web/app.rb` — 30-line Rack app used by `workato oauth2` to catch the OAuth callback.
- `lib/workato/testing/*` — VCR cassette encryption + multipart matching for rspec.

## Evaluation model (how DSL blocks run)

- Every lambda/proc is run via `instance_exec` on an Operation (or `Dsl::WithDsl` for connection-level lambdas like `base_uri`).
- `BlockInvocationRefinements` (`lib/workato/connector/sdk/block_invocation_refinements.rb`) truncates arguments to the block's declared arity: connector lambdas may declare 0..N of the offered positional args. That is why `lambda do |_connection, input|` vs `lambda do |connection, _input, _output_schema|` both work everywhere.
- `Operation#execute` (`operation.rb:92-105`) passes `(connection.settings, input, extended_input_schema, extended_output_schema, continue)` and post-processes the return value: any `Request` objects left anywhere in the result are resolved (`Request.response!` recurses through hashes/arrays), then converted to HashWithIndifferentAccess. An action's execute block can therefore return a bare `get(...)` call and the SDK fires it.
- Requests are lazy: `Request#method_missing` delegates to `response!` (`request.rb:41-43`), so `get(url)['data']` executes inline.
- Streams are NOT available in connection/base_uri/test contexts (`ProhibitedStreams`, `streams.rb:58-67`: raises "Streams are not available in this context").

## Streams

- Defined top-level `streams:` and per-action `streams:`; names become callable methods on the streams proxy: `my_stream(input, from, to, frame_size)` (chunked) and `my_stream!(input, frame_size)` (read all) (`streams.rb:37-47`).
- `Stream::DEFAULT_FRAME_SIZE = 10.megabytes` (`stream.rb:35`).
- `workato.stream.out(name, input)` returns a `Stream::Proxy` that serializes as `{__stream__: true, name:, input:}` — this is how a stream is handed to a recipe; `workato.stream.in(stream, from:, frame_size:, &blk)` reads it chunk by chunk (`dsl/stream_package.rb`).
- Access via `streams.my_stream` (returns Stream) or `workato.stream` package inside execute blocks.

## Lookup tables / account properties / schemas

- `lookup(table_id_or_name, condition_hash)` (`dsl/lookup_table.rb`, `lookup_tables.rb`): singleton loaded from `lookup_tables.yaml` locally via CLI; rows are frozen arrays; returns `{}` (not nil) when table or row not found.
- `account_property(name)` (`dsl/account_property.rb`, `account_properties.rb`): string key/value store, ERB-rendered yaml or encrypted yaml. Values coerced with `.to_s` on `put`.
- `workato_schema(id)` (`dsl/workato_schema.rb`): fetches shared field schema JSON (`workato_schemas.json`) by ID.

## Runtime knobs (local gem only)

- `MAX_REINVOKES` env, default 5 (`dsl/reinvoke_after.rb:37,77`): `reinvoke_after(seconds:, continue:)` on the platform reschedules the recipe; locally it sleeps and re-runs, max 5 times.
- `WAIT_REINVOKE_AFTER` env overrides the sleep seconds locally.

# 2. The connector DSL surface (semantics from code)

## connection block

- `fields:` — static array of connection input fields. `base_uri:` lambda returning a URI prefix; merged with request URLs via URI#merge (relative paths join against it) (`request.rb:369-416`).
- `authorization:`:
  - `type:` default `'none'` (`connection.rb:185-187`). `oauth2?` matches `/oauth2/i` in type. `type: 'multi'` = multi-auth: requires `selected:` lambda + `options:` hash of per-auth-type definitions (`connection.rb:355-373`); unresolved selection raises `UnresolvedMultiAuthOptionError`.
  - `acquire(settings, auth_code, redirect_url, pkce_verifier, query_params)` — runs in a nested Operation whose connection has `apply` REMOVED but `detect_on` KEPT (`connection.rb:263-292`), so an acquire request can still trip its own detect_on. Input passed to the block: `(connection, auth_code, redirect_url, pkce_verifier, query_params)`. Returns tokens hash, or `[tokens, resource_owner_id]`, or `[tokens, resource_owner_id, extra_settings]`.
  - `refresh(connection, refresh_token)` — same nested-Operation pattern without apply.
  - OAuth2 short form: define `token_url` + `client_id`/`client_secret` (each may be lambdas) and the SDK generates the standard refresh_token grant POST itself (`connection.rb:416-440`); missing refresh_token raises "Use workato oauth2 command".
  - `apply(connection, access_token, auth_type)` or legacy `credentials:` — sets headers/params on every request; executed via instance_exec on the Action, so `headers(...)`, `params(...)`, `user(...)`, `password(...)` mutate the current request (`request.rb:480-502`).
  - `refresh_on:` — array of Integer HTTP codes, Strings, or Regexp matched (via `===`) against http_code / response body / exception message. **Blank `refresh_on` + reauthorizable connection = refresh attempt on EVERY failed request** (`connection.rb:306-315`). After refresh the request retries exactly ONCE (`request.rb:486-501`, `first` flag); second failure propagates.
  - `detect_on:` — same pattern matching on response body/response; match raises `DetectOnUnauthorizedRequestError` (auth-level error, distinct from normal failures) checked on both raw body and parsed response (`request.rb:429-436, 324-326`).
  - `reauthorizable?` = oauth2 type OR acquire present (`connection.rb:294-297`).
- Settings: never memoized or frozen on purpose so developers stash temp state in connection settings (comment at `connection.rb:85-91`); refreshed settings merged under MonitorMixin. `Connection.on_settings_update` (CLI hooks into it) decides whether refreshed tokens persist.

## action block

- `execute: (connection, input, extended_input_schema, extended_output_schema, continue)`.
- `input_fields:` / `output_fields:` lambdas `(object_definitions, connection, input)` returning field arrays. `config_fields:` static fields evaluated before input_fields and passed to them.
- `sample_output: (connection, input)`.
- `summarize_input:` / `summarize_output:` — dot paths; arrays >100 items or strings >1024 chars collapsed to "... N items/characters ..." (`summarize.rb:8-9`).
- `retry_on_response:` — Integers = HTTP codes to retry, other matchers (String/Regexp) match exception message or response. If only matchers given, code set defaults to `RETRY_DEFAULT_CODES = [429, 500, 502, 503, 504, 507]` (`action.rb:16`).
- `retry_on_request:` — HTTP methods eligible, default `[:get, :head]` (`action.rb:17`). POST/PUT/DELETE are never retried unless you list them.
- `max_retries:` — clamped to 0..3, hard cap `MAX_RETRIES = 3` (`action.rb:120`). Asking for 10 silently becomes 3.
- Retry delay: 5s, doubling (5, 10, 20), in-process real sleep (`action.rb:135-138`).
- Retry matches only `RequestFailedError` (HTTP-level). Timeout raises `RequestTimeoutError` and is never retried.
- Streams may be declared per action.

## trigger block

- Polling: `poll: (connection, input, closure, eis, eos)` must return a Hash (else `InvalidTriggerPollOutputError` with docs link). Output normalized: `events` array-wrapped then **reversed** (`trigger.rb:84-86`), `next_poll` defaults to prior closure.
- `Trigger#poll` LOOPS until `can_poll_more` is false in a single invocation (`trigger.rb:102-118`). A poll block that always returns `can_poll_more: true` hangs locally.
- `dedup:` lambda receives input event and returns the dedup key; called with `.call(input)` directly, NOT instance_exec (`trigger.rb:121-123`) — `call('...')` to methods is unavailable inside dedup.
- Webhooks: `webhook_subscribe: (webhook_url, connection, input, recipe_id)`; return closure hash or `[closure, expires_at]` (`trigger.rb:12-17`). `webhook_notification: (input, payload, eis, eos, headers, params, settings, webhook_subscribe_output)`. `webhook_unsubscribe: (webhook_subscribe_output)`.
- `recipe_id` comes from `Dsl::ExecutionContext` — locally a random `SecureRandom.hex(32)`; CLI passes a mock (`recipe_id.reverse`) (`exec_command.rb:74`).

## methods block

- Shared lambdas, invoked with `call('method_name', args...)` (`dsl/call.rb`). Must be Procs; named procs raise `UnexpectedMethodDefinitionError`. Unknown name raises `UndefinedMethodError`.

## object_definitions block

- Lazy: a definition's `fields:` runs only when referenced; recursive references surface as `CircleReferenceObjectDefinitionError` (SystemStackError caught, `object_definitions.rb:48-50`). Every read returns a deep_dup, so big schemas get copied per access.

## pick_lists block

- Lambda arity selects signature: 0 args, 1 arg (connection), or 2+ args (connection, **input**) (`connector.rb:315-337`).

## Schema field engine (what input_fields/output_fields entries accept)

- Types (`schema.rb:189-218`): `integer`, `number`/`boolean` (both handled by Number field), `date_time`/`timestamp`, `date`, `object` (with `properties`), `array` (with `of:`, default `'object'`). **Anything else silently becomes a string field.**
- `optional` defaults to TRUE (`schema.rb:147`); required fields need `optional: false`.
- `control_type` prefixes `small-`/`medium-` are stripped (`schema.rb:170-174`). Unknown control types pass through unchecked; unknown keys on a field are never validated (typos like `controL_type:` silently drop; visible in the shipped intercom example).
- `toggle_field:` requires `toggle_hint` and the same `optional` value as the parent; render/parse convertors and control_type are stripped from the toggle field (`schema.rb:152-168`).
- `render_input:` / `parse_output:` on a field: a builtin convertor NAME (`integer_conversion`, `boolean_conversion`, `float_conversion`, `date_conversion`, `date_time_conversion`, `date_time_iso8601_conversion`, `parse_date_time_epoch_millis`, `parse_iso8601_timestamp`, `parse_epoch_time`, `parse_float_epoch_time`, `implicit_utc_time`, ... see `schema/field/convertors.rb`) or a `methods:` block name (resolved via `@_methods[field[:render_input]]` at apply time, `operation.rb:179-191`). Legacy `convert_input:`/`convert_output:` are aliases. **If you pass a Proc directly it is silently discarded** (`schema.rb:140-146`).
- Required enforcement at `invoke`: `MissingRequiredInput` raised unless present; `false` and empty-string count as present (`schema.rb:60-68`).
- Values are normalized on the way out: ASCII-8BIT strings become Binary, other strings UnicodeString, io-like objects read and rewound; unknown types raise `ArgumentError: Unsupported data type` (`schema.rb:92-125`).
- Date parsing heuristic: parses with `Time.parse` and with the zone's `TimeZone.parse`; if they differ, the zoned interpretation wins (`convertors.rb:178-184`). Local zone override env: `WORKATO_TIME_ZONE`.

## HTTP DSL (inside execute/apply/etc.)

- Methods: `get`, `post`, `put`, `patch`, `delete`, `options`, `head`, `copy`, `move` (`dsl/http.rb`). GET-family takes `params` hash; mutating methods take `payload` and default to `format_json` (both content-type and accept). GET defaults to JSON response parsing only.
- Builder chain on the request (`request.rb:68-259`): `headers` (case-insensitive merge), `case_sensitive_headers` (exact-case, for signature-sensitive APIs), `params`, `payload` (also yields the hash for mutation), `user`/`password` (basic auth, embedded in the URL userinfo!), `digest_auth`, `follow_redirection` / `ignore_redirection` (default: follow, per RestClient), `request_format_json` / `response_format_json` / `format_xml` / `request_format_xml` / `response_format_xml(strip_response_namespaces:)` / `request_body(raw)` (no rendering, no content-type), `response_format_raw` (BINARY), `request_format_multipart_form` (payload shape `{name => [value, content_type, filename]}`), `request_format_www_form_urlencoded`, `auth_type`, `tls_client_cert(certificate:, key:, passphrase:, intermediates:)` (mTLS), `tls_server_certs(certificates:, strict:)` (server cert pinning; `strict: false` also trusts system store), `after_response { |code, parsed_body, headers, message| }` (runs in Action context, can return a modified result), `after_error_response(*matches) { |code, body, headers, message| }` (matches: Integer code, String regexp on message/body, Regexp; returning a value SWALLOWS the error).
- XML uses Gyoku for render and a namespaces-stripping Nokogiri parse into hashes (`request.rb:158-179`).
- Empty JSON body parses to `{}` (`request.rb:153`).
- Errors: RestClient exceptions are re-raised as `RequestFailedError` (carrying method/code/response) or `RequestTimeoutError`. All request-chain format errors wrap causes into `JSONResponseFormatError` etc., preserving the original message.
- **No timeout option exists anywhere in the Request DSL.** RestClient default (60s) applies locally. No proxy support, no per-request retry options (retry lives on the action).
- `parallel(requests, threads:, rpm:, requests_per_period:, period:)` (`dsl/http.rb:55-68`): the gem executes requests **sequentially**, ignores every concurrency/rate parameter (rubocop-disabled unused args), and returns `[all_success?, results, errors]`. Any parallelism is platform-side only; locally this is a plain loop.

## workato stdlib package

- `workato.parse_json(str_or_response)`, `workato.uuid`, `workato.parse_yaml` (Psych.safe_load), `workato.render_yaml`.
- `workato.jwt_encode(payload, key, algorithm, header_fields)` / `jwt_encode_rs256` / `jwt_decode(jwt, key, algorithm)`: algorithms RS256/384/512, HS256/384/512, ES256/384/512; RSA keys <2048 bits rejected; ECDSA key length validated per curve; HS keys are raw strings (`dsl/workato_package.rb:54-113`).
- `workato.verify_rsa(payload, certificate, signature, algorithm='SHA256')`.
- Crypto: `workato.aes_cbc_encrypt/decrypt(string, key, iv)` (128/192/256), `workato.aes_gcm_encrypt/decrypt` (IV must be 96-bit, auth tag 96..128-bit, returns `[ciphertext, tag]`), `workato.pbkdf2_hmac_sha1(string, salt, iterations=1000, key_len=16)`, `workato.random_bytes(len<=32)`. Returns are `Binary` (ASCII-8BIT wrapper).
- `workato.encrypt(text, key)` / `workato.decrypt(text, key)`: RNCryptor via ruby_rncryptor gem, base64; failure messages collapsed to "invalid/corrupt input or key" (`dsl.rb:49-72`).
- Namespaces `workato.csv` (parse with size/line caps, errors `CsvFileTooBigError`), `workato.net` (`net.lookup(name, record)` DNS, `net.dns_resolver`), `workato.stream.in/out`.
- Unknown methods raise `UndefinedStdLibMethodError` naming the package (`workato_package.rb:268-270`).

## AWS package

- `aws.generate_signature(connection:, service:, region:, host:, path:, method:, params:, headers:, payload:)` returns signed `{url, headers}` (SigV4) with special-casing for ec2/s3/monitoring/lambda header behaviors (`dsl/aws.rb:186-211`).
- `aws.iam_external_id` / `aws.workato_account_id` for cross-account IAM roles.
- AssumeRole support: connection setting `aws_assume_role` triggers STS AssumeRole with temp-credential caching in connection settings, refreshed when expiring within 60s; retries once without ExternalId on failure (`dsl/aws.rb:88-139`).

## Misc DSL

- `error(message)` raises `Sdk::RuntimeError` (`dsl/error.rb`).
- `now`, `today` (zone-aware), `sleep(seconds)` (real Kernel.sleep locally), `puts` (stdout).
- Sentinels: `blank` = `''`, `clear`/`null`/`skip` = nil (`dsl.rb:74-82`).
- `execution_context` hash currently contains only `recipe_id` (`dsl/execution_context.rb:23-28`).

# 3. The CLI (`lib/workato/cli/`)

## workato exec (`exec_command.rb`)

- Executes any dotted path into the connector: `actions.foo.execute`, `triggers.bar.poll`, `methods.bazz` (with `--args` JSON file), `object_definitions.x`, pick lists, streams (with `--from`/`--frame_size`). Walks the path by public_send, then invokes the final method with args matched from CLI options (`InvokePath#invoke_method`, lines 273-281).
- Auto-loads from cwd if present: `workato_schemas.json`, `lookup_tables.yaml`, `account_properties.yaml(.enc)`.
- Settings: `settings.yaml.enc` preferred over `settings.yaml`; multi-connection files with `--connection NAME`; multi-auth prompts interactively for the auth type when `selected` is unresolved (`multi_auth_selected_fallback.rb`).
- Token refresh UX: `Connection.on_settings_update` is wired to a Yes/No prompt that persists refreshed tokens back into the settings file (`exec_command.rb:105-122`).
- `--debug` wraps the exception into `DebugExceptionError` (fresh clean backtrace). Verbose mode shows a fake progress bar wrapping RestClient logs.

## workato push (`push_command.rb`)

- Builds a zip with exactly three entries: `connector.custom_adapter.rb` (the connector source), `connector.custom_adapter.json` (manifest: title, description, note), optional `connector.custom_adapter.(png|jpeg)` logo (`push_command.rb:29,88-106`).
- Manifest defaults: title from `--title` or connector `title:` or interactive prompt; description from `--description <file>` or repo `README.md`; note = mandatory release notes (`--notes` or prompt).
- Auth: `Authorization: Bearer <token>` (API client token). Passing `--api-email` switches to deprecated `x-user-email`/`x-user-token` headers with a warning (`push_command.rb:188-208`).
- Endpoint: POST `/api/packages/import/<folder_id>`; folder defaults to the token owner's `root_folder_id` from GET `/api/users/me`. Import status polled every 15s up to 120s; on timeout it tells you to check Imports in the UI. Environments: preview, preview-eu, live, live-eu, or a raw URL via `--environment` / `WORKATO_BASE_URL`.
- Errors: folder 404 becomes "Can't find folder with ID=..."; server validation errors are stripped of the `connector.custom_adapter.json: ` prefix. The connector source is NOT evaluated by push beyond reading title (from_file), so syntax errors surface at import time.

## workato oauth2 (`oauth2_command.rb`)

- Local Authorization Code flow: WEBrick on `127.0.0.1:45555` (override `--port`/`--ip`, `--https` for a self-signed cert with verification disabled), callback path `/oauth/callback`, code served at `/code` (`web/app.rb`).
- Builds the authorize URL from the connector's `authorization_url` lambda + client_id + state (random hex) and opens the browser with Launchy. Callback awaited by polling `/code` every 5s, timeout 180s. **The returned state is logged, never verified** (`oauth2_command.rb:45`).
- Token exchange: uses the connector's `acquire` block if present (passing callback query params minus code/state as `query_params`), else a standard `authorization_code` POST to `token_url`. Tokens merged into the settings file.
- PKCE: the SDK acquire path supports `pkce_verifier`, but the CLI generates none; PKCE connectors need manual handling.

## workato edit / new / generate / schema

- `edit`: ActiveSupport::EncryptedConfiguration over `$EDITOR`; auto-creates `master.key` when missing; wrong key becomes "Perhaps you passed the wrong key?".
- `new`: Thor group scaffolding connector.rb + Gemfile + rspec with a VCR choice: secure (encrypted cassettes, error on unknown requests) or simple (plaintext cassettes).
- `generate test`: builds rspec skeletons. `generate schema` (`schema_command.rb`): converts a JSON/CSV sample to a Workato schema by POSTing to the CLOUD endpoint `/api/sdk/generate_schema/<type>` — schema generation is not local; it needs API credentials and connectivity.
- `version`: prints gem version.

# 4. Patterns from the 96 canonical connectors

Corpus: `custom_connectors/{api_key_auth(21), basic_auth(20), custom_auth(20), oauth2(30), digest_auth(1), none(4)}`.

- **OAuth2 minimal** (19 connectors use `refresh_on: 401`): connection fields for client_id/secret, `authorization_url`/`token_url` lambdas, SDK-generated refresh (no `refresh` block), `apply` sets Bearer. Exemplars: `oauth2/intercom_connector.rb`, `oauth2/spotify_connector.rb` (uses explicit `acquire`/`refresh` with www-form-encoded POST and HTTP basic via `.user().password()`), `oauth2/google_calendar_connector.rb`, `oauth2/microsoft_office_365.rb`.
- **Custom auth with acquire + extra settings**: `acquire` returns `[tokens, owner_id, extra_settings]` so tenant metadata lands in connection settings. Exemplars: `custom_auth/paypal_connector.rb`, `custom_auth/sage_intacct_connector.rb` (session-based SOAP-ish auth), `custom_auth/bill_connector.rb`, `custom_auth/paychex.rb`.
- **detect_on for tokens that never 401**: APIs that signal auth failure in the body. `basic_auth/nokiasps.rb:24` `detect_on: [/"errorMessage"\:/]`, `custom_auth/bmc_innovation_suite_connector.rb:46`, `custom_auth/bill_connector.rb:68`, `custom_auth/yarooms_connector.rb:41`, `api_key_auth/mandrill_connector.rb:23`.
- **Error-message enrichment idiom**: nearly every connector wraps destructive or flaky calls with `.after_error_response(/.*/) { |_code, body, _header, message| error("#{message}: #{body}") }` to convert opaque 500s into readable messages. Heaviest user: `api_key_auth/clover.rb` (9 occurrences); status-scoped variant `after_error_response(/[3-9]\d\d/)` in `api_key_auth/drift.rb`. The SDK has no built-in "append response body to error" option; every connector hand-rolls this.
- **Pagination**: poll triggers return `{events:, can_poll_more:, next_poll: closure}` (exemplars `api_key_auth/greenhouse_connector.rb`, `api_key_auth/iterable_connector.rb`); polling actions loop with a while/next closure in execute. No shared pagination helper exists in the SDK; every connector reimplements cursor/offset handling.
- **Dynamic schemas**: `config_fields:` + object_definitions keyed by user selection (`api_key_auth/codility_connector.rb:48-59` reads `config_fields['input']['schema']`); object_definition composition (`basic_auth/stripe_connector.rb` output_fields referencing shared definitions).
- **Tenant discovery via dynamic connection fields**: connection `fields:` as lambdas pulling workspaces/projects after auth (seen in `oauth2/wrike_connector.rb`, `oauth2/intercom_connector.rb` variants).
- **Digest auth**: exactly one exemplar, `digest_auth/shopware_connector.rb` (uses `.digest_auth` on the request).
- **No-auth**: `none/rssfeedreader.rb`, `none/statuspage.rb` (plain get()).
- Conspicuously ABSENT from the entire corpus: `retry_on_response`, `retry_on_request`, `max_retries`, and `parallel()`. The retry and parallel DSL features exist in the engine but no canonical example demonstrates them.

# 5. Bugs, gaps, and product feedback material

Verified in source, with citations. (Gem paths relative to gem root.)

1. **Per-trigger streams are dead code — LIVE-REPRODUCED 2026-10-16 (gem 1.3.19)**: `lib/workato/connector/sdk/connector.rb:163` reads `source[:trigger]` (singular) when collecting streams, but triggers live under `source[:triggers]`. Runtime: identical stream at connector root resolves; the same stream declared inside the trigger raises `KeyError: key not found: "counter"` in the poll block. Repro: /tmp/sdk-repro/trigger_streams_repro.rb. **FILED: PSM-24052** (2026-10-16).
2. **AWS secret-key fallback bug — LIVE-REPRODUCED 2026-10-16 (gem 1.3.19)**: `lib/workato/connector/sdk/dsl/aws.rb:224` — `amazon_role_client_secret` falls back to `@connection.settings[:access_key_id]` instead of `secret_access_key`, and the chain never reaches `@connection.settings[:secret_access_key]`. Runtime probe: settings-empty + connection-has-BOTH-keys still signs with the ACCESS KEY ID as the secret (case C — worse than a missing-secret edge: role-auth signing is always wrong unless the per-call settings carry the secret). Repro: /tmp/sdk-repro/aws_signing_repro.rb + signature differential. **FILED: PSM-24053** (2026-10-16).
3. **`parallel()` is sequential in the gem and silently ignores its tuning args — CODE-VERIFIED against installed gem 1.3.19**: `lib/workato/connector/sdk/dsl/http.rb:55-68` accepts `threads:`, `rpm:`, `requests_per_period:`, `period:` and uses none of them (rubocop Lint/UnusedMethodArgument disabled on the signature). Locally, "parallel" blocks run one-by-one with no rate limiting. Connector code tuned with rpm may behave differently on-platform vs locally.
4. **max_retries hard-capped at 3, silently — CODE-VERIFIED against installed gem 1.3.19**: `lib/workato/connector/sdk/action.rb:120` clamps the definition's `max_retries` to 0..3 (`MAX_RETRIES = 3`, action.rb:20); defaults are codes 429/500/502/503/504/507, methods GET/HEAD only (action.rb:16-17) — 429'd POSTs never retry. `max_retries: 10` becomes 3 with no warning; the cap is not configurable.
5. **Retry only covers GET/HEAD by default**: `lib/workato/connector/sdk/action.rb:17`. A POST hitting 429/503 is never retried unless the author also declares `retry_on_request`. Combined with the fact that no canonical example uses retry at all, transient-failure behavior is essentially undefined for mutating actions.
6. **Blank `refresh_on` refreshes on EVERY error**: `lib/workato/connector/sdk/connection.rb:310` (`refresh_on.blank? || ...`). On an oauth2 connection with no refresh_on, a 404 triggers a token refresh and one silent request retry. This burns refresh-token lifetimes and can loop providers that rotate refresh tokens.
7. **Unknown schema `type` silently becomes string**: `lib/workato/connector/sdk/schema.rb:215-217`. `type: 'datetime'` (wrong name for `date_time`) quietly yields a text field. No schema validation of unknown keys either: the shipped `oauth2/intercom_connector.rb` contains `controL_type:` typos (capital L) that are silently dropped.
8. **`render_input:`/`parse_output:` Procs are silently discarded**: `lib/workato/connector/sdk/schema.rb:140-146` keeps only non-Proc values; a lambda passed inline in a field is dropped with no error. Authors must use a methods-block name or a builtin convertor name.
9. **No request timeout, retry, or proxy knobs in the Request DSL**: `lib/workato/connector/sdk/request.rb` exposes no timeout option; everything rides RestClient defaults locally. Long-poll APIs need platform-side defaults that are invisible to connector authors.
10. **Basic-auth credentials go into the URL**: `lib/workato/connector/sdk/request.rb:386-391` embeds user/password as URI userinfo, so they appear in the built URL (and any log line that prints `current_url`).
11. **Digest auth always double-fires**: `lib/workato/connector/sdk/request.rb:312-323` sends once, takes the 401 challenge, then re-sends. Necessary for the protocol but means every digest request hits the server twice.
12. **Backtrace surgery hides connector frames on unexpected errors**: `lib/workato/connector/sdk/request.rb:60-65` rebuilds the backtrace as [frames after request.rb] + [callstack before request], which truncates context for anything that is not a RestClient error; debugging connector logic locally yields short, synthetic stacks.
13. **Object definitions deep-dup on every access**: `lib/workato/connector/sdk/object_definitions.rb:111-113`. Large shared schemas are copied for each reference; no caching of evaluated field arrays across actions.
14. **Poll semantics sharp edges**: `lib/workato/connector/sdk/trigger.rb:84-86` reverses the events array (ordering contract is implicit, not documented in code); `trigger.rb:102-118` drains `can_poll_more` in a local loop, so a poll block that always returns `can_poll_more: true` hangs the local run with no safeguard.
15. **dedup cannot use shared methods**: `lib/workato/connector/sdk/trigger.rb:121-123` calls the dedup lambda with `.call(input)` instead of instance_exec, so `call('helper')` is unavailable inside dedup; a complex dedup key needs duplicated logic.
16. **acquire can trip its own detect_on**: `lib/workato/connector/sdk/connection.rb:267` strips `apply` but keeps `detect_on` for the acquire request. A login endpoint whose error body matches the connector's detect_on regex raises `DetectOnUnauthorizedRequestError` for the very call meant to fix auth.
17. **OAuth CLI state is not verified**: `lib/workato/cli/oauth2_command.rb:45` logs `state` from the callback but never compares it to the generated one; CSRF protection is cosmetic locally.
18. **`generate schema` requires the cloud**: `lib/workato/cli/schema_command.rb` POSTs to `<WORKATO_BASE_URL>/api/sdk/generate_schema/<type>`; no offline fallback, so CI pipelines doing schema generation need live credentials.
19. **Push import wait is short and opaque**: `lib/workato/cli/push_command.rb:31-32,125-139` polls 120s max, then drops "Go to Imports in Workato UI to see the push result". Large imports or queues make CLI push report failure-shaped timeout for an import that later succeeds.
20. **No definition lint before push**: connector.rb is `eval`'d (connector.rb:22) and push only reads `title:` from it; structural mistakes (singular `trigger:` instead of `triggers:`) surface only at runtime. The Fields engine silently accepts unknown keys, so there is no cheap static validation layer available locally.
21. **MissingRequiredInput treats empty string as present**: `lib/workato/connector/sdk/schema.rb:60-68` (`value.present? || value.is_a?(FalseClass) || (String && !empty)`); blank-ish whitespace strings pass required checks.
22. **Error messages that hide causes**: `workato.encrypt/decrypt` collapse all RNCryptor failures into "invalid/corrupt input or key" / "invalid/corrupt input" (`lib/workato/connector/sdk/dsl.rb:62-72`); `aes_gcm_decrypt` collapses every cipher error into "Not able to decrypt, please check input values again" (`dsl/workato_package.rb:246-247`). Good for users, bad for debugging.
23. **Redirect-handling bug history**: `ignore_redirection` failed to stop 303 responses; fixes shipped in 1.3.17 and again in 1.3.19 (CHANGELOG.md). Connector authors relying on redirect control should pin >= 1.3.19 and re-test.
24. **NotImplementedError default message admits parity gaps**: `lib/workato/connector/sdk/errors.rb:101-105`: "This part of Connector SDK is not implemented in workato-connector-sdk yet". Platform-only behavior (true parallelism, real reinvoke scheduling, settings persistence) is invisible from the gem; local tests cannot fully validate those surfaces.
25. **`exec` settings-refresh prompt answers "no" but still applies new settings in memory** (`lib/workato/cli/exec_command.rb:105-122`): both the yes and no branches return `new_settings` to the connection; "no" only skips file persistence, which surprises anyone expecting a hard decline.

## Cross-cutting gaps worth filing as feature requests

- Built-in pagination primitives (cursor/offset/link-header) instead of hand-rolled loops in every connector.
- A declarative "append response body to error" option instead of the universal after_error_response idiom.
- Schema field validation with helpful errors (unknown type, unknown key, Proc convertor) at definition load time.
- Configurable request timeout/retry budget per connection or per request.
- Refresh token rotation protection: a `refresh_on` default that excludes 4xx-other-than-401/429.
- A visible parallel() local implementation (real threads) or documentation that concurrency args are platform-only.
