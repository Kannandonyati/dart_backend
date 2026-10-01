# DART recon pipeline — APIs, payloads, responses, order

Companion to `DART_Recon_Pipeline.postman_collection.json`.

| | |
|---|---|
| Base URL | `http://127.0.0.1:8000/api/v1` |
| Auth | `Authorization: Bearer {{access_token}}` after **003 Login (JSON)** |
| Login | `recon@admin.com` / `recon@123` |
| Mock files | `API_Modal/Mock/Data_Set 1 Karan/` |
| Pagination | `page` (default 1), `page_size` (default 25, max 200) |
| List total | header `X-Total-Count` on import / bridge / workflow lists |

**Error body (every 4xx/5xx)**

```json
{"error":{"code":"not_found|unauthorized|permission_denied|conflict|app_error|validation_error","message":"...","request_id":"uuid"}}
```

**WebSocket (Bridge progress, not HTTP)**

`ws://127.0.0.1:8000/ws/bridge_run:{{bridge_run_id}}?token={{access_token}}`

## Order of execution

Send **001 → 132**. Happy path skips the Skip column. Poll rows: resend until the status named.

| # | Folder | Method | Request | Happy path | Wait / skip |
|---|---|---|---|---|---|
| 001 | 0. Auth | `GET` | 001 · Health | yes | — |
| 002 | 0. Auth | `GET` | 002 · Health detailed | yes | — |
| 003 | 0. Auth | `POST` | 003 · Login (JSON) | yes | — |
| 004 | 0. Auth | `POST` | 004 · Login (OAuth2 form / Swagger) | skip | optional |
| 005 | 0. Auth | `POST` | 005 · Refresh token | skip | optional |
| 006 | 0. Auth | `GET` | 006 · Current user | yes | — |
| 007 | 1. Prerequisites — group and global variable | `GET` | 007 · List my groups | yes | — |
| 008 | 1. Prerequisites — group and global variable | `GET` | 008 · List groups | yes | — |
| 009 | 1. Prerequisites — group and global variable | `POST` | 009 · Create group | yes | — |
| 010 | 1. Prerequisites — group and global variable | `GET` | 010 · Get group | yes | — |
| 011 | 1. Prerequisites — group and global variable | `GET` | 011 · Group details | yes | — |
| 012 | 1. Prerequisites — group and global variable | `PATCH` | 012 · Rename group | yes | — |
| 013 | 1. Prerequisites — group and global variable | `GET` | 013 · List global variables | yes | — |
| 014 | 1. Prerequisites — group and global variable | `POST` | 014 · Create global variable | yes | — |
| 015 | 1. Prerequisites — group and global variable | `POST` | 015 · Link global variable to group | yes | — |
| 016 | 1. Prerequisites — group and global variable | `DELETE` | 016 · Unlink global variable from group | skip | optional |
| 017 | 1. Prerequisites — group and global variable | `POST` | 017 · Link global variable to group (again) | skip | optional |
| 018 | 2. Select — create recon | `GET` | 018 · List my recons | yes | — |
| 019 | 2. Select — create recon | `GET` | 019 · List available recons | yes | — |
| 020 | 2. Select — create recon | `GET` | 020 · Recon directory (security picklist) | yes | — |
| 021 | 2. Select — create recon | `POST` | 021 · Create recon | yes | — |
| 022 | 2. Select — create recon | `GET` | 022 · Get recon | yes | — |
| 023 | 2. Select — create recon | `PATCH` | 023 · Update recon (name / description) | yes | — |
| 024 | 2. Select — create recon | `POST` | 024 · Link recon to group | yes | — |
| 025 | 3. Dimension Linking — applications | `GET` | 025 · List recon apps | yes | — |
| 026 | 3. Dimension Linking — applications | `PATCH` | 026 · Update App 1 | yes | — |
| 027 | 3. Dimension Linking — applications | `PATCH` | 027 · Update App 2 | yes | — |
| 028 | 3. Dimension Linking — applications | `PATCH` | 028 · Attach global variable on App 1 | yes | — |
| 029 | 3. Dimension Linking — applications | `PATCH` | 029 · Detach global variable on App 1 | yes | — |
| 030 | 3. Dimension Linking — applications | `PATCH` | 030 · Attach global variable on App 1 (again) | yes | — |
| 031 | 3. Dimension Linking — applications | `POST` | 031 · Add App 3 | yes | — |
| 032 | 3. Dimension Linking — applications | `DELETE` | 032 · Delete App 3 | yes | — |
| 033 | 3. Dimension Linking — applications | `GET` | 033 · List recon apps (after delete) | yes | — |
| 034 | 4. Dimension Linking — dimensions | `GET` | 034 · List dimensions | yes | — |
| 035 | 4. Dimension Linking — dimensions | `POST` | 035 · Seed mandatory YEAR/PERIOD/AMOUNT | yes | — |
| 036 | 4. Dimension Linking — dimensions | `POST` | 036 · Import dimensions CSV (Mock template) | yes | — |
| 037 | 4. Dimension Linking — dimensions | `GET` | 037 · List dimensions (save custom id) | yes | — |
| 038 | 4. Dimension Linking — dimensions | `GET` | 038 · Get dimension | yes | — |
| 039 | 4. Dimension Linking — dimensions | `PATCH` | 039 · Update dimension mappings | yes | — |
| 040 | 4. Dimension Linking — dimensions | `POST` | 040 · Reorder dimension | yes | — |
| 041 | 4. Dimension Linking — dimensions | `GET` | 041 · Export dimensions CSV | yes | — |
| 042 | 4. Dimension Linking — dimensions | `POST` | 042 · Create extra dimension ACCOUNT | yes | — |
| 043 | 4. Dimension Linking — dimensions | `DELETE` | 043 · Delete extra dimension ACCOUNT | yes | — |
| 044 | 5. Run Import | `POST` | 044 · Upload App 1 file | yes | — |
| 045 | 5. Run Import | `GET` | 045 · Poll App 1 import run | yes | resend until `status=completed` |
| 046 | 5. Run Import | `POST` | 046 · Upload App 2 file | yes | — |
| 047 | 5. Run Import | `GET` | 047 · Poll App 2 import run | yes | resend until `status=completed` |
| 048 | 5. Run Import | `GET` | 048 · List import history | yes | — |
| 049 | 5. Run Import | `GET` | 049 · List imported rows (App 1) | yes | — |
| 050 | 5. Run Import | `GET` | 050 · List imported rows (App 2) | yes | — |
| 051 | 5. Run Import | `GET` | 051 · Export imported data ZIP (all apps) | yes | — |
| 052 | 5. Run Import | `GET` | 052 · Export imported data CSV (App 1) | yes | — |
| 053 | 5. Run Import | `POST` | 053 · Upload App 1 as journal entry (optional) | skip | optional |
| 054 | 6. Bridge Members | `POST` | 054 · Default bridge mappings App 1 | yes | — |
| 055 | 6. Bridge Members | `POST` | 055 · Default bridge mappings App 2 | yes | — |
| 056 | 6. Bridge Members | `POST` | 056 · Import bridge CSV App 1 (Mock) | yes | — |
| 057 | 6. Bridge Members | `POST` | 057 · Import bridge CSV App 2 (Mock) | yes | — |
| 058 | 6. Bridge Members | `POST` | 058 · Create bridge mapping (extra) | yes | — |
| 059 | 6. Bridge Members | `GET` | 059 · List bridge mappings App 1 | yes | — |
| 060 | 6. Bridge Members | `GET` | 060 · List bridge mappings App 2 | yes | — |
| 061 | 6. Bridge Members | `PATCH` | 061 · Update bridge mapping | yes | — |
| 062 | 6. Bridge Members | `GET` | 062 · Export bridge mappings App 1 | yes | — |
| 063 | 6. Bridge Members | `GET` | 063 · Export bridge mappings (all apps) | yes | — |
| 064 | 6. Bridge Members | `POST` | 064 · Start bridge run | yes | — |
| 065 | 6. Bridge Members | `GET` | 065 · List bridge runs | yes | — |
| 066 | 6. Bridge Members | `GET` | 066 · Get bridge run | yes | resend until `status=completed` |
| 067 | 6. Bridge Members | `GET` | 067 · List kickouts | yes | — |
| 068 | 6. Bridge Members | `GET` | 068 · List kickouts App 1 | yes | — |
| 069 | 6. Bridge Members | `GET` | 069 · Export kickouts | yes | — |
| 070 | 6. Bridge Members | `GET` | 070 · Export kickouts App 1 | yes | — |
| 071 | 6. Bridge Members | `POST` | 071 · Resolve one kickout | yes | — |
| 072 | 6. Bridge Members | `POST` | 072 · Default remaining kickouts App 1 | yes | — |
| 073 | 6. Bridge Members | `POST` | 073 · Default remaining kickouts App 2 | yes | — |
| 074 | 6. Bridge Members | `GET` | 074 · List bridged data App 1 | yes | — |
| 075 | 6. Bridge Members | `GET` | 075 · List bridged data App 2 | yes | — |
| 076 | 6. Bridge Members | `GET` | 076 · List bridged kickout rows | yes | — |
| 077 | 6. Bridge Members | `DELETE` | 077 · Delete extra bridge mapping | yes | — |
| 078 | 7. Transformation | `GET` | 078 · Possible combinations App 1 ENTITY | yes | — |
| 079 | 7. Transformation | `GET` | 079 · Possible combinations App 1 ENTITY+PERIOD | yes | — |
| 080 | 7. Transformation | `POST` | 080 · Apply all members App 1 | yes | — |
| 081 | 7. Transformation | `POST` | 081 · Apply all members App 2 | yes | — |
| 082 | 7. Transformation | `POST` | 082 · Create sync mapping (extra) | yes | — |
| 083 | 7. Transformation | `GET` | 083 · List sync mappings App 1 | yes | — |
| 084 | 7. Transformation | `GET` | 084 · List sync mappings (all apps) | yes | — |
| 085 | 7. Transformation | `PATCH` | 085 · Update sync mapping | yes | — |
| 086 | 7. Transformation | `GET` | 086 · Export sync mappings CSV | yes | — |
| 087 | 7. Transformation | `GET` | 087 · Export sync mappings CSV App 1 | yes | — |
| 088 | 7. Transformation | `POST` | 088 · Import sync mappings CSV | skip | optional |
| 089 | 7. Transformation | `POST` | 089 · Run transformation App 1 | yes | — |
| 090 | 7. Transformation | `POST` | 090 · Run transformation App 2 | yes | — |
| 091 | 7. Transformation | `POST` | 091 · Run transformation (all apps) | yes | — |
| 092 | 7. Transformation | `GET` | 092 · Export transformed data CSV | yes | — |
| 093 | 7. Transformation | `GET` | 093 · Export transformed data CSV App 1 | yes | — |
| 094 | 7. Transformation | `DELETE` | 094 · Delete extra sync mapping | yes | — |
| 095 | 8. Run Report | `GET` | 095 · Last refresh | yes | — |
| 096 | 8. Run Report | `POST` | 096 · Run report | yes | — |
| 097 | 8. Run Report | `GET` | 097 · Export report CSV | yes | — |
| 098 | 8. Run Report | `GET` | 098 · Drill-down ENTITY=1 | yes | — |
| 099 | 8. Run Report | `GET` | 099 · Filter members ENTITY App 1 | yes | — |
| 100 | 8. Run Report | `GET` | 100 · Filter members ENTITY (all apps) | yes | — |
| 101 | 8. Run Report | `POST` | 101 · Create report filter | yes | — |
| 102 | 8. Run Report | `GET` | 102 · List report filters | yes | — |
| 103 | 8. Run Report | `PATCH` | 103 · Update report filter | yes | — |
| 104 | 8. Run Report | `POST` | 104 · Run report with filter | yes | — |
| 105 | 8. Run Report | `GET` | 105 · Export report CSV with filter | yes | — |
| 106 | 8. Run Report | `DELETE` | 106 · Delete report filter | yes | — |
| 107 | 8. Run Report | `GET` | 107 · List sign-offs | yes | — |
| 108 | 8. Run Report | `POST` | 108 · Sign off apps | yes | — |
| 109 | 8. Run Report | `POST` | 109 · Clear sign-off | yes | — |
| 110 | 9. Copy / archive / unlink group | `POST` | 110 · Copy recon (Save As) | yes | — |
| 111 | 9. Copy / archive / unlink group | `GET` | 111 · Get copied recon | yes | — |
| 112 | 9. Copy / archive / unlink group | `PATCH` | 112 · Archive recon | yes | — |
| 113 | 9. Copy / archive / unlink group | `PATCH` | 113 · Unarchive recon | yes | — |
| 114 | 9. Copy / archive / unlink group | `DELETE` | 114 · Unlink recon from group | yes | — |
| 115 | 9. Copy / archive / unlink group | `POST` | 115 · Link recon to group (again) | yes | — |
| 116 | 10. Recon audit | `GET` | 116 · List recon audit logs | yes | — |
| 117 | 10. Recon audit | `GET` | 117 · My audit logs | yes | — |
| 118 | 10. Recon audit | `GET` | 118 · All audit logs (superuser) | yes | — |
| 119 | 10. Recon audit | `GET` | 119 · Users audit logs | yes | — |
| 120 | 10. Recon audit | `GET` | 120 · Export audit logs CSV | yes | — |
| 121 | 11. Scheduler (same recon, automated replay) | `POST` | 121 · Create workflow | yes | — |
| 122 | 11. Scheduler (same recon, automated replay) | `GET` | 122 · List workflows | yes | — |
| 123 | 11. Scheduler (same recon, automated replay) | `GET` | 123 · Get workflow | yes | — |
| 124 | 11. Scheduler (same recon, automated replay) | `PATCH` | 124 · Update workflow (pause / cron) | yes | — |
| 125 | 11. Scheduler (same recon, automated replay) | `POST` | 125 · Trigger workflow run | yes | — |
| 126 | 11. Scheduler (same recon, automated replay) | `GET` | 126 · List runs for workflow | yes | — |
| 127 | 11. Scheduler (same recon, automated replay) | `GET` | 127 · List all workflow runs | yes | — |
| 128 | 11. Scheduler (same recon, automated replay) | `GET` | 128 · Get workflow run | yes | resend until `status=succeeded|failed` |
| 129 | 11. Scheduler (same recon, automated replay) | `DELETE` | 129 · Delete workflow | skip | optional |
| 130 | 12. Cleanup | `DELETE` | 130 · Delete copy recon | skip | optional |
| 131 | 12. Cleanup | `DELETE` | 131 · Delete recon | skip | optional |
| 132 | 12. Cleanup | `DELETE` | 132 · Delete group | skip | optional |

