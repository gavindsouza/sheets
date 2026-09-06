---
description: Review Frappe/Python code for antipatterns, best practices, and translation compliance.
---

## User Input

```text
$ARGUMENTS
```

Interpret arguments as file paths or glob patterns to review. If empty, review staged changes.

## Goal

Analyze Frappe Framework code for common antipatterns and produce an actionable report.

## Critical Rules to Check

1. **Multitenancy**: Global variables with `frappe.db.*`, `frappe.get_all`, `frappe.cache` at module level
2. **Uncommitted changes**: `self.<attr> = ...` in hooks without `db_set()` or `save()`
3. **Child table mutation**: Modifying `self.<table>` while iterating
4. **Cache methods**: Using `.set()/.get()` instead of `.set_value()/.get_value()`
5. **Proxy reassignment**: `frappe.db = ...` instead of `frappe.local.db = ...`
6. **Single DocType**: Using `get_value` instead of `get_single_value`
7. **Realtime broadcast**: Missing `user=`, `doctype=`, or `room=` in `publish_realtime`
8. **Invalid hooks**: Using `after_save` (not valid)
9. **Query builder**: Missing `order=` keyword in `orderby()`
10. **Monkey patching**: Modifying imported modules at runtime
11. **eval()**: Use `safe_eval()` instead
12. **Duplicate dict keys**: Same key assigned twice in dict literal

## Warnings to Check

- `print()` in doctypes (use logger/msgprint)
- `frappe.db.commit()` (usually wrong)
- `map()/filter()` (use comprehensions)
- `debug=True` left in code
- `cur_frm` in JavaScript (deprecated)
- `in_list()` wrapper (use `.includes()`)
- `frappe.get_doc(dict(...))` (use kwargs directly)
- `def process(args):` (use explicit parameters)

## The Frappe Way Violations

- **Direct SQL for schema**: `ALTER TABLE`, `CREATE TABLE` - use JSON + migrate
- **Direct SQL for data**: `UPDATE`, `INSERT`, `DELETE` - use `weg api` or `weg py`
- **Direct SQL for queries**: `SELECT` - use `frappe.get_all` or `weg api`
- **curl to create DocTypes**: Use JSON files in doctype directory
- **Direct file writes**: Use `frappe.get_doc({"doctype": "File", ...})`

## Translation Checks

- `frappe.throw()`/`msgprint()`/`show_alert()` without `_()`
- Format before translate (`_('x %s' % y)`)
- Empty translations (`_('')`)
- Variable-only translations (`_('{0}')`)
- Leading/trailing whitespace in translations
- Concatenating translations (`_('a') + _('b')`)
- Template literals in JS (`__(`...`)`)
- JavaScript: missing `__()` on user text
- Button text without `__()`
- Report labels without `_()`

## Execution

1. Get files to review from args or `git diff --cached`
2. Read each file and apply rules
3. Output report with file:line references
4. Offer to apply fixes

## Report Format

```markdown
## Frappe Code Review

**Files**: N | **Issues**: X critical, Y warnings, Z translation

| File | Line | Severity | Issue | Fix |
|------|------|----------|-------|-----|
```

## Context

$ARGUMENTS
