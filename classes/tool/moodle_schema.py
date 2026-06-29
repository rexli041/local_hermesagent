#!/usr/bin/env python3
"""
Moodle Schema tool — Explore the Moodle database schema.

Features:
- List all tables
- Get table structure (columns, types, keys)
- Find tables by name pattern
- Get foreign key relationships
"""

import argparse
import json
import sys
import re


def load_moodle_config():
    """Load Moodle database config."""
    config_path = "/var/www/html/config.php"
    with open(config_path, "r") as f:
        content = f.read()
    
    patterns = {
        'dbtype': r"\$CFG->dbtype\s*=\s*'([^']+)'",
        'dbhost': r"\$CFG->dbhost\s*=\s*'([^']+)'",
        'dbname': r"\$CFG->dbname\s*=\s*'([^']+)'",
        'dbuser': r"\$CFG->dbuser\s*=\s*'([^']+)'",
        'dbpass': r"\$CFG->dbpass\s*=\s*'([^']+)'",
        'prefix': r"\$CFG->prefix\s*=\s*'([^']+)'",
    }
    
    config = {}
    for key, pattern in patterns.items():
        match = re.search(pattern, content)
        if match:
            config[key] = match.group(1)
    
    return config


def list_tables(config, pattern=None):
    """List all tables, optionally filtered by pattern."""
    import pymysql
    prefix = config.get('prefix', 'mdl_')
    
    conn = pymysql.connect(
        host=config['dbhost'],
        user=config['dbuser'],
        password=config['dbpass'],
        database=config['dbname'],
    )
    
    try:
        with conn.cursor() as cursor:
            cursor.execute("SHOW TABLES")
            tables = [row[0] for row in cursor.fetchall()]
        
        if pattern:
            tables = [t for t in tables if pattern.lower() in t.lower()]
        
        return tables
    finally:
        conn.close()


def table_info(config, table_name):
    """Get detailed info about a table."""
    import pymysql
    prefix = config.get('prefix', 'mdl_')
    
    # Ensure table name has prefix
    if not table_name.startswith(prefix):
        table_name = prefix + table_name
    
    conn = pymysql.connect(
        host=config['dbhost'],
        user=config['dbuser'],
        password=config['dbpass'],
        database=config['dbname'],
    )
    
    try:
        with conn.cursor() as cursor:
            # Get columns
            cursor.execute(f"DESCRIBE `{table_name}`")
            columns = cursor.fetchall()
            
            # Get index info
            cursor.execute(f"SHOW INDEX FROM `{table_name}`")
            indexes = cursor.fetchall()
            
            # Get row count
            cursor.execute(f"SELECT COUNT(*) as cnt FROM `{table_name}`")
            row_count = cursor.fetchone()[0]
            
            # Get table comment
            cursor.execute(
                "SELECT TABLE_COMMENT FROM INFORMATION_SCHEMA.TABLES "
                f"WHERE TABLE_NAME = '{table_name}' AND TABLE_SCHEMA = '{config['dbname']}'"
            )
            comment_row = cursor.fetchone()
            comment = comment_row[0] if comment_row else ''
        
        col_info = []
        for col in columns:
            col_info.append({
                'Field': col[0],
                'Type': col[1],
                'Null': col[2],
                'Key': col[3],
                'Default': col[4],
                'Extra': col[5],
            })
        
        return {
            'table': table_name,
            'comment': comment,
            'row_count': row_count,
            'columns': col_info,
            'indexes': len(indexes),
        }
    finally:
        conn.close()


def find_table(config, search_term):
    """Find tables matching a search term (name or comment)."""
    import pymysql
    
    conn = pymysql.connect(
        host=config['dbhost'],
        user=config['dbuser'],
        password=config['dbpass'],
        database=config['dbname'],
    )
    
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT TABLE_NAME, TABLE_COMMENT FROM INFORMATION_SCHEMA.TABLES "
                f"WHERE TABLE_SCHEMA = '{config['dbname']}' "
                f"AND (TABLE_NAME LIKE '%{search_term}%' OR TABLE_COMMENT LIKE '%{search_term}%')"
            )
            return [{'name': r[0], 'comment': r[1]} for r in cursor.fetchall()]
    finally:
        conn.close()


def main():
    parser = argparse.ArgumentParser(description='Moodle Schema tool')
    subparsers = parser.add_subparsers(dest='action')
    
    # List tables
    list_parser = subparsers.add_parser('list', help='List all tables')
    list_parser.add_argument('--pattern', help='Filter by pattern')
    
    # Table info
    info_parser = subparsers.add_parser('info', help='Get table info')
    info_parser.add_argument('table', help='Table name')
    
    # Find
    find_parser = subparsers.add_parser('find', help='Find tables by search')
    find_parser.add_argument('term', help='Search term')
    
    args = parser.parse_args()
    config = load_moodle_config()
    
    if args.action == 'list':
        result = list_tables(config, args.pattern)
        print(json.dumps({'tables': result, 'count': len(result)}))
    elif args.action == 'info':
        result = table_info(config, args.table)
        print(json.dumps(result))
    elif args.action == 'find':
        result = find_table(config, args.term)
        print(json.dumps({'tables': result, 'count': len(result)}))
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == '__main__':
    main()