**Happy-path jumps**

- **003** Login (JSON) → **006** Current user (skip 004–005)
- **015** Link GV → **018** List my recons (skip 016–017)
- **052** Export App 1 CSV → **054** Default bridge App 1 (skip 053 JE)
- **087** Export sync App 1 → **089** Run transformation (skip 088 until a file is attached)
- **128** Get workflow run → **stop** to keep the recon, or **130** Cleanup

## Variables written

| Variable | Written by | Used by |
|---|---|---|
| `access_token`, `refresh_token` | 003 Login | every later request |
| `group_id` | 009 Create group | link recon, copy, cleanup |
| `global_variable_id` | 014 Create GV | attach on App 1 |
| `recon_id` | 021 Create recon | all `/recons/{id}/…` |
| `dimension_id` | 037 List dimensions | get / update / reorder |
| `extra_dimension_id` | 042 Create ACCOUNT | 043 delete |
| `import_run_id` / `_2` | 044 / 046 upload | 045 / 047 poll |
| `extra_bridge_mapping_id` | 058 Create extra | 077 delete |
| `bridge_mapping_id` | 059 List maps | 061 PATCH |
| `bridge_run_id` | 064 Start bridge | 066 get + websocket |
| `kickout_app`, `kickout_dim`, `kickout_source` | 067 List kickouts | 071 resolve |
| `extra_sync_mapping_id` | 082 Create extra | 094 delete |
| `sync_mapping_id` | 083 List sync | 085 PATCH |
| `filter_id` | 101 Create filter | 103–106 |
| `copy_recon_id` | 110 Copy | 111 get, 130 delete |
| `workflow_id` | 121 Create workflow | 122–129 |
| `workflow_run_id` | 125 Trigger | 128 get |

## 0. Auth

### 001 · Health

- **HTTP:** `GET /health`
- **Auth:** none
- **Success:** `200`
- **What it does:** Confirms the API is up. No token needed.
- **Next (docs):** NEXT (002): GET  002 · Health detailed

**Request**

_No body._

**Response**

```json
{"status":"ok","components":[]}
```

**Next in list:** `002` `GET` 002 · Health detailed

---

### 002 · Health detailed

- **HTTP:** `GET /health/detailed`
- **Auth:** none
- **Success:** `200`
- **What it does:** Confirms Postgres and Redis. No token needed.
- **Next (docs):** NEXT (003): POST  003 · Login (JSON)

**Request**

_No body._

**Response**

```json
{"status":"ok|degraded","components":[{"name":"postgres","ok":true,"detail":null},{"name":"redis","ok":true,"detail":null}]}
```

**Next in list:** `003` `POST` 003 · Login (JSON)

---

### 003 · Login (JSON)

- **HTTP:** `POST /auth/login`
- **Auth:** none
- **Success:** `200`
- **What it does:** Required. Saves access_token and refresh_token. Use this, not the OAuth2 login, for the rest of the run.
- **Next (docs):** NEXT (006): GET  006 · Current user
- **Note:** Skip 004 OAuth2 login and 005 Refresh unless the token expired.

**Request**

**JSON body**

```json
{
  "email": "{{email}}",
  "password": "{{password}}"
}
```

**Response**

```json
{"access_token":"jwt","refresh_token":"jwt","token_type":"bearer","audit_status":false}
```

**Next in list:** `004` `POST` 004 · Login (OAuth2 form / Swagger)

---

### 004 · Login (OAuth2 form / Swagger)

- **HTTP:** `POST /auth/token`
- **Auth:** none
- **Success:** `200`
- **What it does:** SKIP if Login (JSON) already succeeded. Same tokens, Swagger-style form body.
- **Next (docs):** NEXT (005): POST  005 · Refresh token
- **Note:** Skip this. After Login (JSON) go to Current user (or Refresh token only if the token expired).

**Request**

**application/x-www-form-urlencoded**

- `username` = `{{email}}`
- `password` = `{{password}}`

**Response**

```json
{"access_token":"jwt","refresh_token":"jwt","token_type":"bearer","audit_status":false}
```

**Next in list:** `005` `POST` 005 · Refresh token

---

### 005 · Refresh token

- **HTTP:** `POST /auth/refresh`
- **Auth:** none
- **Success:** `200`
- **What it does:** SKIP unless access_token expired. Re-saves tokens.
- **Next (docs):** NEXT (006): GET  006 · Current user
- **Note:** Skip this unless the token expired. After Login (JSON) go to Current user.

**Request**

**JSON body**

```json
{
  "refresh_token": "{{refresh_token}}"
}
```

**Response**

```json
{"access_token":"jwt","refresh_token":"jwt","token_type":"bearer","audit_status":false}
```

**Next in list:** `006` `GET` 006 · Current user

---

### 006 · Current user

- **HTTP:** `GET /users/me`
- **Auth:** Bearer `{{access_token}}`
- **Success:** `200`
- **What it does:** Sanity check that the bearer token works.
- **Next (docs):** NEXT (007): GET  007 · List my groups
Then open folder: 1. Prerequisites — group and global variable

**Request**

_No body._

**Response**

```json
{"id":"uuid","email":"recon@admin.com","username":"string","is_active":true,"user_types":["recon_user"],"created_at":"ISO-8601","is_superuser":true,"is_platform_admin":false}
```

**Next in list:** `007` `GET` 007 · List my groups

---

## 1. Prerequisites — group and global variable

### 007 · List my groups

- **HTTP:** `GET /groups/mine`
- **Auth:** Bearer `{{access_token}}`
- **Success:** `200`
- **What it does:** Read-only. Does not write group_id.
- **Next (docs):** NEXT (008): GET  008 · List groups

**Request**

_No body._

**Response**

JSON array of the object below.

```json
{"id":"uuid","name":"Postman Pipeline Group …","created_by":"username","created_at":"ISO-8601"}
```

**Next in list:** `008` `GET` 008 · List groups

---

### 008 · List groups

- **HTTP:** `GET /groups`
- **Auth:** Bearer `{{access_token}}`
- **Success:** `200`
- **What it does:** Read-only. Does not write group_id.
- **Next (docs):** NEXT (009): POST  009 · Create group

**Request**

_No body._

**Response**

JSON array of the object below.

```json
{"id":"uuid","name":"Postman Pipeline Group …","created_by":"username","created_at":"ISO-8601"}
```

**Next in list:** `009` `POST` 009 · Create group

---

### 009 · Create group

- **HTTP:** `POST /groups`
- **Auth:** Bearer `{{access_token}}`
- **Success:** `201`
- **What it does:** Required. Saves group_id. Copy recon later needs this id.
- **Next (docs):** NEXT (010): GET  010 · Get group

**Request**

**JSON body**

```json
{
  "name": "{{group_name}}"
}
```

**Response**

```json
{"id":"uuid","name":"Postman Pipeline Group …","created_by":"username","created_at":"ISO-8601"}
```

**Next in list:** `010` `GET` 010 · Get group

---

### 010 · Get group

- **HTTP:** `GET /groups/{{group_id}}`
- **Auth:** Bearer `{{access_token}}`
- **Success:** `200`
- **What it does:** Confirms the group exists.
- **Next (docs):** NEXT (011): GET  011 · Group details

**Request**

_No body._

**Response**

```json
{"id":"uuid","name":"Postman Pipeline Group …","created_by":"username","created_at":"ISO-8601"}
```

**Next in list:** `011` `GET` 011 · Group details

---

### 011 · Group details

- **HTTP:** `GET /groups/{{group_id}}/details`
- **Auth:** Bearer `{{access_token}}`
- **Success:** `200`
- **What it does:** Shows members, GVs, linked recons.
- **Next (docs):** NEXT (012): PATCH  012 · Rename group

**Request**

_No body._

**Response**

```json
{"id":"uuid","name":"…","admin_names":[],"member_names":[],"lob_names":[],"team_names":[],"role_names":[],"recon_names":[],"gv_names":["Postman_FX_…"]}
```

**Next in list:** `012` `PATCH` 012 · Rename group

---

### 012 · Rename group

- **HTTP:** `PATCH /groups/{{group_id}}`
- **Auth:** Bearer `{{access_token}}`
- **Success:** `200`
- **What it does:** Uses the same unique group_name. Harmless.
- **Next (docs):** NEXT (013): GET  013 · List global variables

**Request**

**JSON body**

```json
{
  "name": "{{group_name}}"
}
```

**Response**

```json
{"id":"uuid","name":"Postman Pipeline Group …","created_by":"username","created_at":"ISO-8601"}
```

**Next in list:** `013` `GET` 013 · List global variables

---

### 013 · List global variables

- **HTTP:** `GET /global-variables`
- **Auth:** Bearer `{{access_token}}`
- **Success:** `200`
- **What it does:** Read-only catalog.
- **Next (docs):** NEXT (014): POST  014 · Create global variable

**Request**

_No body._

**Response**

JSON array of the object below.

```json
{"id":"uuid","name":"Postman_FX_…"}
```

**Next in list:** `014` `POST` 014 · Create global variable

---

### 014 · Create global variable

- **HTTP:** `POST /global-variables`
- **Auth:** Bearer `{{access_token}}`
- **Success:** `201`
- **What it does:** Required for app attach. Saves global_variable_id.
- **Next (docs):** NEXT (015): POST  015 · Link global variable to group

**Request**

**JSON body**

```json
{
  "name": "{{gv_name}}"
}
```

**Response**

```json
{"id":"uuid","name":"Postman_FX_…"}
```

**Next in list:** `015` `POST` 015 · Link global variable to group

---

### 015 · Link global variable to group

- **HTTP:** `POST /groups/{{group_id}}/global-variables`
- **Auth:** Bearer `{{access_token}}`
- **Success:** `204`
- **What it does:** Attaches the GV catalog name to the group.
- **Next (docs):** NEXT (018): GET  018 · List my recons
Then open folder: 2. Select — create recon
- **Note:** Skip 016 Unlink and 017 re-link unless you are testing unlink.

**Request**

**JSON body**

```json
{
  "name": "{{gv_name}}"
}
```

**Response**

Empty body. HTTP **204 No Content**.

**Next in list:** `016` `DELETE` 016 · Unlink global variable from group

---

### 016 · Unlink global variable from group

- **HTTP:** `DELETE /groups/{{group_id}}/global-variables/{{gv_name}}`
- **Auth:** Bearer `{{access_token}}`
- **Success:** `204`
- **What it does:** SKIP unless you want to test unlink. If you run it, you must run the next request to re-link.
- **Next (docs):** NEXT (017): POST  017 · Link global variable to group (again)
- **Note:** Skip unless testing unlink. After Link GV to group go to List my recons (folder 2).

**Request**

_No body._

**Response**

Empty body. HTTP **204 No Content**.

**Next in list:** `017` `POST` 017 · Link global variable to group (again)

---

### 017 · Link global variable to group (again)

- **HTTP:** `POST /groups/{{group_id}}/global-variables`
- **Auth:** Bearer `{{access_token}}`
- **Success:** `204`
- **What it does:** Only needed if you unlinked. Safe to send anyway.
- **Next (docs):** NEXT (018): GET  018 · List my recons
Then open folder: 2. Select — create recon

**Request**

**JSON body**

```json
{
  "name": "{{gv_name}}"
}
```

**Response**

Empty body. HTTP **204 No Content**.

**Next in list:** `018` `GET` 018 · List my recons

---

## 2. Select — create recon

### 018 · List my recons

- **HTTP:** `GET /recons?page=1&page_size=25`
- **Auth:** Bearer `{{access_token}}`
- **Success:** `200`
- **What it does:** Select-page list. Read-only.
- **Next (docs):** NEXT (019): GET  019 · List available recons

**Request**

**Query**

- `page` = `1`
- `page_size` = `25`

**Response**

_See FastAPI `/docs`._

**Next in list:** `019` `GET` 019 · List available recons

---

### 019 · List available recons

- **HTTP:** `GET /recons/available?page=1&page_size=25`
- **Auth:** Bearer `{{access_token}}`
- **Success:** `200`
- **What it does:** Recons the caller can open. Read-only.
- **Next (docs):** NEXT (020): GET  020 · Recon directory (security picklist)

**Request**

**Query**

- `page` = `1`
- `page_size` = `25`

**Response**

_See FastAPI `/docs`._

**Next in list:** `020` `GET` 020 · Recon directory (security picklist)

---

### 020 · Recon directory (security picklist)

- **HTTP:** `GET /recons/directory`
- **Auth:** Bearer `{{access_token}}`
- **Success:** `200`
- **What it does:** Security picklist. Read-only.
- **Next (docs):** NEXT (021): POST  021 · Create recon

**Request**

_No body._

**Response**

JSON array of the object below. Paginated with `page` / `page_size`.

