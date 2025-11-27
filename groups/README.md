# Groups

Blueprint groups define collections of related blueprints that work together.

## Group JSON Format

```json
{
  "name": "QMS",
  "description": "Quality Management System blueprints",
  "members": [
    {"id": "simple-qms", "required": true},
    {"id": "capa", "required": false}
  ]
}
```

## Scripts

### check-groups.py

Checks for conflicts between entities with the same title across blueprints.

**Usage:**
```bash
# Check all groups
python groups/scripts/check-groups.py

# Check specific group
python groups/scripts/check-groups.py groups/qms.json
```

**Exit codes:**
- `0` - No conflicts found
- `1` - Conflicts detected

### generate-foundation.py

Creates a foundations blueprint with entities common to a threshold fraction of blueprints. Automatically runs conflict checks first.

**Usage:**
```bash
# Generate foundations (default: >50% threshold)
python groups/scripts/generate-foundation.py groups/qms.json

# Custom threshold (e.g., 70%)
python groups/scripts/generate-foundation.py groups/qms.json --threshold 0.7

# Remove common entities from source blueprints
python groups/scripts/generate-foundation.py groups/qms.json --prune

# Preview changes without modifying files
python groups/scripts/generate-foundation.py groups/qms.json --dry-run
```

**Arguments:**
- `group_file` (required) - Path to group JSON file
- `--threshold FLOAT` - Fraction of blueprints entity must appear in (default: 0.5)
- `--prune` - Remove common entities from source blueprints (default: off)
- `--dry-run` - Preview changes without writing files

**Exit codes:**
- `0` - Success
- `1` - Error (conflicts detected or other failure)

