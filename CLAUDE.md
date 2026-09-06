# weg CLI — Use These Commands for All Frappe Operations

NEVER manually activate the bench environment, write scripts that import frappe directly, or use `bench` commands.
NEVER modify files inside `.weg/` — it is managed infrastructure.

## Instead of...                              → Use...

| Anti-pattern                                 | weg command                         |
|----------------------------------------------|-------------------------------------|
| `bench --site X migrate`                       | `weg db migrate`                    |
| `bench --site X clear-cache`                   | `weg cache clear`                   |
| `bench build`                                  | `weg build`                         |
| `cd .weg && env/bin/python -c "import..."`   | `weg py "print(frappe.get_all(...))"` |
| `curl localhost:8000/api/resource/...`         | `weg api get DocType/name`           |
| `mysql -e "SELECT..."`                       | `weg api get DocType --filters '{}'` |

For full command reference: `weg --help` | For subcommand help: `weg <cmd> --help`

---

# Frappe App Development Guidelines

This project is a Frappe Framework application. Follow these guidelines strictly.

## Project Structure

```
myapp/
├── myapp/
│   ├── __init__.py
│   ├── hooks.py              # App hooks and overrides
│   ├── modules.txt           # List of modules
│   └── module_name/
│       └── doctype/
│           └── doctype_name/
│               ├── doctype_name.py      # Controller
│               ├── doctype_name.js      # Client script
│               └── doctype_name.json    # Schema
├── pyproject.toml
└── .pre-commit-config.yaml
```

## Critical Rules (ERRORS)

### 1. Multitenancy - NEVER use global variables with DB/cache calls

```python
# BAD - breaks multitenancy
CACHED_USERS = frappe.get_all("User")  # Global scope!

# GOOD - wrap in function
def get_users():
    return frappe.get_all("User")
```

### 2. Always commit changes in controller hooks

```python
# BAD - changes lost after hook completes
def on_submit(self):
    self.status = "Submitted"  # Not saved!

# GOOD - use db_set or save
def on_submit(self):
    self.db_set("status", "Submitted")
```

### 3. Never modify child tables while iterating

```python
# BAD - undefined behavior
for row in self.items:
    if row.qty == 0:
        self.remove(row)

# GOOD - collect then modify
to_remove = [row for row in self.items if row.qty == 0]
for row in to_remove:
    self.remove(row)
```

### 4. Use correct cache methods for multitenancy

```python
# BAD - not multitenant-safe
frappe.cache().set("key", value)

# GOOD - use set_value/get_value
frappe.cache().set_value("key", value)
```

### 5. Never reassign frappe local proxies

```python
# BAD - breaks proxying
frappe.db = some_other_db

# GOOD - use frappe.local
frappe.local.db = some_other_db
```

### 6. Use get_single_value for Single DocTypes

```python
# BAD - not type-safe
value = frappe.db.get_value("System Settings", "System Settings", "field")

# GOOD
value = frappe.db.get_single_value("System Settings", "field")
```

### 7. Specify room for realtime messages

```python
# BAD - broadcasts to ALL users on site
frappe.publish_realtime("event", data)

# GOOD - specify recipient
frappe.publish_realtime("event", data, user=frappe.session.user)
```

### 8. Valid controller hooks only

Valid hooks: `before_insert`, `after_insert`, `validate`, `before_save`, `on_update`, `before_submit`, `on_submit`, `before_cancel`, `on_cancel`, `on_trash`

### 9. Use keyword argument for orderby

```python
# BAD
query.orderby("creation", "desc")

# GOOD
query.orderby("creation", order=frappe.qb.desc)
```

### 10. No monkey patching - use hooks

```python
# BAD - patching at runtime
from frappe.core.doctype.user import user
user.User.some_method = my_method

# GOOD - use hooks.py doc_events
```

### 11. Never use eval() - use safe_eval()

```python
# BAD - code injection risk
result = eval(user_input)

# GOOD
from frappe.utils.safe_exec import safe_eval
result = safe_eval(user_input)
```

## Warnings

- Use `frappe.logger()` instead of `print()`
- Avoid `frappe.db.commit()` - let framework handle transactions
- Prefer list comprehensions over `map()/filter()`
- Remove `debug=True` statements

## Translation Rules

```python
# All user-facing text must be translated
frappe.throw(_("Document not found"))

# Format AFTER translate
_("User {0} not found").format(user)
```

## JavaScript Rules

- Never use `cur_frm` (deprecated) - use `frm`
- Create debounced functions once, not on each call
- Translate button text: `frm.add_custom_button(__('Process'), fn)`

## The Frappe Way

### Schema Changes - Edit JSON, Then Migrate

```bash
# BAD - direct SQL breaks migrations
mysql -e "ALTER TABLE tabUser ADD COLUMN custom_field VARCHAR(255)"

# GOOD - edit DocType JSON, then migrate
weg migrate
```

### Data Changes - Use Frappe API, Not Raw SQL

```bash
# BAD - bypasses permissions and hooks
mysql -e "UPDATE tabUser SET first_name='John' WHERE name='john@example.com'"

# GOOD - use weg api
weg api call frappe.client.set_value --doctype User --name john@example.com --fieldname first_name --value John

# GOOD - for bulk updates, use filters dict + values dict
weg py "frappe.db.set_value('User', {'user_type': 'Website User'}, {'enabled': 0})"
```

### Reading Data - Use Frappe API

```bash
# BAD
mysql -e "SELECT name FROM tabUser WHERE enabled=1"

# GOOD
weg api call frappe.client.get_list --doctype User --filters '{"enabled": 1}'
```

```python
# BAD - raw SQL for simple list
names = frappe.db.sql("SELECT name FROM tabUser WHERE enabled=1", pluck=True)

# GOOD - use pluck for list[str]
names = frappe.get_all("User", filters={"enabled": 1}, pluck="name")
```

### Creating DocTypes - Edit JSON Files

```bash
# BAD - fragile, not version controlled
curl -X POST localhost:8000/api/resource/DocType -d '...'

# GOOD - create JSON files in doctype directory, then:
weg migrate
```

## Quick Reference

| Instead of | Use |
|------------|-----|
| `print()` | `frappe.logger().info()` |
| `frappe.db.commit()` | Let framework handle it |
| `cur_frm` | `frm` |
| `frappe.cache().set()` | `frappe.cache().set_value()` |
| `frappe.db.get_value(Single, Single, field)` | `frappe.db.get_single_value()` |
| `map()/filter()` | List comprehensions |
| Global DB calls | Wrap in functions |
| `ALTER TABLE` | Edit JSON + `weg migrate` |
| `mysql -e "UPDATE..."` | `weg api call frappe.client.set_value` |
| `mysql -e "SELECT..."` | `weg api call frappe.client.get_list` |
| `frappe.db.sql("SELECT x...")` | `frappe.get_all(pluck="x")` |
| `eval()` | `safe_eval()` |
| `in_list(arr, x)` | `arr.includes(x)` |