```json
{"id":"uuid","name":"Postman_Mock_Set1_…","description":"string|null","group_name":"string|null","owner":"username","status":"string","archived":false,"last_modified":"ISO-8601"}
```

**Next in list:** `021` `POST` 021 · Create recon

---

### 021 · Create recon

- **HTTP:** `POST /recons`
- **Auth:** Bearer `{{access_token}}`
- **Success:** `201`
- **What it does:** Required. Saves recon_id. Seeds App 1, App 2, YEAR/PERIOD/AMOUNT.
- **Next (docs):** NEXT (022): GET  022 · Get recon

**Request**

**JSON body**

```json
{
  "name": "{{recon_name}}",
  "description": "Postman end-to-end from Mock Set 1"
}
```

**Response**

```json
{"id":"uuid","name":"Postman_Mock_Set1_…","description":"string|null","group_name":"string|null","owner":"username","status":"string","archived":false,"last_modified":"ISO-8601"}
```

**Next in list:** `022` `GET` 022 · Get recon

---

### 022 · Get recon

- **HTTP:** `GET /recons/{{recon_id}}`
- **Auth:** Bearer `{{access_token}}`
- **Success:** `200`
- **What it does:** Confirms recon_id.
- **Next (docs):** NEXT (023): PATCH  023 · Update recon (name / description)

**Request**

_No body._

**Response**

```json
{"id":"uuid","name":"Postman_Mock_Set1_…","description":"string|null","group_name":"string|null","owner":"username","status":"string","archived":false,"last_modified":"ISO-8601"}
```

**Next in list:** `023` `PATCH` 023 · Update recon (name / description)

---

### 023 · Update recon (name / description)

- **HTTP:** `PATCH /recons/{{recon_id}}`
- **Auth:** Bearer `{{access_token}}`
- **Success:** `200`
- **What it does:** Rename/description only. Does not archive.
- **Next (docs):** NEXT (024): POST  024 · Link recon to group

**Request**

**JSON body**

```json
{
  "name": "{{recon_name}}",
  "description": "Updated from Postman"
}
```

**Response**

```json
{"id":"uuid","name":"Postman_Mock_Set1_…","description":"string|null","group_name":"string|null","owner":"username","status":"string","archived":false,"last_modified":"ISO-8601"}
```

**Next in list:** `024` `POST` 024 · Link recon to group

---

### 024 · Link recon to group

- **HTTP:** `POST /recons/{{recon_id}}/groups/{{group_id}}`
- **Auth:** Bearer `{{access_token}}`
- **Success:** `200`
- **What it does:** Required. Same second step the UI Create dialog runs.
- **Next (docs):** NEXT (025): GET  025 · List recon apps
Then open folder: 3. Dimension Linking — applications

**Request**

_No body._

**Response**

```json
{"id":"uuid","name":"Postman_Mock_Set1_…","description":"string|null","group_name":"string|null","owner":"username","status":"string","archived":false,"last_modified":"ISO-8601"}
```

**Next in list:** `025` `GET` 025 · List recon apps

---

## 3. Dimension Linking — applications

### 025 · List recon apps

- **HTTP:** `GET /recons/{{recon_id}}/apps`
- **Auth:** Bearer `{{access_token}}`
- **Success:** `200`
- **What it does:** Should show App 1 and App 2.
- **Next (docs):** NEXT (026): PATCH  026 · Update App 1

**Request**

_No body._

**Response**

JSON array of the object below.

```json
{"id":"uuid","recon_id":"uuid","app_number":1,"name":"App1","description":"string|null","delimiter":",","currency_delimiter":null,"currency_symbol":null,"thousands_separator":",","has_header":true,"global_variable_id":"uuid|null","global_variable_name":"string|null","created_at":"ISO-8601","updated_at":"ISO-8601"}
```

**Next in list:** `026` `PATCH` 026 · Update App 1

---

### 026 · Update App 1

- **HTTP:** `PATCH /recons/{{recon_id}}/apps/1`
- **Auth:** Bearer `{{access_token}}`
- **Success:** `200`
- **What it does:** Sets name App1 and CSV parse options.
- **Next (docs):** NEXT (027): PATCH  027 · Update App 2

**Request**

**JSON body**

```json
{
  "name": "App1",
  "description": "Mock Set 1 left file",
  "delimiter": ",",
  "has_header": true,
  "thousands_separator": ","
}
```

**Response**

```json
{"id":"uuid","recon_id":"uuid","app_number":1,"name":"App1","description":"string|null","delimiter":",","currency_delimiter":null,"currency_symbol":null,"thousands_separator":",","has_header":true,"global_variable_id":"uuid|null","global_variable_name":"string|null","created_at":"ISO-8601","updated_at":"ISO-8601"}
```

**Next in list:** `027` `PATCH` 027 · Update App 2

---

### 027 · Update App 2

- **HTTP:** `PATCH /recons/{{recon_id}}/apps/2`
- **Auth:** Bearer `{{access_token}}`
- **Success:** `200`
- **What it does:** Sets name App2 and CSV parse options.
- **Next (docs):** NEXT (028): PATCH  028 · Attach global variable on App 1

**Request**

**JSON body**

```json
{
  "name": "App2",
  "description": "Mock Set 1 right file",
  "delimiter": ",",
  "has_header": true,
  "thousands_separator": ","
}
```

**Response**

```json
{"id":"uuid","recon_id":"uuid","app_number":1,"name":"App1","description":"string|null","delimiter":",","currency_delimiter":null,"currency_symbol":null,"thousands_separator":",","has_header":true,"global_variable_id":"uuid|null","global_variable_name":"string|null","created_at":"ISO-8601","updated_at":"ISO-8601"}
```

**Next in list:** `028` `PATCH` 028 · Attach global variable on App 1

---

### 028 · Attach global variable on App 1

- **HTTP:** `PATCH /recons/{{recon_id}}/apps/1`
- **Auth:** Bearer `{{access_token}}`
- **Success:** `200`
- **What it does:** Stores global_variable_id on the app.
- **Next (docs):** NEXT (029): PATCH  029 · Detach global variable on App 1

**Request**

**JSON body**

```json
{
  "global_variable_id": "{{global_variable_id}}"
}
```

**Response**

```json
{"id":"uuid","recon_id":"uuid","app_number":1,"name":"App1","description":"string|null","delimiter":",","currency_delimiter":null,"currency_symbol":null,"thousands_separator":",","has_header":true,"global_variable_id":"uuid|null","global_variable_name":"string|null","created_at":"ISO-8601","updated_at":"ISO-8601"}
```

**Next in list:** `029` `PATCH` 029 · Detach global variable on App 1

---

### 029 · Detach global variable on App 1

- **HTTP:** `PATCH /recons/{{recon_id}}/apps/1`
- **Auth:** Bearer `{{access_token}}`
- **Success:** `200`
- **What it does:** Sets global_variable_id to null.
- **Next (docs):** NEXT (030): PATCH  030 · Attach global variable on App 1 (again)

**Request**

**JSON body**

```json
{
  "global_variable_id": null
}
```

**Response**

```json
{"id":"uuid","recon_id":"uuid","app_number":1,"name":"App1","description":"string|null","delimiter":",","currency_delimiter":null,"currency_symbol":null,"thousands_separator":",","has_header":true,"global_variable_id":"uuid|null","global_variable_name":"string|null","created_at":"ISO-8601","updated_at":"ISO-8601"}
```

**Next in list:** `030` `PATCH` 030 · Attach global variable on App 1 (again)

---

### 030 · Attach global variable on App 1 (again)

- **HTTP:** `PATCH /recons/{{recon_id}}/apps/1`
- **Auth:** Bearer `{{access_token}}`
- **Success:** `200`
- **What it does:** Re-attach so later screens show the GV.
- **Next (docs):** NEXT (031): POST  031 · Add App 3

**Request**

**JSON body**

```json
{
  "global_variable_id": "{{global_variable_id}}"
}
```

**Response**

```json
{"id":"uuid","recon_id":"uuid","app_number":1,"name":"App1","description":"string|null","delimiter":",","currency_delimiter":null,"currency_symbol":null,"thousands_separator":",","has_header":true,"global_variable_id":"uuid|null","global_variable_name":"string|null","created_at":"ISO-8601","updated_at":"ISO-8601"}
```

**Next in list:** `031` `POST` 031 · Add App 3

---

### 031 · Add App 3

- **HTTP:** `POST /recons/{{recon_id}}/apps`
- **Auth:** Bearer `{{access_token}}`
- **Success:** `201`
- **What it does:** Creates a third app so the next delete can run. Max 5 apps.
- **Next (docs):** NEXT (032): DELETE  032 · Delete App 3

**Request**

**JSON body**

```json
{
  "app_number": 3,
  "name": "App3",
  "description": "Optional third source",
  "delimiter": ",",
  "has_header": true,
  "thousands_separator": ","
}
```

**Response**

```json
{"id":"uuid","recon_id":"uuid","app_number":1,"name":"App1","description":"string|null","delimiter":",","currency_delimiter":null,"currency_symbol":null,"thousands_separator":",","has_header":true,"global_variable_id":"uuid|null","global_variable_name":"string|null","created_at":"ISO-8601","updated_at":"ISO-8601"}
```

**Next in list:** `032` `DELETE` 032 · Delete App 3

---

### 032 · Delete App 3

- **HTTP:** `DELETE /recons/{{recon_id}}/apps/3`
- **Auth:** Bearer `{{access_token}}`
- **Success:** `204`
- **What it does:** Allowed because two apps remain. 409 if you try to go below 2.
- **Next (docs):** NEXT (033): GET  033 · List recon apps (after delete)

**Request**

_No body._

**Response**

Empty body. HTTP **204 No Content**.

**Next in list:** `033` `GET` 033 · List recon apps (after delete)

---

### 033 · List recon apps (after delete)

- **HTTP:** `GET /recons/{{recon_id}}/apps`
- **Auth:** Bearer `{{access_token}}`
- **Success:** `200`
- **What it does:** Should be App 1 and App 2 again.
- **Next (docs):** NEXT (034): GET  034 · List dimensions
Then open folder: 4. Dimension Linking — dimensions

**Request**

_No body._

**Response**

JSON array of the object below.

```json
{"id":"uuid","recon_id":"uuid","app_number":1,"name":"App1","description":"string|null","delimiter":",","currency_delimiter":null,"currency_symbol":null,"thousands_separator":",","has_header":true,"global_variable_id":"uuid|null","global_variable_name":"string|null","created_at":"ISO-8601","updated_at":"ISO-8601"}
```

**Next in list:** `034` `GET` 034 · List dimensions

---

## 4. Dimension Linking — dimensions

### 034 · List dimensions

- **HTTP:** `GET /recons/{{recon_id}}/dimensions`
- **Auth:** Bearer `{{access_token}}`
- **Success:** `200`
- **What it does:** YEAR/PERIOD/AMOUNT from create. Custom dims come after import.
- **Next (docs):** NEXT (035): POST  035 · Seed mandatory YEAR/PERIOD/AMOUNT

**Request**

_No body._

**Response**

JSON array of the object below.

```json
{"id":"uuid","recon_id":"uuid","name":"ENTITY","position":3,"is_mandatory":false,"mappings":[{"app_number":1,"in_file":true,"column_location":"3","default_value":null,"is_active":true}]}
```

**Next in list:** `035` `POST` 035 · Seed mandatory YEAR/PERIOD/AMOUNT

---

### 035 · Seed mandatory YEAR/PERIOD/AMOUNT

- **HTTP:** `POST /recons/{{recon_id}}/dimensions/seed-mandatory`
- **Auth:** Bearer `{{access_token}}`
- **Success:** `200`
- **What it does:** Idempotent. Safe if create already seeded them.
- **Next (docs):** NEXT (036): POST  036 · Import dimensions CSV (Mock template)

**Request**

_No body._

**Response**

JSON array of the object below. Full list after the write.

```json
{"id":"uuid","recon_id":"uuid","name":"ENTITY","position":3,"is_mandatory":false,"mappings":[{"app_number":1,"in_file":true,"column_location":"3","default_value":null,"is_active":true}]}
```

**Next in list:** `036` `POST` 036 · Import dimensions CSV (Mock template)

---

### 036 · Import dimensions CSV (Mock template)

- **HTTP:** `POST /recons/{{recon_id}}/dimensions/import`
- **Auth:** Bearer `{{access_token}}`
- **Success:** `200`
- **What it does:** Required. Uses Mock Set 1 DimensionTemplate. File path is prefilled.
- **Next (docs):** NEXT (037): GET  037 · List dimensions (save custom id)

**Request**

**multipart/form-data**

- `file` *(file)* → `C:/Users/KannanSubramaniyan/API_Modal/Mock/Data_Set 1 Karan/DimensionTemplate_App1_App2.csv`

**Response**

JSON array of the object below. Full list after the write.

```json
{"id":"uuid","recon_id":"uuid","name":"ENTITY","position":3,"is_mandatory":false,"mappings":[{"app_number":1,"in_file":true,"column_location":"3","default_value":null,"is_active":true}]}
```

**Next in list:** `037` `GET` 037 · List dimensions (save custom id)

---

### 037 · List dimensions (save custom id)

- **HTTP:** `GET /recons/{{recon_id}}/dimensions`
- **Auth:** Bearer `{{access_token}}`
- **Success:** `200`
- **What it does:** Saves dimension_id (first non-mandatory dim) for get/update/reorder.
- **Next (docs):** NEXT (038): GET  038 · Get dimension

**Request**

_No body._

**Response**

JSON array of the object below.

```json
{"id":"uuid","recon_id":"uuid","name":"ENTITY","position":3,"is_mandatory":false,"mappings":[{"app_number":1,"in_file":true,"column_location":"3","default_value":null,"is_active":true}]}
```

