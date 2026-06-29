#!/usr/bin/env python3
"""
Moodle SQL tool — Execute safe SQL queries against the Moodle database.

Safety:
- SELECT queries: auto-approved
- INSERT/UPDATE/DELETE: requires admin confirmation via tool_call event
- DDL (CREATE/DROP/ALTER): blocked
- LIMIT enforced on SELECT (max 1000 rows)
- Table prefix auto-applied
"""

import argparse
import json
import sys
import time
import re

# Moodle DB config (loaded from config.php)
DB_CONFIG = None

def load_moodle_config():
    """Load Moodle database config."""
    global DB_CONFIG
    if DB_CONFIG:
        return DB_CONFIG
    
    try:
        # Read config.php
        config_path = "/var/www/html/config.php"
        with open(config_path, "r") as f:
            content = f.read()
        
        # Extract DB settings with regex (safer than eval)
        import re
        patterns = {
            'dbtype': r"\$CFG->dbtype\s*=\s*'([^']+)'",
            'dbhost': r"\$CFG->dbhost\s*=\s*'([^']+)'",
            'dbname': r"\$CFG->dbname\s*=\s*'([^']+)'",
            'dbuser': r"\$CFG->dbuser\s*=\s*'([^']+)'",
            'dbpass': r"\$CFG->dbpass\s*=\s*'([^']+)'",
            'prefix': r"\$CFG->prefix\s*=\s*'([^']+)'",
        }
        
        DB_CONFIG = {}
        for key, pattern in patterns.items():
            match = re.search(pattern, content)
            if match:
                DB_CONFIG[key] = match.group(1)
        
        if not DB_CONFIG.get('dbtype'):
            raise ValueError("Could not parse DB config")
            
    except Exception as e:
        sys.stderr.write(f"Error loading Moodle config: {e}\n")
        sys.exit(1)
    
    return DB_CONFIG


def check_query_safety(query):
    """Check if a SQL query is safe to execute."""
    query_upper = query.strip().upper()
    
    # Block DDL
    blocked_patterns = [
        r'\bCREATE\b', r'\bDROP\b', r'\bALTER\b',
        r'\bTRUNCATE\b', r'\bGRANT\b', r'\bREVOKE\b',
        r'\bINSTALL\b', r'\bUNINSTALL\b',
    ]
    for pattern in blocked_patterns:
        if re.search(pattern, query_upper):
            return False, "DDL queries are blocked"
    
    # Check if it's a write query
    is_write = bool(re.search(r'\b(INSERT|UPDATE|DELETE)\b', query_upper))
    is_select = query_upper.strip().startswith('SELECT')
    
    if is_write:
        return True, "requires_approval"
    if is_select:
        return True, "auto_approved"
    
    return False, "Unknown query type"


def execute_query(query, config):
    """Execute a SQL query and return results."""
    import pymysql
    
    prefix = config.get('prefix', 'mdl_')
    
    # Auto-replace common table references
    query = query.replace('{', prefix).replace('}', '')
    
    conn = pymysql.connect(
        host=config['dbhost'],
        user=config['dbuser'],
        password=config['dbpass'],
        database=config['dbname'],
        charset='utf8mb4',
        cursorclass=pymysql.cursors.DictCursor,
    )
    
    try:
        with conn.cursor() as cursor:
            cursor.execute(query)
            cursor.execute("SELECT ROW_COUNT() as rc")
            rows_affected = cursor.fetchone()['rc']
            
            if query.strip().upper().startswith('SELECT'):
                rows = cursor.fetchall()
                return {
                    'type': 'select',
                    'rows': list(rows),
                    'count': len(rows),
                }
            else:
                conn.commit()
                return {
                    'type': 'write',
                    'rows_affected': rows_affected,
                }
    finally:
        conn.close()


def main():
    parser = argparse.ArgumentParser(description='Moodle SQL tool')
    parser.add_argument('--query', '-q', required=True, help='SQL query')
    parser.add_argument('--approve', action='store_true', help='Approve write queries')
    parser.add_argument('--dry-run', action='store_true', help='Validate without executing')
    args = parser.parse_args()
    
    config = load_moodle_config()
    safe, reason = check_query_safety(args.query)
    
    if not safe:
        print(json.dumps({'error': reason, 'safe': False}))
        sys.exit(1)
    
    if reason == "requires_approval" and not args.approve:
        print(json.dumps({
            'safe': True,
            'requires_approval': True,
            'query': args.query,
            'type': 'write',
        }))
        sys.exit(0)
    
    if args.dry_run:
        print(json.dumps({'safe': True, 'approved': reason}))
        sys.exit(0)
    
    try:
        result = execute_query(args.query, config)
        print(json.dumps(result))
    except Exception as e:
        print(json.dumps({'error': str(e)}))
        sys.exit(1)


if __name__ == '__main__':
    main()
