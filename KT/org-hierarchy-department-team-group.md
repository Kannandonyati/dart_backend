# KT — Department, Team, and Group

What each one is **for**, how they **connect**, and a **worked example** you can follow on Manage Recon Security. Companion: `docs/KT_PHASE3.md` (how the APIs were built), `apitest/28-org-links-checked.md` (what tests proved).

**Department** in the UI is **LOB** in the API (`/api/v1/lobs`). Same object.

---

## One-line each

| UI name | API | What it is | What it is not |
|---|---|---|---|
| **Department** | LOB | The **company org box** people sit in (Finance, Ops, Tax). Holds **teams**. Can have department admins/members. | Not a recon. Not what Create Recon lists. |
| **Team** | Team | A **desk / squad inside one department** (AP, Payroll under Finance). Always has **one** parent department. | Cannot exist without a department. Not the Create Recon dropdown. |
| **Group** | Group | The **recon access bag**. Users (and later recons) attach here. Created with **a name only**. | Not a child of a team. Departments/teams are **linked later**, they do not parent the group. |

Recons hang off **groups**, not off departments or teams. Org structure (dept/team) describes **who people are**. Groups describe **which recons those people may work**.

---

## Why three layers (old DART and this rebuild)

Large recon programs mix two questions:

1. **HR / org:** “Kannan is in Finance → AP.” That is Department + Team.
2. **Work / access:** “Kannan may run Bank-vs-GL recon.” That is **Group** + membership + recon↔group link.

If you only had departments, every Finance person would see every Finance recon. Groups let AP share one recon with Treasury without dumping the whole Finance tree onto that recon.

Old DART stored the same idea in `sp_master` / `f_validate_access`. Here it is tables + REST: `lobs`, `teams`, `groups`, `group_lobs`, `group_teams`, `memberships`, `recon_group_xref`.

---

## How they connect (rules)

```
Department "Finance"
    └── Team "AP"          (required: team.lob_id → Finance)
    └── Team "Payroll"

Group "Month-end cash recon"
    ├── linked departments: Finance          (optional, many)
    ├── linked teams:       AP               (optional, many)
    ├── members / admins:   users            (required for Create Recon dropdown)
    └── recons:             BANK_GL_SEP26    (after create)
```

| Connection | Cardinality | Required? | Used for |
|---|---|---|---|
| Team → Department | many teams → **one** department | **Yes** at team create | Org tree on Teams tab |
| Group ↔ Department | many-to-many | No | Group details → Departments tab; org tagging |
| Group ↔ Team | many-to-many | No | Group details → Teams tab |
| User ↔ Group (member or admin) | many-to-many | **Yes** if that user should **see the group in Create Recon** | `GET /api/v1/groups/mine` |
| Recon ↔ Group | many-to-many (UI usually one at create) | **Yes** in Create Recon dialog | Who can open the recon later |

Linking Finance to the group does **not** auto-add every Finance user to the group. Linking AP team does **not** either. You still add **people** (or they inherit via other access paths — see below).

**Create Recon dropdown** today: only groups where the **logged-in user** has a **group** membership (admin **or** member). Department/team links are **not** enough for that list.

`accessible_group_ids` (recon access later) **can** also include groups linked to a department or team the user belongs to. That is **not** what the Create Recon dropdown uses. Do not mix the two.

---

## Real-time example (Donyati-style month-end)

Company runs bank-to-GL recon. People:

| Person | Org | Should they create/run “BANK_GL”? |
|---|---|---|
| Priya | Finance / AP | Yes — she owns the recon |
| Arun | Finance / Payroll | No — different desk |
| Nisha | Treasury (another department) | Yes — she matches cash |

### 1. Org (Departments + Teams)

1. Create department **Finance**.
2. Create department **Treasury**.
3. Create team **AP** with department = Finance.
4. Create team **Payroll** with department = Finance.
5. Create team **Cash** with department = Treasury.

After this, Teams tab: AP and Payroll show **Created under Finance**. Payroll people are **not** in AP.

### 2. Group (the recon bag)

6. Create group **Month-end cash recon** (name only).
7. Group details → **Departments**: link **Finance** and **Treasury** (optional labels / later inheritance).
8. Group details → **Teams**: link **AP** and **Cash** — **not** Payroll.
9. Group details → **Members**: add **Priya** and **Nisha**. Do **not** add Arun.

Priya and Nisha now see **Month-end cash recon** in Create Recon. Arun does not, even though he is in Finance.

### 3. Create the recon

10. Priya opens Create Recon, picks group **Month-end cash recon**, name `BANK_GL_SEP26`.
11. API: `POST /recons` then `POST /recons/{id}/groups/{group_id}`.

The recon is tied to the **group**, not to the AP team row.

### 4. What each screen is doing in this story

| Screen | What you did | Why |
|---|---|---|
| Departments | Finance, Treasury | Org boxes |
| Teams | AP, Payroll under Finance; Cash under Treasury | Desks |
| Groups | Month-end cash recon + links + members | Who may work this recon family |
| Create Recon | Priya picks that group | Dropdown = her group memberships only |

---

## Step-by-step if the dropdown is empty

1. Group exists (Groups tab).
2. Open group info → **Members** or **Admins**.
3. Add **the same user you log in as** (creating the group does **not** add you).
4. Refresh Create Recon.

Department/team links will not fill the dropdown by themselves.

---

## API cheat sheet

| Intent | Call |
|---|---|
| Create department | `POST /api/v1/lobs` `{ "name": "Finance" }` |
| Create team under it | `POST /api/v1/teams` `{ "name": "AP", "lob_id": "<finance uuid>" }` |
| Create group | `POST /api/v1/groups` `{ "name": "Month-end cash recon" }` |
| Tag group with department | `POST /api/v1/groups/{g}/lobs/{lob}` → 204 |
| Tag group with team | `POST /api/v1/groups/{g}/teams/{team}` → 204 |
| Put user on group (dropdown) | `POST /api/v1/groups/{g}/members` `{ "user_id": "<uuid>" }` |
| Groups for Create Recon | `GET /api/v1/groups/mine` |
| Attach recon to group | `POST /api/v1/recons/{recon}/groups/{g}` |

Writes need `security:manage` (or superuser), except creating a recon as a normal user who already belongs to a group.

---

## Short memory aid

- **Department** = where the person sits in the company.  
- **Team** = which desk inside that department.  
- **Group** = which recon work they are allowed to touch.

Org links on a group are **labels / later access expansion**. **People on the group** are what Create Recon lists.