**Next in list:** `038` `GET` 038 · Get dimension

---

### 038 · Get dimension

- **HTTP:** `GET /recons/{{recon_id}}/dimensions/{{dimension_id}}`
- **Auth:** Bearer `{{access_token}}`
- **Success:** `200`
- **What it does:** Needs dimension_id from the previous list.
- **Next (docs):** NEXT (039): PATCH  039 · Update dimension mappings

**Request**

_No body._

**Response**

```json
{"id":"uuid","recon_id":"uuid","name":"ENTITY","position":3,"is_mandatory":false,"mappings":[{"app_number":1,"in_file":true,"column_location":"3","default_value":null,"is_active":true}]}
```

**Next in list:** `039` `PATCH` 039 · Update dimension mappings

---

### 039 · Update dimension mappings

- **HTTP:** `PATCH /recons/{{recon_id}}/dimensions/{{dimension_id}}`
- **Auth:** Bearer `{{access_token}}`
- **Success:** `200`
- **What it does:** Column map for apps 1 and 2.
- **Next (docs):** NEXT (040): POST  040 · Reorder dimension

**Request**

**JSON body**

```json
{
  "mappings": [
    {
      "app_number": 1,
      "in_file": true,
      "column_location": "3",
      "is_active": true
    },
    {
      "app_number": 2,
      "in_file": true,
      "column_location": "3",
      "is_active": true
    }
  ]
}
```

**Response**

```json
{"id":"uuid","recon_id":"uuid","name":"ENTITY","position":3,"is_mandatory":false,"mappings":[{"app_number":1,"in_file":true,"column_location":"3","default_value":null,"is_active":true}]}
```

**Next in list:** `040` `POST` 040 · Reorder dimension

---

### 040 · Reorder dimension

- **HTTP:** `POST /recons/{{recon_id}}/dimensions/{{dimension_id}}/reorder`
- **Auth:** Bearer `{{access_token}}`
- **Success:** `200`
- **What it does:** Moves that dimension to position 3.
- **Next (docs):** NEXT (041): GET  041 · Export dimensions CSV

**Request**

**JSON body**

```json
{
  "new_position": 3
}
```

**Response**

JSON array of the object below. Full list after the move.

```json
{"id":"uuid","recon_id":"uuid","name":"ENTITY","position":3,"is_mandatory":false,"mappings":[{"app_number":1,"in_file":true,"column_location":"3","default_value":null,"is_active":true}]}
```

**Next in list:** `041` `GET` 041 · Export dimensions CSV

---

### 041 · Export dimensions CSV

- **HTTP:** `GET /recons/{{recon_id}}/dimensions/export`
- **Auth:** Bearer `{{access_token}}`
- **Success:** `200`
- **What it does:** Downloads the current column map.
- **Next (docs):** NEXT (042): POST  042 · Create extra dimension ACCOUNT

**Request**

_No body._

**Response**

`text/csv` download (`Content-Disposition: attachment`). Not JSON. Header `serial_no` then per-app dimension/in_file/column/default/active.

**Next in list:** `042` `POST` 042 · Create extra dimension ACCOUNT

---

### 042 · Create extra dimension ACCOUNT

- **HTTP:** `POST /recons/{{recon_id}}/dimensions`
- **Auth:** Bearer `{{access_token}}`
- **Success:** `201`
- **What it does:** Saves extra_dimension_id. Uses default_value UNMAPPED (not in file).
- **Next (docs):** NEXT (043): DELETE  043 · Delete extra dimension ACCOUNT

**Request**

**JSON body**

```json
{
  "name": "ACCOUNT",
  "mappings": [
    {
      "app_number": 1,
      "in_file": false,
      "default_value": "UNMAPPED",
      "is_active": true
    },
    {
      "app_number": 2,
      "in_file": false,
      "default_value": "UNMAPPED",
      "is_active": true
    }
  ]
}
```

**Response**

```json
{"id":"uuid","recon_id":"uuid","name":"ENTITY","position":3,"is_mandatory":false,"mappings":[{"app_number":1,"in_file":true,"column_location":"3","default_value":null,"is_active":true}]}
```

**Next in list:** `043` `DELETE` 043 · Delete extra dimension ACCOUNT

---

### 043 · Delete extra dimension ACCOUNT

- **HTTP:** `DELETE /recons/{{recon_id}}/dimensions/{{extra_dimension_id}}`
- **Auth:** Bearer `{{access_token}}`
- **Success:** `204`
- **What it does:** YEAR/PERIOD/AMOUNT cannot be deleted. This only deletes ACCOUNT.
- **Next (docs):** NEXT (044): POST  044 · Upload App 1 file
Then open folder: 5. Run Import

**Request**

_No body._

**Response**

Empty body. HTTP **204 No Content**.

**Next in list:** `044` `POST` 044 · Upload App 1 file

---

## 5. Run Import

### 044 · Upload App 1 file

- **HTTP:** `POST /recons/{{recon_id}}/imports`
- **Auth:** Bearer `{{access_token}}`
- **Success:** `201`
- **What it does:** Required. Prefills Mock App1_Data.csv. Saves import_run_id.
- **Next (docs):** NEXT (045): GET  045 · Poll App 1 import run

**Request**

**multipart/form-data**

- `app_number` = `1`
- `je_flag` = `false`
- `file` *(file)* → `C:/Users/KannanSubramaniyan/API_Modal/Mock/Data_Set 1 Karan/App1_Data.csv`

**Response**

```json
{"id":"uuid","recon_id":"uuid","app_number":1,"file_name":"App1_Data.csv","status":"pending|processing|completed|failed","row_count":40,"error_message":null,"je_flag":false,"created_by":"username","created_at":"ISO-8601","started_at":"ISO-8601|null","completed_at":"ISO-8601|null"}
```

**Next in list:** `045` `GET` 045 · Poll App 1 import run

---

### 045 · Poll App 1 import run

- **HTTP:** `GET /recons/{{recon_id}}/imports/{{import_run_id}}`
- **Auth:** Bearer `{{access_token}}`
- **Success:** `200`
- **Note:** WAIT: Send again until status is completed (not pending). Then continue.
- **Next (docs):** NEXT (046): POST  046 · Upload App 2 file

**Request**

_No body._

**Response**

```json
{"id":"uuid","recon_id":"uuid","app_number":1,"file_name":"App1_Data.csv","status":"pending|processing|completed|failed","row_count":40,"error_message":null,"je_flag":false,"created_by":"username","created_at":"ISO-8601","started_at":"ISO-8601|null","completed_at":"ISO-8601|null"}
```

**Next in list:** `046` `POST` 046 · Upload App 2 file

---

### 046 · Upload App 2 file

- **HTTP:** `POST /recons/{{recon_id}}/imports`
- **Auth:** Bearer `{{access_token}}`
- **Success:** `201`
- **What it does:** Required. Prefills Mock App2_Data.csv. Saves import_run_id_2.
- **Next (docs):** NEXT (047): GET  047 · Poll App 2 import run

**Request**

**multipart/form-data**

- `app_number` = `2`
- `je_flag` = `false`
- `file` *(file)* → `C:/Users/KannanSubramaniyan/API_Modal/Mock/Data_Set 1 Karan/App2_Data.csv`

**Response**

```json
{"id":"uuid","recon_id":"uuid","app_number":1,"file_name":"App1_Data.csv","status":"pending|processing|completed|failed","row_count":40,"error_message":null,"je_flag":false,"created_by":"username","created_at":"ISO-8601","started_at":"ISO-8601|null","completed_at":"ISO-8601|null"}
```

**Next in list:** `047` `GET` 047 · Poll App 2 import run

---

### 047 · Poll App 2 import run

- **HTTP:** `GET /recons/{{recon_id}}/imports/{{import_run_id_2}}`
- **Auth:** Bearer `{{access_token}}`
- **Success:** `200`
- **Note:** WAIT: Send again until status is completed. Then continue.
- **Next (docs):** NEXT (048): GET  048 · List import history

**Request**

_No body._

**Response**

```json
{"id":"uuid","recon_id":"uuid","app_number":1,"file_name":"App1_Data.csv","status":"pending|processing|completed|failed","row_count":40,"error_message":null,"je_flag":false,"created_by":"username","created_at":"ISO-8601","started_at":"ISO-8601|null","completed_at":"ISO-8601|null"}
```

**Next in list:** `048` `GET` 048 · List import history

---

### 048 · List import history

- **HTTP:** `GET /recons/{{recon_id}}/imports?page=1&page_size=50`
- **Auth:** Bearer `{{access_token}}`
- **Success:** `200`
- **What it does:** Should show at least one row per app.
- **Next (docs):** NEXT (049): GET  049 · List imported rows (App 1)

**Request**

**Query**

- `page` = `1`
- `page_size` = `50`

**Response**

_See FastAPI `/docs`._

**Next in list:** `049` `GET` 049 · List imported rows (App 1)

---

### 049 · List imported rows (App 1)

- **HTTP:** `GET /recons/{{recon_id}}/imports/data?app_number=1&page=1&page_size=25`
- **Auth:** Bearer `{{access_token}}`
- **Success:** `200`
- **What it does:** Mapped YEAR/PERIOD/AMOUNT/ENTITY rows.
- **Next (docs):** NEXT (050): GET  050 · List imported rows (App 2)

**Request**

**Query**

- `app_number` = `1`
- `page` = `1`
- `page_size` = `25`

**Response**

_See FastAPI `/docs`._

**Next in list:** `050` `GET` 050 · List imported rows (App 2)

---

### 050 · List imported rows (App 2)

- **HTTP:** `GET /recons/{{recon_id}}/imports/data?app_number=2&page=1&page_size=25`
- **Auth:** Bearer `{{access_token}}`
- **Success:** `200`
- **What it does:** Mapped YEAR/PERIOD/AMOUNT/ENTITY rows.
- **Next (docs):** NEXT (051): GET  051 · Export imported data ZIP (all apps)

**Request**

**Query**

- `app_number` = `2`
- `page` = `1`
- `page_size` = `25`

**Response**

_See FastAPI `/docs`._

**Next in list:** `051` `GET` 051 · Export imported data ZIP (all apps)

---

### 051 · Export imported data ZIP (all apps)

- **HTTP:** `GET /recons/{{recon_id}}/imports/export`
- **Auth:** Bearer `{{access_token}}`
- **Success:** `200`
- **What it does:** Downloads a zip of both apps.
- **Next (docs):** NEXT (052): GET  052 · Export imported data CSV (App 1)

**Request**

_No body._

**Response**

`application/zip` download (`Source_Data_Export.zip`). Not JSON.

**Next in list:** `052` `GET` 052 · Export imported data CSV (App 1)

---

### 052 · Export imported data CSV (App 1)

- **HTTP:** `GET /recons/{{recon_id}}/imports/export?app_number=1`
- **Auth:** Bearer `{{access_token}}`
- **Success:** `200`
- **What it does:** Downloads App 1 CSV only.
- **Next (docs):** NEXT (054): POST  054 · Default bridge mappings App 1
Then open folder: 6. Bridge Members
- **Note:** Skip 053 JE upload unless you want a second App 1 history row.

**Request**

**Query**

- `app_number` = `1`

**Response**

_See FastAPI `/docs`._

**Next in list:** `053` `POST` 053 · Upload App 1 as journal entry (optional)

---

### 053 · Upload App 1 as journal entry (optional)

- **HTTP:** `POST /recons/{{recon_id}}/imports`
- **Auth:** Bearer `{{access_token}}`
- **Success:** `201`
- **What it does:** SKIP unless you want a second App 1 history row with je_flag. Same file, je_flag true.
- **Next (docs):** NEXT (054): POST  054 · Default bridge mappings App 1
Then open folder: 6. Bridge Members
- **Note:** Skip unless you want JE history. After Export App 1 CSV go to Default bridge mappings App 1.

**Request**

**multipart/form-data**

- `app_number` = `1`
- `je_flag` = `true`
- `file` *(file)* → `C:/Users/KannanSubramaniyan/API_Modal/Mock/Data_Set 1 Karan/App1_Data.csv`

**Response**

```json
{"id":"uuid","recon_id":"uuid","app_number":1,"file_name":"App1_Data.csv","status":"pending|processing|completed|failed","row_count":40,"error_message":null,"je_flag":false,"created_by":"username","created_at":"ISO-8601","started_at":"ISO-8601|null","completed_at":"ISO-8601|null"}
```

**Next in list:** `054` `POST` 054 · Default bridge mappings App 1

---

## 6. Bridge Members

### 054 · Default bridge mappings App 1

- **HTTP:** `POST /recons/{{recon_id}}/bridge-mappings/default?app_number=1`
- **Auth:** Bearer `{{access_token}}`
- **Success:** `200`
- **What it does:** Identity-maps imported members, wiping prior App 1 maps. Mock CSV import next overwrites this.
- **Next (docs):** NEXT (055): POST  055 · Default bridge mappings App 2

**Request**

**Query**

- `app_number` = `1`

**Response**

_See FastAPI `/docs`._

**Next in list:** `055` `POST` 055 · Default bridge mappings App 2

---

### 055 · Default bridge mappings App 2

- **HTTP:** `POST /recons/{{recon_id}}/bridge-mappings/default?app_number=2`
- **Auth:** Bearer `{{access_token}}`
- **Success:** `200`
- **What it does:** Same for App 2.
- **Next (docs):** NEXT (056): POST  056 · Import bridge CSV App 1 (Mock)

**Request**

**Query**

- `app_number` = `2`

**Response**

_See FastAPI `/docs`._

**Next in list:** `056` `POST` 056 · Import bridge CSV App 1 (Mock)

---

### 056 · Import bridge CSV App 1 (Mock)

