#!/usr/bin/env python3
"""
Generate Foundation Script

Creates a foundations blueprint with entities common to a threshold fraction of blueprints.
Automatically runs conflict checks first.

Usage:
    python generate-foundation.py groups/qms.json
    python generate-foundation.py groups/qms.json --threshold 0.7
    python generate-foundation.py groups/qms.json --prune
    python generate-foundation.py groups/qms.json --dry-run
"""

import argparse
import json
import sys
import uuid
import re
from pathlib import Path
from typing import Any
from collections import defaultdict
from copy import deepcopy

# Import check-groups module
import importlib.util
check_groups_spec = importlib.util.spec_from_file_location("check_groups", Path(__file__).parent / "check-groups.py")
check_groups = importlib.util.module_from_spec(check_groups_spec)
check_groups_spec.loader.exec_module(check_groups)

GroupChecker = check_groups.GroupChecker
normalize_for_comparison = check_groups.normalize_for_comparison
normalize_type_for_comparison = check_groups.normalize_type_for_comparison
normalize_template_for_comparison = check_groups.normalize_template_for_comparison


def slugify(text: str) -> str:
    """Convert text to slug format."""
    text = text.lower()
    text = re.sub(r'[^a-z0-9]+', '-', text)
    text = text.strip('-')
    return text


def get_entity_filename(title: str, entity_id: str) -> str:
    """Generate entity filename from title and ID."""
    slug = slugify(title)
    id_prefix = entity_id.split('-')[0] if '-' in entity_id else entity_id[:8]
    return f"{slug}-{id_prefix}.json"


def load_json(path: Path) -> dict:
    """Load JSON file."""
    with open(path, 'r') as f:
        return json.load(f)


def save_json(path: Path, data: dict) -> None:
    """Save JSON file with pretty formatting."""
    with open(path, 'w') as f:
        json.dump(data, f, indent=2)
        f.write('\n')


