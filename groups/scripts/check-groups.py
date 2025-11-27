#!/usr/bin/env python3
"""
Check Groups Script

Checks for conflicts between entities with the same title across blueprints in groups.
Only performs conflict detection - does not modify any files.

Usage:
    python check-groups.py                    # Check all groups
    python check-groups.py groups/qms.json    # Check specific group
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Any
from collections import defaultdict


def normalize_for_comparison(obj: Any, exclude_keys: set | None = None) -> Any:
    """
    Normalize an object for comparison by:
    - Removing IDs, metadata, and other non-structural fields
    - Sorting dictionary keys
    - Converting to a comparable form
    """
    if exclude_keys is None:
        exclude_keys = {
            'id', 'metadata', 'schemaVersion', 'status', 'version', 
            'previousVersion', 'sourceInfo', 'sourceVersion', 'tagIds'
        }
    
    if isinstance(obj, dict):
        result = {}
        for k, v in sorted(obj.items()):
            if k in exclude_keys:
                continue
            result[k] = normalize_for_comparison(v, exclude_keys)
        return result
    elif isinstance(obj, list):
        return [normalize_for_comparison(item, exclude_keys) for item in obj]
    else:
        return obj


def normalize_type_for_comparison(entity_data: dict) -> dict:
    """
    Normalize a TYPE entity for comparison.
    Compare: title, contentType, fields structure, instanceConfig (specific fields), templateConfig
    """
    normalized = {
        'title': entity_data.get('title'),
        'contentType': entity_data.get('contentType'),
        'kind': entity_data.get('kind'),
    }
    
    # Compare fields structure (excluding IDs within fields)
    fields = entity_data.get('fields', {})
    normalized_fields = {}
    for field_name, field_data in fields.items():
        normalized_field = {
            'type': field_data.get('type'),
            'dataType': field_data.get('dataType'),
            'config': normalize_for_comparison(field_data.get('config', {}), exclude_keys={'id'}),
        }
        normalized_fields[field_name] = normalized_field
    normalized['fields'] = normalized_fields
    
    # Compare key instanceConfig settings
    instance_config = entity_data.get('instanceConfig', {})
    normalized['instanceConfig'] = {
        'enforceUniqueTitles': instance_config.get('enforceUniqueTitles'),
        'strictMode': instance_config.get('strictMode'),
        'canChooseActiveVersion': instance_config.get('canChooseActiveVersion'),
    }
    
    # Compare templateConfig structure
    template_config = entity_data.get('templateConfig')
    if template_config:
        normalized['templateConfig'] = normalize_for_comparison(
            template_config, 
            exclude_keys={'id'}
        )
    
    return normalized


def normalize_template_for_comparison(entity_data: dict, type_title_map: dict) -> dict:
    """
    Normalize a TEMPLATE entity for comparison.
    Compare: title, type (by title, not ID), fields structure, content structure, instanceConfig
    """
    normalized = {
        'title': entity_data.get('title'),
        'kind': entity_data.get('kind'),
    }
    
    # Get type title instead of ID for comparison
    type_ref = entity_data.get('type', {}).get('ref', {})
    type_id = type_ref.get('id')
    type_title = type_title_map.get(type_id, type_id)
    normalized['type_title'] = type_title
    
    # Compare fields structure (excluding IDs)
    fields = entity_data.get('fields', {})
    normalized_fields = {}
    for field_name, field_data in fields.items():
        normalized_field = {
            'type': field_data.get('type'),
            'dataType': field_data.get('dataType'),
            'config': normalize_for_comparison(field_data.get('config', {}), exclude_keys={'id'}),
        }
        normalized_fields[field_name] = normalized_field
    normalized['fields'] = normalized_fields
    
    # Compare content structure (normalize but keep structure)
    content = entity_data.get('content', {})
    normalized['content'] = {
        'type': content.get('type'),
        # For content value, normalize but this will include structural differences
        'value_structure': normalize_for_comparison(
            content.get('value', {}),
            exclude_keys={'id', 'fieldId'}  # Exclude IDs but keep structure
        )
    }
    
    # Compare instanceConfig
    instance_config = entity_data.get('instanceConfig', {})
    normalized['instanceConfig'] = normalize_for_comparison(
        instance_config,
        exclude_keys={'id'}
    )
    
    return normalized


def get_diff_description(entity1: dict, entity2: dict, kind: str) -> str:
    """Get a human-readable description of differences between two entities."""
    diffs = []
    
    # Check contentType
    if entity1.get('contentType') != entity2.get('contentType'):
        diffs.append(f"contentType: {entity1.get('contentType')} vs {entity2.get('contentType')}")
    
    # Check fields
    fields1 = set(entity1.get('fields', {}).keys())
    fields2 = set(entity2.get('fields', {}).keys())
    
    only_in_1 = fields1 - fields2
    only_in_2 = fields2 - fields1
    
    if only_in_1:
        diffs.append(f"fields only in first: {only_in_1}")
    if only_in_2:
        diffs.append(f"fields only in second: {only_in_2}")
    
    # Check common fields for differences
    for field_name in fields1 & fields2:
        f1 = entity1['fields'][field_name]
        f2 = entity2['fields'][field_name]
        if f1.get('type') != f2.get('type'):
            diffs.append(f"field '{field_name}' type: {f1.get('type')} vs {f2.get('type')}")
        if f1.get('dataType') != f2.get('dataType'):
            diffs.append(f"field '{field_name}' dataType: {f1.get('dataType')} vs {f2.get('dataType')}")
        # Check field config differences
        config1 = normalize_for_comparison(f1.get('config', {}), exclude_keys={'id'})
        config2 = normalize_for_comparison(f2.get('config', {}), exclude_keys={'id'})
        if config1 != config2:
            diffs.append(f"field '{field_name}' config differs")
    
    # Check instanceConfig differences
    ic1 = entity1.get('instanceConfig', {})
    ic2 = entity2.get('instanceConfig', {})
    
    if ic1.get('enforceUniqueTitles') != ic2.get('enforceUniqueTitles'):
        diffs.append(f"enforceUniqueTitles: {ic1.get('enforceUniqueTitles')} vs {ic2.get('enforceUniqueTitles')}")
    if ic1.get('strictMode') != ic2.get('strictMode'):
        diffs.append(f"strictMode: {ic1.get('strictMode')} vs {ic2.get('strictMode')}")
    if ic1.get('canChooseActiveVersion') != ic2.get('canChooseActiveVersion'):
        diffs.append(f"canChooseActiveVersion: {ic1.get('canChooseActiveVersion')} vs {ic2.get('canChooseActiveVersion')}")
    
    # Check templateConfig differences for types
    if kind == 'TYPE':
        tc1 = entity1.get('templateConfig')
        tc2 = entity2.get('templateConfig')
        if (tc1 is not None) != (tc2 is not None):
            diffs.append(f"templateConfig: {'present' if tc1 else 'absent'} vs {'present' if tc2 else 'absent'}")
        elif tc1 and tc2:
            norm_tc1 = normalize_for_comparison(tc1, exclude_keys={'id'})
            norm_tc2 = normalize_for_comparison(tc2, exclude_keys={'id'})
            if norm_tc1 != norm_tc2:
                diffs.append("templateConfig differs")
    
    # Check createFromTemplate differences
    cft1 = ic1.get('createFromTemplate', {})
    cft2 = ic2.get('createFromTemplate', {})
    if cft1.get('onlyCreateFromActiveVersion') != cft2.get('onlyCreateFromActiveVersion'):
        diffs.append(f"onlyCreateFromActiveVersion: {cft1.get('onlyCreateFromActiveVersion')} vs {cft2.get('onlyCreateFromActiveVersion')}")
    
    return "; ".join(diffs) if diffs else "structures differ (check full entity files)"


class GroupChecker:
    def __init__(self, base_path: Path):
        self.base_path = base_path
        self.errors: list[str] = []
    
    def load_json(self, path: Path) -> dict:
        """Load JSON file."""
        with open(path, 'r') as f:
            return json.load(f)
    
    def get_entity_filename(self, title: str, entity_id: str) -> str:
        """Generate entity filename from title and ID."""
        import re
        slug = re.sub(r'[^a-z0-9]+', '-', title.lower()).strip('-')
        id_prefix = entity_id.split('-')[0] if '-' in entity_id else entity_id[:8]
        return f"{slug}-{id_prefix}.json"
    
    def load_blueprint(self, blueprint_id: str) -> tuple[dict | None, dict[str, dict]]:
        """
        Load a blueprint's manifest and all entity data.
        Returns (manifest, {entity_id: entity_data})
        """
        blueprint_path = self.base_path / blueprint_id
        manifest_path = blueprint_path / 'manifest.json'
        
        if not manifest_path.exists():
            return None, {}
        
        manifest = self.load_json(manifest_path)
        entities = {}
        
        for entity_info in manifest.get('entities', []):
            entity_id = entity_info['id']
            entity_title = entity_info['title']
            entity_filename = self.get_entity_filename(entity_title, entity_id)
            entity_path = blueprint_path / entity_filename
            
            if entity_path.exists():
                entities[entity_id] = self.load_json(entity_path)
            else:
                # Try to find by ID prefix
                for file in blueprint_path.glob(f'*-{entity_id.split("-")[0]}*.json'):
                    if file.name != 'manifest.json':
                        entities[entity_id] = self.load_json(file)
                        break
        
        return manifest, entities
    
    def build_type_title_map(self, blueprints_data: dict[str, tuple[dict, dict[str, dict]]]) -> dict[str, str]:
        """Build a map of type_id -> type_title across all blueprints."""
        type_title_map = {}
        for blueprint_id, (manifest, entities) in blueprints_data.items():
            if manifest is None:
                continue
            for entity_info in manifest.get('entities', []):
                if entity_info.get('kind') == 'TYPE':
                    type_title_map[entity_info['id']] = entity_info['title']
        return type_title_map
    
    def check_conflicts(
        self, 
        blueprints_data: dict[str, tuple[dict, dict[str, dict]]],
        group_name: str
    ) -> list[str]:
        """
        Check for conflicts between entities with the same title.
        Returns list of conflict error messages.
        """
        type_title_map = self.build_type_title_map(blueprints_data)
        errors = []
        
        # Group entities by (kind, title)
        entities_by_key: dict[tuple[str, str], list[tuple[str, str, dict, dict]]] = defaultdict(list)
        
        for blueprint_id, (manifest, entities) in blueprints_data.items():
            if manifest is None:
                continue
            
            for entity_info in manifest.get('entities', []):
                entity_id = entity_info['id']
                kind = entity_info.get('kind')
                title = entity_info.get('title')
                
                if kind not in ('TYPE', 'TEMPLATE'):
                    continue
                
                entity_data = entities.get(entity_id)
                if entity_data is None:
                    continue
                
                key = (kind, title)
                entities_by_key[key].append((blueprint_id, entity_id, entity_info, entity_data))
        
        # Check for conflicts (entities with same title but different structure)
        for key, occurrences in entities_by_key.items():
            if len(occurrences) < 2:
                continue
            
            kind, title = key
            
            # Check if all occurrences are structurally identical
            first_bp, first_id, first_info, first_data = occurrences[0]
            
            for bp_id, ent_id, ent_info, ent_data in occurrences[1:]:
                if kind == 'TYPE':
                    norm1 = normalize_type_for_comparison(first_data)
                    norm2 = normalize_type_for_comparison(ent_data)
                else:  # TEMPLATE
                    norm1 = normalize_template_for_comparison(first_data, type_title_map)
                    norm2 = normalize_template_for_comparison(ent_data, type_title_map)
                
                if norm1 != norm2:
                    diff_desc = get_diff_description(first_data, ent_data, kind)
                    errors.append(
                        f"[{group_name}] Conflict in {kind} '{title}': "
                        f"Blueprint '{first_bp}' vs '{bp_id}' - {diff_desc}"
                    )
        
        return errors
    
    def check_group(self, group_path: Path) -> list[str]:
        """
        Check a single group file for conflicts.
        Returns list of error messages.
        """
        group_data = self.load_json(group_path)
        group_name = group_data.get('name', group_path.stem)
        
        # Load all member blueprints
        members = group_data.get('members', [])
        blueprints_data: dict[str, tuple[dict, dict[str, dict]]] = {}
        
        for member in members:
            member_id = member.get('id')
            if not member_id:
                continue
            
            manifest, entities = self.load_blueprint(member_id)
            if manifest is None:
                continue
            
            blueprints_data[member_id] = (manifest, entities)
        
        if len(blueprints_data) < 2:
            return []
        
        return self.check_conflicts(blueprints_data, group_name)
    
    def check_all_groups(self) -> bool:
        """
        Check all groups in the groups/ directory.
        Returns True if no conflicts, False if conflicts found.
        """
        groups_path = self.base_path / 'groups'
        
        if not groups_path.exists():
            print(f"Error: groups directory not found at {groups_path}", file=sys.stderr)
            return False
        
        group_files = list(groups_path.glob('*.json'))
        
        if not group_files:
            print("No group files found in groups/", file=sys.stderr)
            return False
        
        all_errors = []
        
        for group_file in group_files:
            errors = self.check_group(group_file)
            all_errors.extend(errors)
        
        if all_errors:
            print(f"\n{len(all_errors)} conflict(s) detected:", file=sys.stderr)
            for error in all_errors:
                print(f"  {error}", file=sys.stderr)
            return False
        
        print("No conflicts found.")
        return True


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description='Check for conflicts between entities with the same title across blueprints in groups'
    )
    parser.add_argument(
        'group_file',
        nargs='?',
        help='Optional path to specific group JSON file (e.g., groups/qms.json). If omitted, checks all groups.'
    )
    args = parser.parse_args()
    
    # Get the base path (repo root)
    script_path = Path(__file__).resolve()
    # Script is in groups/scripts/, so base_path is repo root
    base_path = script_path.parent.parent.parent
    
    checker = GroupChecker(base_path)
    
    if args.group_file:
        # Check specific group
        group_path = Path(args.group_file)
        if not group_path.is_absolute():
            group_path = base_path / group_path
        
        if not group_path.exists():
            print(f"Error: Group file not found: {group_path}", file=sys.stderr)
            sys.exit(1)
        
        errors = checker.check_group(group_path)
        if errors:
            print(f"\n{len(errors)} conflict(s) detected:", file=sys.stderr)
            for error in errors:
                print(f"  {error}", file=sys.stderr)
            sys.exit(1)
        else:
            print("No conflicts found.")
            sys.exit(0)
    else:
        # Check all groups
        success = checker.check_all_groups()
        sys.exit(0 if success else 1)


if __name__ == '__main__':
    main()