- **HTTP:** `POST /recons/{{recon_id}}/bridge-mappings/import`
- **Auth:** Bearer `{{access_token}}`
- **Success:** `200`
- **What it does:** Required. Overwrites App 1 maps with Mock App1_Bridge_Export.csv.
- **Next (docs):** NEXT (057): POST  057 · Import bridge CSV App 2 (Mock)

**Request**

**multipart/form-data**

- `app_number` = `1`
- `overwrite` = `true`
- `file` *(file)* → `C:/Users/KannanSubramaniyan/API_Modal/Mock/Data_Set 1 Karan/App1_Bridge_Export.csv`

**Response**

JSON array of the object below.

```json
{"id":"uuid","recon_id":"uuid","app_number":1,"app_name":"App1","app_type":"App1","dimension_name":"ENTITY","source_member":"1","bridge_member":"1","is_kickout":false,"flip_sign":false,"dim_comment":null,"bridge_comment":null,"je_comment":null,"is_invalid":false,"created_at":"ISO-8601","updated_at":"ISO-8601"}
```

**Next in list:** `057` `POST` 057 · Import bridge CSV App 2 (Mock)

---

### 057 · Import bridge CSV App 2 (Mock)

- **HTTP:** `POST /recons/{{recon_id}}/bridge-mappings/import`
- **Auth:** Bearer `{{access_token}}`
- **Success:** `200`
- **What it does:** Required. Overwrites App 2 maps with Mock App2_Bridge_Export.csv.
- **Next (docs):** NEXT (058): POST  058 · Create bridge mapping (extra)

**Request**

**multipart/form-data**

- `app_number` = `2`
- `overwrite` = `true`
- `file` *(file)* → `C:/Users/KannanSubramaniyan/API_Modal/Mock/Data_Set 1 Karan/App2_Bridge_Export.csv`

**Response**

JSON array of the object below.

```json
{"id":"uuid","recon_id":"uuid","app_number":1,"app_name":"App1","app_type":"App1","dimension_name":"ENTITY","source_member":"1","bridge_member":"1","is_kickout":false,"flip_sign":false,"dim_comment":null,"bridge_comment":null,"je_comment":null,"is_invalid":false,"created_at":"ISO-8601","updated_at":"ISO-8601"}
```

**Next in list:** `058` `POST` 058 · Create bridge mapping (extra)

---

### 058 · Create bridge mapping (extra)

- **HTTP:** `POST /recons/{{recon_id}}/bridge-mappings`
- **Auth:** Bearer `{{access_token}}`
- **Success:** `201`
- **What it does:** Creates POSTMAN_EXTRA so delete later has a safe id. Saves extra_bridge_mapping_id.
- **Next (docs):** NEXT (059): GET  059 · List bridge mappings App 1

**Request**

**JSON body**

```json
{
  "app_number": 1,
  "dimension_name": "ENTITY",
  "source_member": "POSTMAN_EXTRA",
  "bridge_member": "POSTMAN_EXTRA",
  "flip_sign": false,
  "dim_comment": null,
  "bridge_comment": null,
  "je_comment": "optional JE comment",
  "is_invalid": false
}
```

**Response**

```json
{"id":"uuid","recon_id":"uuid","app_number":1,"app_name":"App1","app_type":"App1","dimension_name":"ENTITY","source_member":"1","bridge_member":"1","is_kickout":false,"flip_sign":false,"dim_comment":null,"bridge_comment":null,"je_comment":null,"is_invalid":false,"created_at":"ISO-8601","updated_at":"ISO-8601"}
```

**Next in list:** `059` `GET` 059 · List bridge mappings App 1

---

### 059 · List bridge mappings App 1

- **HTTP:** `GET /recons/{{recon_id}}/bridge-mappings?page=1&page_size=50&app_number=1`
- **Auth:** Bearer `{{access_token}}`
- **Success:** `200`
- **What it does:** Also saves bridge_mapping_id from the first row for the PATCH that follows.
- **Next (docs):** NEXT (060): GET  060 · List bridge mappings App 2

**Request**

**Query**

- `page` = `1`
- `page_size` = `50`
- `app_number` = `1`

**Response**

_See FastAPI `/docs`._

**Next in list:** `060` `GET` 060 · List bridge mappings App 2

---

### 060 · List bridge mappings App 2

- **HTTP:** `GET /recons/{{recon_id}}/bridge-mappings?page=1&page_size=50&app_number=2`
- **Auth:** Bearer `{{access_token}}`
- **Success:** `200`
- **What it does:** Read-only.
- **Next (docs):** NEXT (061): PATCH  061 · Update bridge mapping

**Request**

**Query**

- `page` = `1`
- `page_size` = `50`
- `app_number` = `2`

**Response**

_See FastAPI `/docs`._

**Next in list:** `061` `PATCH` 061 · Update bridge mapping

---

### 061 · Update bridge mapping

- **HTTP:** `PATCH /recons/{{recon_id}}/bridge-mappings/{{bridge_mapping_id}}`
- **Auth:** Bearer `{{access_token}}`
- **Success:** `200`
- **What it does:** Patches the first listed mapping (bridge_mapping_id).
- **Next (docs):** NEXT (062): GET  062 · Export bridge mappings App 1

**Request**

**JSON body**

```json
{
  "flip_sign": false,
  "je_comment": "updated from Postman"
}
```

**Response**

```json
{"id":"uuid","recon_id":"uuid","app_number":1,"app_name":"App1","app_type":"App1","dimension_name":"ENTITY","source_member":"1","bridge_member":"1","is_kickout":false,"flip_sign":false,"dim_comment":null,"bridge_comment":null,"je_comment":null,"is_invalid":false,"created_at":"ISO-8601","updated_at":"ISO-8601"}
```

**Next in list:** `062` `GET` 062 · Export bridge mappings App 1

---

### 062 · Export bridge mappings App 1

- **HTTP:** `GET /recons/{{recon_id}}/bridge-mappings/export?app_number=1`
- **Auth:** Bearer `{{access_token}}`
- **Success:** `200`
- **What it does:** Downloads App 1 maps.
- **Next (docs):** NEXT (063): GET  063 · Export bridge mappings (all apps)

**Request**

**Query**

- `app_number` = `1`

**Response**

_See FastAPI `/docs`._

**Next in list:** `063` `GET` 063 · Export bridge mappings (all apps)

---

### 063 · Export bridge mappings (all apps)

- **HTTP:** `GET /recons/{{recon_id}}/bridge-mappings/export`
- **Auth:** Bearer `{{access_token}}`
- **Success:** `200`
- **What it does:** Downloads every app.
- **Next (docs):** NEXT (064): POST  064 · Start bridge run

**Request**

_No body._

**Response**

`text/csv` download (`Content-Disposition: attachment`). Not JSON. Dimension, Source Member, Flip Sign, Bridge Member, comments.

**Next in list:** `064` `POST` 064 · Start bridge run

---

### 064 · Start bridge run

- **HTTP:** `POST /recons/{{recon_id}}/bridge-runs`
- **Auth:** Bearer `{{access_token}}`
- **Success:** `201`
- **What it does:** Required. Saves bridge_run_id. Local env runs in-process.
- **Next (docs):** NEXT (065): GET  065 · List bridge runs

**Request**

_No body._

**Response**

```json
{"id":"uuid","recon_id":"uuid","status":"pending|processing|completed|failed","total_rows":80,"processed_rows":80,"kickout_count":0,"error_message":null,"created_by":"username","created_at":"ISO-8601","started_at":"ISO-8601|null","completed_at":"ISO-8601|null"}
```

**Next in list:** `065` `GET` 065 · List bridge runs

---

### 065 · List bridge runs

- **HTTP:** `GET /recons/{{recon_id}}/bridge-runs?page=1&page_size=25`
- **Auth:** Bearer `{{access_token}}`
- **Success:** `200`
- **What it does:** History of bridge jobs.
- **Next (docs):** NEXT (066): GET  066 · Get bridge run

**Request**

**Query**

- `page` = `1`
- `page_size` = `25`

**Response**

_See FastAPI `/docs`._

**Next in list:** `066` `GET` 066 · Get bridge run

---

### 066 · Get bridge run

- **HTTP:** `GET /recons/{{recon_id}}/bridge-runs/{{bridge_run_id}}`
- **Auth:** Bearer `{{access_token}}`
- **Success:** `200`
- **Note:** WAIT: Send again until status is completed. Then continue.
- **Next (docs):** NEXT (067): GET  067 · List kickouts

**Request**

_No body._

**Response**

```json
{"id":"uuid","recon_id":"uuid","status":"pending|processing|completed|failed","total_rows":80,"processed_rows":80,"kickout_count":0,"error_message":null,"created_by":"username","created_at":"ISO-8601","started_at":"ISO-8601|null","completed_at":"ISO-8601|null"}
```

**Next in list:** `067` `GET` 067 · List kickouts

---

### 067 · List kickouts

- **HTTP:** `GET /recons/{{recon_id}}/bridge-kickouts?page=1&page_size=50`
- **Auth:** Bearer `{{access_token}}`
- **Success:** `200`
- **What it does:** Saves first kickout into kickout_app / kickout_dim / kickout_source for Resolve.
- **Next (docs):** NEXT (068): GET  068 · List kickouts App 1

**Request**

**Query**

- `page` = `1`
- `page_size` = `50`

**Query (off)**

- `app_number` = `1`

**Response**

_See FastAPI `/docs`._

**Next in list:** `068` `GET` 068 · List kickouts App 1

---

### 068 · List kickouts App 1

- **HTTP:** `GET /recons/{{recon_id}}/bridge-kickouts?page=1&page_size=50&app_number=1`
- **Auth:** Bearer `{{access_token}}`
- **Success:** `200`
- **What it does:** Filtered to App 1.
- **Next (docs):** NEXT (069): GET  069 · Export kickouts

**Request**

**Query**

- `page` = `1`
- `page_size` = `50`
- `app_number` = `1`

**Response**

_See FastAPI `/docs`._

**Next in list:** `069` `GET` 069 · Export kickouts

---

### 069 · Export kickouts

- **HTTP:** `GET /recons/{{recon_id}}/bridge-kickouts/export`
- **Auth:** Bearer `{{access_token}}`
- **Success:** `200`
- **What it does:** Downloads all kickouts.
- **Next (docs):** NEXT (070): GET  070 · Export kickouts App 1

**Request**

_No body._

**Response**

`text/csv` download (`Content-Disposition: attachment`). Not JSON. `app_name`, `Common_dimension_name`, `Source_member`, `Bridge_member`.

**Next in list:** `070` `GET` 070 · Export kickouts App 1

---

### 070 · Export kickouts App 1

- **HTTP:** `GET /recons/{{recon_id}}/bridge-kickouts/export?app_number=1`
- **Auth:** Bearer `{{access_token}}`
- **Success:** `200`
- **What it does:** Downloads App 1 kickouts.
- **Next (docs):** NEXT (071): POST  071 · Resolve one kickout

**Request**

**Query**

- `app_number` = `1`

**Response**

_See FastAPI `/docs`._

**Next in list:** `071` `POST` 071 · Resolve one kickout

---

### 071 · Resolve one kickout

- **HTTP:** `POST /recons/{{recon_id}}/bridge-kickouts`
- **Auth:** Bearer `{{access_token}}`
- **Success:** `200`
- **What it does:** Identity-maps the first kickout from List kickouts. Empty list is ok to skip.
- **Next (docs):** NEXT (072): POST  072 · Default remaining kickouts App 1

**Request**

**JSON body**

```json
{
  "app_number": {{kickout_app}},
  "dimension_name": "{{kickout_dim}}",
  "source_member": "{{kickout_source}}",
  "bridge_member": "{{kickout_source}}",
  "flip_sign": false
}
```

**Response**

```json
{"id":"uuid","recon_id":"uuid","app_number":1,"app_name":"App1","app_type":"App1","dimension_name":"ENTITY","source_member":"1","bridge_member":"1","is_kickout":false,"flip_sign":false,"dim_comment":null,"bridge_comment":null,"je_comment":null,"is_invalid":false,"created_at":"ISO-8601","updated_at":"ISO-8601"}
```

**Next in list:** `072` `POST` 072 · Default remaining kickouts App 1

---

### 072 · Default remaining kickouts App 1

- **HTTP:** `POST /recons/{{recon_id}}/bridge-kickouts/default?app_number=1`
- **Auth:** Bearer `{{access_token}}`
- **Success:** `200`
- **What it does:** Identity-maps leftover App 1 kickouts without wiping real maps.
- **Next (docs):** NEXT (073): POST  073 · Default remaining kickouts App 2

**Request**

**Query**

- `app_number` = `1`

**Response**

_See FastAPI `/docs`._

**Next in list:** `073` `POST` 073 · Default remaining kickouts App 2

---

### 073 · Default remaining kickouts App 2

- **HTTP:** `POST /recons/{{recon_id}}/bridge-kickouts/default?app_number=2`
- **Auth:** Bearer `{{access_token}}`
- **Success:** `200`
- **What it does:** Same for App 2.
- **Next (docs):** NEXT (074): GET  074 · List bridged data App 1

**Request**

**Query**

- `app_number` = `2`

**Response**

_See FastAPI `/docs`._

**Next in list:** `074` `GET` 074 · List bridged data App 1

---

### 074 · List bridged data App 1

- **HTTP:** `GET /recons/{{recon_id}}/bridge-data?page=1&page_size=25&app_number=1&kickout=false`
- **Auth:** Bearer `{{access_token}}`
- **Success:** `200`
- **What it does:** Resolved members, kickout=false.
- **Next (docs):** NEXT (075): GET  075 · List bridged data App 2

**Request**

**Query**

- `page` = `1`
- `page_size` = `25`
- `app_number` = `1`
- `kickout` = `false`