class FoundationGenerator:
    def __init__(self, base_path: Path, threshold: float, dry_run: bool = False):
        self.base_path = base_path
        self.threshold = threshold
        self.dry_run = dry_run
        self.checker = GroupChecker(base_path)
    
    def load_blueprint(self, blueprint_id: str) -> tuple[dict | None, dict[str, dict]]:
        """Load a blueprint's manifest and all entity data."""
        return self.checker.load_blueprint(blueprint_id)
    
    def get_entity_filename(self, title: str, entity_id: str) -> str:
        """Generate entity filename from title and ID."""
        return self.checker.get_entity_filename(title, entity_id)
    
    def find_common_entities_by_threshold(
        self,
        blueprints_data: dict[str, tuple[dict, dict[str, dict]]],
        group_name: str
    ) -> dict[tuple[str, str], list[tuple[str, str, dict, dict]]]:
        """
        Find entities that appear in >= threshold fraction of blueprints.
        Returns: {(kind, title): [(blueprint_id, entity_id, entity_info, entity_data), ...]}
        """
        type_title_map = self.checker.build_type_title_map(blueprints_data)
        num_blueprints = len([b for b in blueprints_data.values() if b[0] is not None])
        min_occurrences = max(2, int(num_blueprints * self.threshold) + (1 if num_blueprints * self.threshold % 1 > 0 else 0))
        
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
        
        # Filter to entities that meet threshold and are compatible
        common_entities: dict[tuple[str, str], list[tuple[str, str, dict, dict]]] = {}
        
        for key, occurrences in entities_by_key.items():
            if len(occurrences) < min_occurrences:
                continue
            
            kind, title = key
            
            # Verify all occurrences are structurally identical
            first_bp, first_id, first_info, first_data = occurrences[0]
            is_compatible = True
            
            for bp_id, ent_id, ent_info, ent_data in occurrences[1:]:
                if kind == 'TYPE':
                    norm1 = normalize_type_for_comparison(first_data)
                    norm2 = normalize_type_for_comparison(ent_data)
                else:  # TEMPLATE
                    norm1 = normalize_template_for_comparison(first_data, type_title_map)
                    norm2 = normalize_template_for_comparison(ent_data, type_title_map)
                
                if norm1 != norm2:
                    is_compatible = False
                    break
            
            if is_compatible:
                common_entities[key] = occurrences
        
        return common_entities
    
    def create_foundations_blueprint(
        self,
        group_name: str,
        common_entities: dict[tuple[str, str], list[tuple[str, str, dict, dict]]]
    ) -> tuple[str, dict, dict[str, dict]]:
        """
        Create a foundations blueprint with common entities.
        Returns: (blueprint_id, manifest, {entity_id: entity_data})
        """
        foundations_id = f"{slugify(group_name)}-foundations"
        
        # Track type ID mappings for template type references
        old_type_id_to_new: dict[str, str] = {}
        
        foundations_entities = []
        foundations_entity_data: dict[str, dict] = {}
        
        # Process types first (templates depend on them)
        type_entries = [(k, v) for k, v in common_entities.items() if k[0] == 'TYPE']
        template_entries = [(k, v) for k, v in common_entities.items() if k[0] == 'TEMPLATE']
        
        for key, occurrences in type_entries:
            kind, title = key
            # Use the first occurrence as the canonical version
            first_bp, first_id, first_info, first_data = occurrences[0]
            
            # Generate new ID
            new_id = str(uuid.uuid4())
            
            # Track old ID -> new ID for all occurrences
            for bp_id, ent_id, ent_info, ent_data in occurrences:
                old_type_id_to_new[ent_id] = new_id
            
            # Create manifest entry
            manifest_entry = {
                'id': new_id,
                'kind': kind,
                'contentType': first_info.get('contentType'),
                'title': title,
                'icon': first_info.get('icon', 'application'),
            }
            if first_info.get('sourceVersion'):
                manifest_entry['sourceVersion'] = first_info['sourceVersion']
            foundations_entities.append(manifest_entry)
            
            # Create entity data with new ID
            entity_data = deepcopy(first_data)
            entity_data['id'] = new_id
            foundations_entity_data[new_id] = entity_data
        
        for key, occurrences in template_entries:
            kind, title = key
            first_bp, first_id, first_info, first_data = occurrences[0]
            
            new_id = str(uuid.uuid4())
            
            manifest_entry = {
                'id': new_id,
                'kind': kind,
                'contentType': first_info.get('contentType'),
                'title': title,
                'icon': first_info.get('icon', 'application'),
            }
            if first_info.get('sourceVersion'):
                manifest_entry['sourceVersion'] = first_info['sourceVersion']
            foundations_entities.append(manifest_entry)
            
            # Create entity data with new ID and updated type reference
            entity_data = deepcopy(first_data)
            entity_data['id'] = new_id
            
            # Update type reference if the type is also common
            type_ref = entity_data.get('type', {}).get('ref', {})
            old_type_id = type_ref.get('id')
            if old_type_id in old_type_id_to_new:
                entity_data['type']['ref']['id'] = old_type_id_to_new[old_type_id]
            
            foundations_entity_data[new_id] = entity_data
        
        # Create foundations manifest
        foundations_manifest = {
            'id': foundations_id,
            'version': 1,
            'name': f"{group_name} Foundations",
            'description': f"Common types and templates shared across {group_name} blueprints",
            'entities': foundations_entities,
            'tags': []
        }
        
        return foundations_id, foundations_manifest, foundations_entity_data
    
    def remove_common_from_blueprints(
        self,
        common_entities: dict[tuple[str, str], list[tuple[str, str, dict, dict]]],
        blueprints_data: dict[str, tuple[dict, dict[str, dict]]]
    ) -> dict[str, tuple[dict, dict[str, dict], set[str]]]:
        """
        Remove common entities from blueprints.
        Returns: {blueprint_id: (updated_manifest, remaining_entities, removed_entity_ids)}
        """
        # Build set of (blueprint_id, entity_id) to remove
        to_remove: dict[str, set[str]] = defaultdict(set)
        
        for key, occurrences in common_entities.items():
            for bp_id, ent_id, ent_info, ent_data in occurrences:
                to_remove[bp_id].add(ent_id)
        
        updated_blueprints: dict[str, tuple[dict, dict[str, dict], set[str]]] = {}
        
        for blueprint_id, (manifest, entities) in blueprints_data.items():
            if manifest is None:
                continue
            
            removed_ids = to_remove.get(blueprint_id, set())
            
            if not removed_ids:
                updated_blueprints[blueprint_id] = (manifest, entities, set())
                continue
            
            # Create updated manifest
            updated_manifest = deepcopy(manifest)
            updated_manifest['entities'] = [
                e for e in updated_manifest['entities']
                if e['id'] not in removed_ids
            ]
            
            # Filter entities
            remaining_entities = {
                eid: edata for eid, edata in entities.items()
                if eid not in removed_ids
            }
            
            updated_blueprints[blueprint_id] = (updated_manifest, remaining_entities, removed_ids)
        
        return updated_blueprints
    
    def save_blueprint(
        self,
        blueprint_id: str,
        manifest: dict,
        entities: dict[str, dict],
        is_new: bool = False
    ) -> None:
        """Save a blueprint's manifest and entities to disk."""
        blueprint_path = self.base_path / blueprint_id
        
        if is_new:
            blueprint_path.mkdir(exist_ok=True)
        
        # Save manifest
        save_json(blueprint_path / 'manifest.json', manifest)
        
        # Save entities
        for entity_id, entity_data in entities.items():
            title = entity_data.get('title', 'unknown')
            filename = self.get_entity_filename(title, entity_id)
            save_json(blueprint_path / filename, entity_data)
    
    def delete_entity_files(
        self,
        blueprint_id: str,
        removed_ids: set[str],
        original_manifest: dict
    ) -> None:
        """Delete entity files that were removed from a blueprint."""
        blueprint_path = self.base_path / blueprint_id
        
        # Find entity titles for removed IDs
        for entity_info in original_manifest.get('entities', []):
            if entity_info['id'] in removed_ids:
                filename = self.get_entity_filename(entity_info['title'], entity_info['id'])
                file_path = blueprint_path / filename
                if file_path.exists():
                    file_path.unlink()
    
    def generate(self, group_path: Path, prune: bool = False) -> bool:
        """
        Generate foundations blueprint for a group.
        Returns True if successful, False otherwise.
        """
        group_data = load_json(group_path)
        group_name = group_data.get('name', group_path.stem)
        foundations_id = f"{slugify(group_name)}-foundations"
        
        # Step 1: Run conflict checks first
        errors = self.checker.check_group(group_path)
        if errors:
            print(f"Error: {len(errors)} conflict(s) detected:", file=sys.stderr)
            for error in errors:
                print(f"  {error}", file=sys.stderr)
            print("\nResolve conflicts before generating foundations.", file=sys.stderr)
            return False
        
        if self.dry_run:
            print(f"[DRY RUN] Generating foundations for: {group_name}")
        else:
            print(f"Generating foundations for: {group_name}")
        
        # Step 2: Load all member blueprints
        members = group_data.get('members', [])
        blueprints_data: dict[str, tuple[dict, dict[str, dict]]] = {}
        
        for member in members:
            member_id = member.get('id')
            if not member_id:
                continue
            
            manifest, entities = self.load_blueprint(member_id)
            if manifest is None:
                print(f"Warning: Blueprint '{member_id}' not found, skipping", file=sys.stderr)
                continue
            
            blueprints_data[member_id] = (manifest, entities)
        
        if len(blueprints_data) < 2:
            print(f"Error: Need at least 2 blueprints", file=sys.stderr)
            return False
        
        num_blueprints = len(blueprints_data)
        min_occurrences = max(2, int(num_blueprints * self.threshold) + (1 if num_blueprints * self.threshold % 1 > 0 else 0))
        
        # Step 3: Find common entities by threshold
        common_entities = self.find_common_entities_by_threshold(blueprints_data, group_name)
        
        if not common_entities:
            print(f"No entities found common to >= {self.threshold} ({min_occurrences}/{num_blueprints}) of blueprints")
            return True
        
        # Step 4: Create foundations blueprint
        foundations_id, foundations_manifest, foundations_entities = self.create_foundations_blueprint(
            group_name, common_entities
        )
        
        if self.dry_run:
            print(f"Would create: {foundations_id} ({len(foundations_entities)} entities)")
        else:
            self.save_blueprint(foundations_id, foundations_manifest, foundations_entities, is_new=True)
            print(f"Created: {foundations_id} ({len(foundations_entities)} entities)")
        
        # Step 5: Prune if requested
        if prune:
            updated_blueprints = self.remove_common_from_blueprints(common_entities, blueprints_data)
            pruned_count = 0
            
            for blueprint_id, (updated_manifest, remaining_entities, removed_ids) in updated_blueprints.items():
                if removed_ids:
                    pruned_count += len(removed_ids)
                    original_manifest = blueprints_data[blueprint_id][0]
                    
                    if not self.dry_run:
                        self.delete_entity_files(blueprint_id, removed_ids, original_manifest)
                        self.save_blueprint(blueprint_id, updated_manifest, remaining_entities)
            
            if self.dry_run:
                print(f"Would prune {pruned_count} entities from source blueprints")
            else:
                print(f"Pruned {pruned_count} entities from source blueprints")
        
        # Step 6: Update group file
        if not self.dry_run:
            updated_group = deepcopy(group_data)
            foundations_member = {'id': foundations_id, 'required': True}
            
            # Check if foundations already exists
            existing_foundations = [m for m in updated_group['members'] if m.get('id') == foundations_id]
            if not existing_foundations:
                updated_group['members'].insert(0, foundations_member)
                save_json(group_path, updated_group)
                print(f"Updated group file")
        
        print("✓ Complete")
        return True


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description='Generate foundations blueprint with entities common to threshold fraction of blueprints'
    )
    parser.add_argument(
        'group_file',
        help='Path to group JSON file (e.g., groups/qms.json)'
    )
    parser.add_argument(
        '--threshold',
        type=float,
        default=0.5,
        help='Fraction of blueprints entity must appear in (default: 0.5, i.e., >50%%)'
    )
    parser.add_argument(
        '--prune',
        action='store_true',
        help='Remove common entities from source blueprints (default: off)'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Preview changes without modifying any files'
    )
    args = parser.parse_args()
    
    # Validate threshold
    if not 0 < args.threshold <= 1.0:
        print(f"Error: threshold must be between 0 and 1.0, got {args.threshold}", file=sys.stderr)
        sys.exit(1)
    
    # Get the base path (repo root)
    script_path = Path(__file__).resolve()
    base_path = script_path.parent.parent.parent
    
    # Resolve group file path
    group_path = Path(args.group_file)
    if not group_path.is_absolute():
        group_path = base_path / group_path
    
    if not group_path.exists():
        print(f"Error: Group file not found: {group_path}", file=sys.stderr)
        sys.exit(1)
    
    generator = FoundationGenerator(base_path, args.threshold, dry_run=args.dry_run)
    success = generator.generate(group_path, prune=args.prune)
    
    sys.exit(0 if success else 1)


if __name__ == '__main__':
    main()