**Response**

_See FastAPI `/docs`._

**Next in list:** `075` `GET` 075 · List bridged data App 2

---

### 075 · List bridged data App 2

- **HTTP:** `GET /recons/{{recon_id}}/bridge-data?page=1&page_size=25&app_number=2`
- **Auth:** Bearer `{{access_token}}`
- **Success:** `200`
- **What it does:** Resolved members for App 2.
- **Next (docs):** NEXT (076): GET  076 · List bridged kickout rows

**Request**

**Query**

- `page` = `1`
- `page_size` = `25`
- `app_number` = `2`

**Response**

_See FastAPI `/docs`._

**Next in list:** `076` `GET` 076 · List bridged kickout rows

---

### 076 · List bridged kickout rows

- **HTTP:** `GET /recons/{{recon_id}}/bridge-data?page=1&page_size=25&kickout=true`
- **Auth:** Bearer `{{access_token}}`
- **Success:** `200`
- **What it does:** kickout=true rows still excluded from report.
- **Next (docs):** NEXT (077): DELETE  077 · Delete extra bridge mapping

**Request**

**Query**

- `page` = `1`
- `page_size` = `25`
- `kickout` = `true`

**Response**

_See FastAPI `/docs`._

**Next in list:** `077` `DELETE` 077 · Delete extra bridge mapping

---

### 077 · Delete extra bridge mapping

- **HTTP:** `DELETE /recons/{{recon_id}}/bridge-mappings/{{extra_bridge_mapping_id}}`
- **Auth:** Bearer `{{access_token}}`
- **Success:** `204`
- **What it does:** Deletes POSTMAN_EXTRA only (extra_bridge_mapping_id).
- **Next (docs):** NEXT (078): GET  078 · Possible combinations App 1 ENTITY
Then open folder: 7. Transformation

**Request**

_No body._

**Response**

Empty body. HTTP **204 No Content**.

**Next in list:** `078` `GET` 078 · Possible combinations App 1 ENTITY

---

## 7. Transformation

### 078 · Possible combinations App 1 ENTITY

- **HTTP:** `GET /recons/{{recon_id}}/sync-mappings/possible-combinations?app_number=1&dimension_names=ENTITY`
- **Auth:** Bearer `{{access_token}}`
- **Success:** `200`
- **What it does:** Distinct ENTITY values for concat mapping.
- **Next (docs):** NEXT (079): GET  079 · Possible combinations App 1 ENTITY+PERIOD

**Request**

**Query**

- `app_number` = `1`
- `dimension_names` = `ENTITY`

**Response**

_See FastAPI `/docs`._

**Next in list:** `079` `GET` 079 · Possible combinations App 1 ENTITY+PERIOD

---

### 079 · Possible combinations App 1 ENTITY+PERIOD

- **HTTP:** `GET /recons/{{recon_id}}/sync-mappings/possible-combinations?app_number=1&dimension_names=ENTITY&dimension_names=PERIOD`
- **Auth:** Bearer `{{access_token}}`
- **Success:** `200`
- **What it does:** Zipped ENTITY+PERIOD combos, not a cartesian product.
- **Next (docs):** NEXT (080): POST  080 · Apply all members App 1

**Request**

**Query**

- `app_number` = `1`
- `dimension_names` = `ENTITY`
- `dimension_names` = `PERIOD`

**Response**

_See FastAPI `/docs`._

**Next in list:** `080` `POST` 080 · Apply all members App 1

---

### 080 · Apply all members App 1

- **HTTP:** `POST /recons/{{recon_id}}/sync-mappings/apply-all`
- **Auth:** Bearer `{{access_token}}`
- **Success:** `200`
- **What it does:** Required. Identity concat mappings for App 1 ENTITY.
- **Next (docs):** NEXT (081): POST  081 · Apply all members App 2

**Request**

**JSON body**

```json
{
  "app_number": 1,
  "dimension_names": [
    "ENTITY"
  ],
  "concat_delimiter": "-"
}
```

**Response**

```json
{"created":12,"skipped":0}
```

**Next in list:** `081` `POST` 081 · Apply all members App 2

---

### 081 · Apply all members App 2

- **HTTP:** `POST /recons/{{recon_id}}/sync-mappings/apply-all`
- **Auth:** Bearer `{{access_token}}`
- **Success:** `200`
- **What it does:** Required. Same for App 2.
- **Next (docs):** NEXT (082): POST  082 · Create sync mapping (extra)

**Request**

**JSON body**

```json
{
  "app_number": 2,
  "dimension_names": [
    "ENTITY"
  ],
  "concat_delimiter": "-"
}
```

**Response**

```json
{"created":12,"skipped":0}
```

**Next in list:** `082` `POST` 082 · Create sync mapping (extra)

---

### 082 · Create sync mapping (extra)

- **HTTP:** `POST /recons/{{recon_id}}/sync-mappings`
- **Auth:** Bearer `{{access_token}}`
- **Success:** `201`
- **What it does:** Creates POSTMAN_SYNC. 409 is ok if it already exists. Saves extra_sync_mapping_id.
- **Next (docs):** NEXT (083): GET  083 · List sync mappings App 1

**Request**

**JSON body**

```json
{
  "app_number": 1,
  "dimension_names": [
    "ENTITY"
  ],
  "concat_delimiter": "-",
  "source_sync": "POSTMAN_SYNC",
  "target_sync": "POSTMAN_SYNC",
  "flip_sign": false
}
```

**Response**

```json
{"id":"uuid","recon_id":"uuid","app_number":1,"dimension_names":["ENTITY"],"concat_delimiter":"-","source_sync":"1","target_sync":"1","flip_sign":false,"created_at":"ISO-8601","updated_at":"ISO-8601"}
```

**Next in list:** `083` `GET` 083 · List sync mappings App 1

---

### 083 · List sync mappings App 1

- **HTTP:** `GET /recons/{{recon_id}}/sync-mappings?app_number=1`
- **Auth:** Bearer `{{access_token}}`
- **Success:** `200`
- **What it does:** Saves sync_mapping_id from the first row for PATCH.
- **Next (docs):** NEXT (084): GET  084 · List sync mappings (all apps)

**Request**

**Query**

- `app_number` = `1`

**Response**

_See FastAPI `/docs`._

**Next in list:** `084` `GET` 084 · List sync mappings (all apps)

---

### 084 · List sync mappings (all apps)

- **HTTP:** `GET /recons/{{recon_id}}/sync-mappings`
- **Auth:** Bearer `{{access_token}}`
- **Success:** `200`
- **What it does:** Read-only.
- **Next (docs):** NEXT (085): PATCH  085 · Update sync mapping

**Request**

_No body._

**Response**

JSON array of the object below.

```json
{"id":"uuid","recon_id":"uuid","app_number":1,"dimension_names":["ENTITY"],"concat_delimiter":"-","source_sync":"1","target_sync":"1","flip_sign":false,"created_at":"ISO-8601","updated_at":"ISO-8601"}
```

**Next in list:** `085` `PATCH` 085 · Update sync mapping

---

### 085 · Update sync mapping

- **HTTP:** `PATCH /recons/{{recon_id}}/sync-mappings/{{sync_mapping_id}}`
- **Auth:** Bearer `{{access_token}}`
- **Success:** `200`
- **What it does:** Patches the first listed mapping.
- **Next (docs):** NEXT (086): GET  086 · Export sync mappings CSV

**Request**

**JSON body**

```json
{
  "flip_sign": false
}
```

**Response**

```json
{"id":"uuid","recon_id":"uuid","app_number":1,"dimension_names":["ENTITY"],"concat_delimiter":"-","source_sync":"1","target_sync":"1","flip_sign":false,"created_at":"ISO-8601","updated_at":"ISO-8601"}
```

**Next in list:** `086` `GET` 086 · Export sync mappings CSV

---

### 086 · Export sync mappings CSV

- **HTTP:** `GET /recons/{{recon_id}}/sync-mappings/export`
- **Auth:** Bearer `{{access_token}}`
- **Success:** `200`
- **What it does:** Download this if you want to test Import next.
- **Next (docs):** NEXT (087): GET  087 · Export sync mappings CSV App 1

**Request**

_No body._

**Response**

`text/csv` download (`Content-Disposition: attachment`). Not JSON. `app_number`, `dimension_names` (pipe), `concat_delimiter`, `source_sync`, `target_sync`, `flip_sign`.

**Next in list:** `087` `GET` 087 · Export sync mappings CSV App 1

---

### 087 · Export sync mappings CSV App 1

- **HTTP:** `GET /recons/{{recon_id}}/sync-mappings/export?app_number=1`
- **Auth:** Bearer `{{access_token}}`
- **Success:** `200`
- **What it does:** App 1 only.
- **Next (docs):** NEXT (089): POST  089 · Run transformation App 1
- **Note:** Skip 088 Import sync CSV until you attach the file you exported.

**Request**

**Query**

- `app_number` = `1`

**Response**

_See FastAPI `/docs`._

**Next in list:** `088` `POST` 088 · Import sync mappings CSV

---

### 088 · Import sync mappings CSV

- **HTTP:** `POST /recons/{{recon_id}}/sync-mappings/import`
- **Auth:** Bearer `{{access_token}}`
- **Success:** `200`
- **What it does:** SKIP in Runner until you attach the CSV you just exported (Body → file).
- **Next (docs):** NEXT (089): POST  089 · Run transformation App 1
- **Note:** Skip until you attach an exported CSV. After Export sync mappings go to Run transformation App 1.

**Request**

**multipart/form-data**

- `file` *(file)* → `(select in Postman)`

**Response**

JSON array of the object below.

```json
{"id":"uuid","recon_id":"uuid","app_number":1,"dimension_names":["ENTITY"],"concat_delimiter":"-","source_sync":"1","target_sync":"1","flip_sign":false,"created_at":"ISO-8601","updated_at":"ISO-8601"}
```

**Next in list:** `089` `POST` 089 · Run transformation App 1

---

### 089 · Run transformation App 1

- **HTTP:** `POST /recons/{{recon_id}}/sync-data/run?page=1&page_size=25&app_number=1`
- **Auth:** Bearer `{{access_token}}`
- **Success:** `200`
- **What it does:** Computes transformed rows for App 1.
- **Next (docs):** NEXT (090): POST  090 · Run transformation App 2

**Request**

**Query**

- `page` = `1`
- `page_size` = `25`
- `app_number` = `1`

**Response**

_See FastAPI `/docs`._

**Next in list:** `090` `POST` 090 · Run transformation App 2

---

### 090 · Run transformation App 2

- **HTTP:** `POST /recons/{{recon_id}}/sync-data/run?page=1&page_size=25&app_number=2`
- **Auth:** Bearer `{{access_token}}`
- **Success:** `200`
- **What it does:** Computes transformed rows for App 2.
- **Next (docs):** NEXT (091): POST  091 · Run transformation (all apps)

**Request**

**Query**

- `page` = `1`
- `page_size` = `25`
- `app_number` = `2`

**Response**

_See FastAPI `/docs`._

**Next in list:** `091` `POST` 091 · Run transformation (all apps)

---

### 091 · Run transformation (all apps)

- **HTTP:** `POST /recons/{{recon_id}}/sync-data/run?page=1&page_size=25`
- **Auth:** Bearer `{{access_token}}`
- **Success:** `200`
- **What it does:** Both apps, one page.
- **Next (docs):** NEXT (092): GET  092 · Export transformed data CSV

**Request**

**Query**

- `page` = `1`
- `page_size` = `25`

**Response**

_See FastAPI `/docs`._

**Next in list:** `092` `GET` 092 · Export transformed data CSV

---

### 092 · Export transformed data CSV

- **HTTP:** `GET /recons/{{recon_id}}/sync-data/export`
- **Auth:** Bearer `{{access_token}}`
- **Success:** `200`
- **What it does:** Downloads transformed data.
- **Next (docs):** NEXT (093): GET  093 · Export transformed data CSV App 1

**Request**

_No body._

**Response**

`text/csv` download (`Content-Disposition: attachment`). Not JSON. `app_number`, `app_name`, `row_number`, dims, `amount`, `flip_sign`.

**Next in list:** `093` `GET` 093 · Export transformed data CSV App 1

---

### 093 · Export transformed data CSV App 1

- **HTTP:** `GET /recons/{{recon_id}}/sync-data/export?app_number=1`
- **Auth:** Bearer `{{access_token}}`
- **Success:** `200`
- **What it does:** App 1 only.
- **Next (docs):** NEXT (094): DELETE  094 · Delete extra sync mapping

**Request**

**Query**

- `app_number` = `1`

**Response**

_See FastAPI `/docs`._

**Next in list:** `094` `DELETE` 094 · Delete extra sync mapping

---

### 094 · Delete extra sync mapping

- **HTTP:** `DELETE /recons/{{recon_id}}/sync-mappings/{{extra_sync_mapping_id}}`
- **Auth:** Bearer `{{access_token}}`
- **Success:** `204`
- **What it does:** Deletes POSTMAN_SYNC only (extra_sync_mapping_id).
- **Next (docs):** NEXT (095): GET  095 · Last refresh
Then open folder: 8. Run Report

**Request**

_No body._

**Response**

Empty body. HTTP **204 No Content**.

**Next in list:** `095` `GET` 095 · Last refresh

---

## 8. Run Report

### 095 · Last refresh

- **HTTP:** `GET /recons/{{recon_id}}/report/last-refresh`
- **Auth:** Bearer `{{access_token}}`
- **Success:** `200`
- **What it does:** Latest completed import time per app. Should include App 1 and App 2.
- **Next (docs):** NEXT (096): POST  096 · Run report

**Request**

_No body._

**Response**

```json
[{"app_number":1,"last_refresh":"ISO-8601|null"},{"app_number":2,"last_refresh":"ISO-8601|null"}]
```

**Next in list:** `096` `POST` 096 · Run report

---

### 096 · Run report

- **HTTP:** `POST /recons/{{recon_id}}/report/run?baseline_app=1&comparison_app=2&variance_threshold=0`
- **Auth:** Bearer `{{access_token}}`
- **Success:** `200`
- **What it does:** Required. Baseline App 1 vs comparison App 2.
- **Next (docs):** NEXT (097): GET  097 · Export report CSV

**Request**

**Query**

- `baseline_app` = `1`
- `comparison_app` = `2`
- `variance_threshold` = `0`

**Response**

_See FastAPI `/docs`._

**Next in list:** `097` `GET` 097 · Export report CSV

---

### 097 · Export report CSV

- **HTTP:** `GET /recons/{{recon_id}}/report/export?baseline_app=1&comparison_app=2&variance_threshold=0`
- **Auth:** Bearer `{{access_token}}`
- **Success:** `200`
- **What it does:** Downloads the variance table.
- **Next (docs):** NEXT (098): GET  098 · Drill-down ENTITY=1

**Request**

**Query**

- `baseline_app` = `1`
- `comparison_app` = `2`
- `variance_threshold` = `0`

**Response**

_See FastAPI `/docs`._

**Next in list:** `098` `GET` 098 · Drill-down ENTITY=1

---

### 098 · Drill-down ENTITY=1

- **HTTP:** `GET /recons/{{recon_id}}/report/drill-down?dimension_names=ENTITY&values=1&baseline_app=1&comparison_app=2&variance_threshold=0`
- **Auth:** Bearer `{{access_token}}`
- **Success:** `200`
- **What it does:** Rows whose ENTITY is 1.
- **Next (docs):** NEXT (099): GET  099 · Filter members ENTITY App 1

**Request**

**Query**

- `dimension_names` = `ENTITY`
- `values` = `1`
- `baseline_app` = `1`
- `comparison_app` = `2`
- `variance_threshold` = `0`

**Response**

_See FastAPI `/docs`._

**Next in list:** `099` `GET` 099 · Filter members ENTITY App 1

---

### 099 · Filter members ENTITY App 1

- **HTTP:** `GET /recons/{{recon_id}}/report/filters/members?dimension_name=ENTITY&app_number=1`
- **Auth:** Bearer `{{access_token}}`
- **Success:** `200`
- **What it does:** Distinct ENTITY members for the filter dropdown.
- **Next (docs):** NEXT (100): GET  100 · Filter members ENTITY (all apps)

**Request**

**Query**

- `dimension_name` = `ENTITY`
- `app_number` = `1`

**Response**

_See FastAPI `/docs`._

**Next in list:** `100` `GET` 100 · Filter members ENTITY (all apps)

---

### 100 · Filter members ENTITY (all apps)

- **HTTP:** `GET /recons/{{recon_id}}/report/filters/members?dimension_name=ENTITY`
- **Auth:** Bearer `{{access_token}}`
- **Success:** `200`
- **What it does:** Same across apps.
- **Next (docs):** NEXT (101): POST  101 · Create report filter

**Request**

**Query**

- `dimension_name` = `ENTITY`

**Response**

_See FastAPI `/docs`._

**Next in list:** `101` `POST` 101 · Create report filter

---

### 101 · Create report filter

- **HTTP:** `POST /recons/{{recon_id}}/report/filters`
- **Auth:** Bearer `{{access_token}}`
- **Success:** `201`
- **What it does:** Saves filter_id. Criteria ENTITY=['1'].
- **Next (docs):** NEXT (102): GET  102 · List report filters

**Request**

**JSON body**

```json
{
  "name": "Entity 1",
  "criteria": {
    "ENTITY": [
      "1"
    ]
  }
}
```

**Response**

```json
{"id":"uuid","recon_id":"uuid","name":"Entity 1","criteria":{"ENTITY":["1"]},"created_at":"ISO-8601","updated_at":"ISO-8601"}
```

**Next in list:** `102` `GET` 102 · List report filters

---

### 102 · List report filters

- **HTTP:** `GET /recons/{{recon_id}}/report/filters`
- **Auth:** Bearer `{{access_token}}`
- **Success:** `200`
- **What it does:** Should include Entity 1.
- **Next (docs):** NEXT (103): PATCH  103 · Update report filter

**Request**

_No body._

**Response**

JSON array of the object below.

```json
{"id":"uuid","recon_id":"uuid","name":"Entity 1","criteria":{"ENTITY":["1"]},"created_at":"ISO-8601","updated_at":"ISO-8601"}
```

**Next in list:** `103` `PATCH` 103 · Update report filter

---

### 103 · Update report filter

- **HTTP:** `PATCH /recons/{{recon_id}}/report/filters/{{filter_id}}`
- **Auth:** Bearer `{{access_token}}`
- **Success:** `200`
- **What it does:** Widens criteria to ENTITY 1 and 2.
- **Next (docs):** NEXT (104): POST  104 · Run report with filter

**Request**

**JSON body**

```json
{
  "criteria": {
    "ENTITY": [
      "1",
      "2"
    ]
  }
}
```

**Response**

```json
{"id":"uuid","recon_id":"uuid","name":"Entity 1","criteria":{"ENTITY":["1"]},"created_at":"ISO-8601","updated_at":"ISO-8601"}
```

**Next in list:** `104` `POST` 104 · Run report with filter

---

### 104 · Run report with filter

- **HTTP:** `POST /recons/{{recon_id}}/report/run?baseline_app=1&comparison_app=2&variance_threshold=0&filter_id={{filter_id}}`
- **Auth:** Bearer `{{access_token}}`
- **Success:** `200`
- **What it does:** Same run, filtered by filter_id.
- **Next (docs):** NEXT (105): GET  105 · Export report CSV with filter

**Request**

**Query**

- `baseline_app` = `1`
- `comparison_app` = `2`
- `variance_threshold` = `0`
- `filter_id` = `{{filter_id}}`

**Response**

_See FastAPI `/docs`._

**Next in list:** `105` `GET` 105 · Export report CSV with filter

---

### 105 · Export report CSV with filter

- **HTTP:** `GET /recons/{{recon_id}}/report/export?baseline_app=1&comparison_app=2&variance_threshold=0&filter_id={{filter_id}}`
- **Auth:** Bearer `{{access_token}}`
- **Success:** `200`
- **What it does:** Filtered CSV.
- **Next (docs):** NEXT (106): DELETE  106 · Delete report filter

**Request**

**Query**

- `baseline_app` = `1`
- `comparison_app` = `2`
- `variance_threshold` = `0`
- `filter_id` = `{{filter_id}}`

**Response**

_See FastAPI `/docs`._

**Next in list:** `106` `DELETE` 106 · Delete report filter

---

### 106 · Delete report filter

- **HTTP:** `DELETE /recons/{{recon_id}}/report/filters/{{filter_id}}`
- **Auth:** Bearer `{{access_token}}`
- **Success:** `204`
- **What it does:** Removes the filter you created.
- **Next (docs):** NEXT (107): GET  107 · List sign-offs

**Request**

_No body._

**Response**

Empty body. HTTP **204 No Content**.

**Next in list:** `107` `GET` 107 · List sign-offs

---

### 107 · List sign-offs

- **HTTP:** `GET /recons/{{recon_id}}/report/signoff`
- **Auth:** Bearer `{{access_token}}`
- **Success:** `200`
- **What it does:** Current sign-off flags.
- **Next (docs):** NEXT (108): POST  108 · Sign off apps

**Request**

_No body._

**Response**

```json
[{"app_number":1,"signed_off":true,"signed_off_by_id":"uuid","signed_off_at":"ISO-8601"}]
```

**Next in list:** `108` `POST` 108 · Sign off apps

---

### 108 · Sign off apps

- **HTTP:** `POST /recons/{{recon_id}}/report/signoff`
- **Auth:** Bearer `{{access_token}}`
- **Success:** `200`
- **What it does:** Locks App 1 and 2. Bridge mapping edits will 409 while signed off.
- **Next (docs):** NEXT (109): POST  109 · Clear sign-off

**Request**

**JSON body**

```json
{
  "app_numbers": [
    1,
    2
  ],
  "signed_off": true
}
```

**Response**

```json
[{"app_number":1,"signed_off":true,"signed_off_by_id":"uuid","signed_off_at":"ISO-8601"}]
```

**Next in list:** `109` `POST` 109 · Clear sign-off

---

### 109 · Clear sign-off

- **HTTP:** `POST /recons/{{recon_id}}/report/signoff`
- **Auth:** Bearer `{{access_token}}`
- **Success:** `200`
- **What it does:** Unlocks apps so later copy/cleanup can run.
- **Next (docs):** NEXT (110): POST  110 · Copy recon (Save As)
Then open folder: 9. Copy / archive / unlink group

**Request**

**JSON body**

```json
{
  "app_numbers": [
    1,
    2
  ],
  "signed_off": false
}
```

**Response**

```json
[{"app_number":1,"signed_off":true,"signed_off_by_id":"uuid","signed_off_at":"ISO-8601"}]
```

**Next in list:** `110` `POST` 110 · Copy recon (Save As)

---

## 9. Copy / archive / unlink group

### 110 · Copy recon (Save As)

- **HTTP:** `POST /recons/{{recon_id}}/copy`
- **Auth:** Bearer `{{access_token}}`
- **Success:** `201`
- **What it does:** Required. Clones config (not import rows). Saves copy_recon_id. Needs group_id.
- **Next (docs):** NEXT (111): GET  111 · Get copied recon

**Request**

**JSON body**

```json
{
  "name": "{{copy_recon_name}}",
  "group_id": "{{group_id}}"
}
```

**Response**

```json
{"id":"uuid","name":"Postman_Mock_Set1_…","description":"string|null","group_name":"string|null","owner":"username","status":"string","archived":false,"last_modified":"ISO-8601"}
```

**Next in list:** `111` `GET` 111 · Get copied recon

---

### 111 · Get copied recon

- **HTTP:** `GET /recons/{{copy_recon_id}}`
- **Auth:** Bearer `{{access_token}}`
- **Success:** `200`
- **What it does:** Confirms the clone.
- **Next (docs):** NEXT (112): PATCH  112 · Archive recon

**Request**

_No body._

**Response**

```json
{"id":"uuid","name":"Postman_Mock_Set1_…","description":"string|null","group_name":"string|null","owner":"username","status":"string","archived":false,"last_modified":"ISO-8601"}
```

**Next in list:** `112` `PATCH` 112 · Archive recon

---

### 112 · Archive recon

- **HTTP:** `PATCH /recons/{{recon_id}}`
- **Auth:** Bearer `{{access_token}}`
- **Success:** `200`
- **What it does:** Hides the original from Select.
- **Next (docs):** NEXT (113): PATCH  113 · Unarchive recon

**Request**

**JSON body**

```json
{
  "archived": true
}
```

**Response**

```json
{"id":"uuid","name":"Postman_Mock_Set1_…","description":"string|null","group_name":"string|null","owner":"username","status":"string","archived":false,"last_modified":"ISO-8601"}
```

**Next in list:** `113` `PATCH` 113 · Unarchive recon

---

### 113 · Unarchive recon

- **HTTP:** `PATCH /recons/{{recon_id}}`
- **Auth:** Bearer `{{access_token}}`
- **Success:** `200`
- **What it does:** Brings it back.
- **Next (docs):** NEXT (114): DELETE  114 · Unlink recon from group

**Request**

**JSON body**

```json
{
  "archived": false
}
```

**Response**

```json
{"id":"uuid","name":"Postman_Mock_Set1_…","description":"string|null","group_name":"string|null","owner":"username","status":"string","archived":false,"last_modified":"ISO-8601"}
```

**Next in list:** `114` `DELETE` 114 · Unlink recon from group

---

### 114 · Unlink recon from group

- **HTTP:** `DELETE /recons/{{recon_id}}/groups/{{group_id}}`
- **Auth:** Bearer `{{access_token}}`
- **Success:** `200`
- **What it does:** Inverse of create's link step.
- **Next (docs):** NEXT (115): POST  115 · Link recon to group (again)

**Request**

_No body._

**Response**

```json
{"id":"uuid","name":"Postman_Mock_Set1_…","description":"string|null","group_name":"string|null","owner":"username","status":"string","archived":false,"last_modified":"ISO-8601"}
```

**Next in list:** `115` `POST` 115 · Link recon to group (again)

---

### 115 · Link recon to group (again)

- **HTTP:** `POST /recons/{{recon_id}}/groups/{{group_id}}`
- **Auth:** Bearer `{{access_token}}`
- **Success:** `200`
- **What it does:** Puts the original back on the group.
- **Next (docs):** NEXT (116): GET  116 · List recon audit logs
Then open folder: 10. Recon audit

**Request**

_No body._

**Response**

```json
{"id":"uuid","name":"Postman_Mock_Set1_…","description":"string|null","group_name":"string|null","owner":"username","status":"string","archived":false,"last_modified":"ISO-8601"}
```

**Next in list:** `116` `GET` 116 · List recon audit logs

---

## 10. Recon audit

### 116 · List recon audit logs

- **HTTP:** `GET /recons/{{recon_id}}/audit-logs?page=1&page_size=50`
- **Auth:** Bearer `{{access_token}}`
- **Success:** `200`
- **What it does:** This recon's trail.
- **Next (docs):** NEXT (117): GET  117 · My audit logs

**Request**

**Query**

- `page` = `1`
- `page_size` = `50`

**Response**

_See FastAPI `/docs`._

**Next in list:** `117` `GET` 117 · My audit logs

---

### 117 · My audit logs

- **HTTP:** `GET /audit-logs/mine?page=1&page_size=50`
- **Auth:** Bearer `{{access_token}}`
- **Success:** `200`
- **What it does:** Your actions across recons.
- **Next (docs):** NEXT (118): GET  118 · All audit logs (superuser)

**Request**

**Query**

- `page` = `1`
- `page_size` = `50`

**Response**

_See FastAPI `/docs`._

**Next in list:** `118` `GET` 118 · All audit logs (superuser)

---

### 118 · All audit logs (superuser)

- **HTTP:** `GET /audit-logs?page=1&page_size=50`
- **Auth:** Bearer `{{access_token}}`
- **Success:** `200`
- **What it does:** Needs superuser. 403 otherwise — continue anyway.
- **Next (docs):** NEXT (119): GET  119 · Users audit logs

**Request**

**Query**

- `page` = `1`
- `page_size` = `50`

**Response**

_See FastAPI `/docs`._

**Next in list:** `119` `GET` 119 · Users audit logs

---

### 119 · Users audit logs

- **HTTP:** `GET /audit-logs/users?page=1&page_size=50`
- **Auth:** Bearer `{{access_token}}`
- **Success:** `200`
- **What it does:** Needs user:manage.
- **Next (docs):** NEXT (120): GET  120 · Export audit logs CSV

**Request**

**Query**

- `page` = `1`
- `page_size` = `50`

**Response**

_See FastAPI `/docs`._

**Next in list:** `120` `GET` 120 · Export audit logs CSV

---

### 120 · Export audit logs CSV

- **HTTP:** `GET /audit-logs/export`
- **Auth:** Bearer `{{access_token}}`
- **Success:** `200`
- **What it does:** Needs superuser.
- **Next (docs):** NEXT (121): POST  121 · Create workflow
Then open folder: 11. Scheduler (same recon, automated replay)

**Request**

_No body._

**Response**

`text/csv` download (`Content-Disposition: attachment`). Not JSON. `created_at`, `user`, `recon_name`, `action`, `entity_type`, `entity_id`, `detail`.

**Next in list:** `121` `POST` 121 · Create workflow

---

## 11. Scheduler (same recon, automated replay)

### 121 · Create workflow

- **HTTP:** `POST /workflows`
- **Auth:** Bearer `{{access_token}}`
- **Success:** `201`
- **What it does:** Required. Saves workflow_id. Paused cron so it will not auto-fire.
- **Next (docs):** NEXT (122): GET  122 · List workflows

**Request**

**JSON body**

```json
{
  "name": "{{workflow_name}}",
  "recon_id": "{{recon_id}}",
  "definition": {
    "steps": [
      {
        "key": "import_app_1",
        "type": "import_app_data",
        "ignore_kickout": false,
        "kickout_tolerance": 0,
        "app_number": 1,
        "app_name": "App1"
      },
      {
        "key": "import_app_2",
        "type": "import_app_data",
        "ignore_kickout": false,
        "kickout_tolerance": 0,
        "app_number": 2,
        "app_name": "App2"
      },
      {
        "key": "import_bridge_1",
        "type": "import_bridge_data",
        "ignore_kickout": false,
        "kickout_tolerance": 0,
        "app_number": 1,
        "app_name": "App1"
      },
      {
        "key": "import_bridge_2",
        "type": "import_bridge_data",
        "ignore_kickout": false,
        "kickout_tolerance": 0,
        "app_number": 2,
        "app_name": "App2"
      },
      {
        "key": "upload_dimensions",
        "type": "upload_dimensions",
        "ignore_kickout": false,
        "kickout_tolerance": 0,
        "app_name": ""
      },
      {
        "key": "run_bridge",
        "type": "run_bridge",
        "ignore_kickout": false,
        "kickout_tolerance": 0,
        "app_name": ""
      },
      {
        "key": "check_kickouts",
        "type": "check_kickouts",
        "ignore_kickout": false,
        "kickout_tolerance": 0,
        "app_name": ""
      },
      {
        "key": "run_transformation",
        "type": "run_transformation",
        "ignore_kickout": false,
        "kickout_tolerance": 0,
        "app_name": ""
      },
      {
        "key": "run_report",
        "type": "run_report",
        "ignore_kickout": false,
        "kickout_tolerance": 0,
        "app_name": ""
      }
    ],
    "on_success_emails": "",
    "on_failure_emails": ""
  },
  "schedule_cron": "0 2 * * *",
  "timezone": "UTC",
  "is_paused": true
}
```

**Response**

```json
{"id":"uuid","name":"…","recon_id":"uuid","recon_name":"…","definition":{"steps":[{"key":"import_app_1","type":"import_app_data","ignore_kickout":false,"kickout_tolerance":0,"app_number":1,"app_name":"App1"}],"on_success_emails":"","on_failure_emails":""},"schedule_cron":"0 2 * * *","timezone":"UTC","is_paused":true,"next_run_at":null,"created_by":"username","created_at":"ISO-8601","updated_at":"ISO-8601","latest_run":null}
```

**Next in list:** `122` `GET` 122 · List workflows

---

### 122 · List workflows

- **HTTP:** `GET /workflows?page=1&page_size=25`
- **Auth:** Bearer `{{access_token}}`
- **Success:** `200`
- **What it does:** Should include the new workflow.
- **Next (docs):** NEXT (123): GET  123 · Get workflow

**Request**

**Query**

- `page` = `1`
- `page_size` = `25`

**Response**

_See FastAPI `/docs`._

**Next in list:** `123` `GET` 123 · Get workflow

---

### 123 · Get workflow

- **HTTP:** `GET /workflows/{{workflow_id}}`
- **Auth:** Bearer `{{access_token}}`
- **Success:** `200`
- **What it does:** Shows definition and next_run_at (null while paused).
- **Next (docs):** NEXT (124): PATCH  124 · Update workflow (pause / cron)

**Request**

_No body._

**Response**

```json
{"id":"uuid","name":"…","recon_id":"uuid","recon_name":"…","definition":{"steps":[{"key":"import_app_1","type":"import_app_data","ignore_kickout":false,"kickout_tolerance":0,"app_number":1,"app_name":"App1"}],"on_success_emails":"","on_failure_emails":""},"schedule_cron":"0 2 * * *","timezone":"UTC","is_paused":true,"next_run_at":null,"created_by":"username","created_at":"ISO-8601","updated_at":"ISO-8601","latest_run":null}
```

**Next in list:** `124` `PATCH` 124 · Update workflow (pause / cron)

---

### 124 · Update workflow (pause / cron)

- **HTTP:** `PATCH /workflows/{{workflow_id}}`
- **Auth:** Bearer `{{access_token}}`
- **Success:** `200`
- **What it does:** Keeps paused, changes cron to 03:00 UTC.
- **Next (docs):** NEXT (125): POST  125 · Trigger workflow run

**Request**

**JSON body**

```json
{
  "is_paused": true,
  "schedule_cron": "0 3 * * *",
  "timezone": "UTC"
}
```

**Response**

```json
{"id":"uuid","name":"…","recon_id":"uuid","recon_name":"…","definition":{"steps":[{"key":"import_app_1","type":"import_app_data","ignore_kickout":false,"kickout_tolerance":0,"app_number":1,"app_name":"App1"}],"on_success_emails":"","on_failure_emails":""},"schedule_cron":"0 2 * * *","timezone":"UTC","is_paused":true,"next_run_at":null,"created_by":"username","created_at":"ISO-8601","updated_at":"ISO-8601","latest_run":null}
```

**Next in list:** `125` `POST` 125 · Trigger workflow run

---

### 125 · Trigger workflow run

- **HTTP:** `POST /workflows/{{workflow_id}}/runs`
- **Auth:** Bearer `{{access_token}}`
- **Success:** `201`
- **What it does:** Required. Saves workflow_run_id. Local env runs immediately.
- **Next (docs):** NEXT (126): GET  126 · List runs for workflow

**Request**

_No body._

**Response**

```json
{"id":"uuid","workflow_id":"uuid","workflow_name":"…","recon_id":"uuid","status":"queued|running|succeeded|failed|cancelled","trigger_kind":"manual|schedule","triggered_by":"username","current_step":"run_report","error_message":null,"created_at":"ISO-8601","started_at":"ISO-8601|null","completed_at":"ISO-8601|null","steps":[{"id":"uuid","step_key":"import_app_1","step_type":"import_app_data","status":"pending|running|succeeded|failed|skipped","attempt":1,"detail":{},"error_message":null,"started_at":null,"completed_at":null}]}
```

**Next in list:** `126` `GET` 126 · List runs for workflow

---

### 126 · List runs for workflow

- **HTTP:** `GET /workflows/{{workflow_id}}/runs?page=1&page_size=25`
- **Auth:** Bearer `{{access_token}}`
- **Success:** `200`
- **What it does:** This workflow's run history.
- **Next (docs):** NEXT (127): GET  127 · List all workflow runs

**Request**

**Query**

- `page` = `1`
- `page_size` = `25`

**Response**

_See FastAPI `/docs`._

**Next in list:** `127` `GET` 127 · List all workflow runs

---

### 127 · List all workflow runs

- **HTTP:** `GET /workflow-runs?page=1&page_size=25`
- **Auth:** Bearer `{{access_token}}`
- **Success:** `200`
- **What it does:** Every visible workflow's runs.
- **Next (docs):** NEXT (128): GET  128 · Get workflow run

**Request**

**Query**

- `page` = `1`
- `page_size` = `25`

**Response**

_See FastAPI `/docs`._

**Next in list:** `128` `GET` 128 · Get workflow run

---

### 128 · Get workflow run

- **HTTP:** `GET /workflow-runs/{{workflow_run_id}}`
- **Auth:** Bearer `{{access_token}}`
- **Success:** `200`
- **Note:** WAIT: Send again until status is succeeded or failed.
- **Note:** STOP here to keep the recon and workflow.
NEXT (130): DELETE  130 · Delete copy recon — only if you want Cleanup.
Skip 129 Delete workflow unless you want it gone.

**Request**

_No body._

**Response**

```json
{"id":"uuid","workflow_id":"uuid","workflow_name":"…","recon_id":"uuid","status":"queued|running|succeeded|failed|cancelled","trigger_kind":"manual|schedule","triggered_by":"username","current_step":"run_report","error_message":null,"created_at":"ISO-8601","started_at":"ISO-8601|null","completed_at":"ISO-8601|null","steps":[{"id":"uuid","step_key":"import_app_1","step_type":"import_app_data","status":"pending|running|succeeded|failed|skipped","attempt":1,"detail":{},"error_message":null,"started_at":null,"completed_at":null}]}
```

**Next in list:** `129` `DELETE` 129 · Delete workflow

---

### 129 · Delete workflow

- **HTTP:** `DELETE /workflows/{{workflow_id}}`
- **Auth:** Bearer `{{access_token}}`
- **Success:** `204`
- **What it does:** SKIP if you want the workflow to stay on the recon accordion. Soft-delete.
- **Next (docs):** NEXT (130): DELETE  130 · Delete copy recon
Then open folder: 12. Cleanup
- **Note:** Skip if you want to keep the workflow. After Get workflow run you are done unless you want Cleanup.

**Request**

_No body._

**Response**

Empty body. HTTP **204 No Content**.

**Next in list:** `130` `DELETE` 130 · Delete copy recon

---

## 12. Cleanup

### 130 · Delete copy recon

- **HTTP:** `DELETE /recons/{{copy_recon_id}}`
- **Auth:** Bearer `{{access_token}}`
- **Success:** `204`
- **What it does:** SKIP this whole Cleanup folder if you want the recon to stay on /recon-pipeline.
- **Next (docs):** NEXT (131): DELETE  131 · Delete recon

**Request**

_No body._

**Response**

Empty body. HTTP **204 No Content**.

**Next in list:** `131` `DELETE` 131 · Delete recon

---

### 131 · Delete recon

- **HTTP:** `DELETE /recons/{{recon_id}}`
- **Auth:** Bearer `{{access_token}}`
- **Success:** `204`
- **What it does:** Soft-deletes the working recon.
- **Next (docs):** NEXT (132): DELETE  132 · Delete group

**Request**

_No body._

**Response**

Empty body. HTTP **204 No Content**.

**Next in list:** `132` `DELETE` 132 · Delete group

---

### 132 · Delete group

- **HTTP:** `DELETE /groups/{{group_id}}`
- **Auth:** Bearer `{{access_token}}`
- **Success:** `204`
- **What it does:** Needs security:manage. Last step.
- **What it does:** Done. Collection finished.

**Request**

_No body._

**Response**

Empty body. HTTP **204 No Content**.

**Next in list:** collection finished.

---

## Backend routers included

| Module | Prefix |
|---|---|
| health | `/health` |
| auth | `/auth` |
| users | `/users/me` |
| groups | `/groups` |
| global_variables | `/global-variables` |
| recons | `/recons` |
| recon_apps | `/recons/{id}/apps` |
| dimensions | `/recons/{id}/dimensions` |
| imports | `/recons/{id}/imports` |
| bridge_mappings | `/recons/{id}/bridge-mappings` |
| bridge_kickouts | `/recons/{id}/bridge-kickouts` |
| bridge_runs | `/recons/{id}/bridge-runs` |
| bridge_data | `/recons/{id}/bridge-data` |
| sync_mappings | `/recons/{id}/sync-mappings` |
| sync_data | `/recons/{id}/sync-data` |
| report_data | `/recons/{id}/report` |
| report_filters | `/recons/{id}/report/filters` |
| audit_logs | `/audit-logs`, `/recons/{id}/audit-logs` |
| workflows | `/workflows`, `/workflow-runs` |

Not recon pipeline (omitted): LOBs, teams, roles, users CRUD, SSO, UI components, system logs, audit-mode.
