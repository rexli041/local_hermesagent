#!/usr/bin/env python3
"""
Moodle Admin tool — Query course, user, and enrolment information.

Read-only operations:
- Course listing and details
- User information lookup
- Enrolment data
- Category hierarchy
"""

import argparse
import json
import sys
import re


def load_moodle_config():
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


def get_course_info(config, course_id=None, shortname=None):
    """Get course information."""
    import pymysql
    p = config.get('prefix', 'mdl_')
    
    conn = pymysql.connect(
        host=config['dbhost'], user=config['dbuser'],
        password=config['dbpass'], database=config['dbname'],
        cursorclass=pymysql.cursors.DictCursor,
    )
    
    try:
        with conn.cursor() as cursor:
            where = "1=1"
            if course_id:
                where += f" AND c.id = {int(course_id)}"
            if shortname:
                where += f" AND c.shortname LIKE '%{shortname}%'"
            
            cursor.execute(
                f"SELECT c.id, c.shortname, c.fullname, c.idnumber, c.category, c.visible, "
                f"c.format, c.startdate, c.enddate, c.summary, c.timemodified "
                f"FROM {p}course c WHERE {where} LIMIT 20"
            )
            return cursor.fetchall()
    finally:
        conn.close()


def get_user_info(config, username=None, email=None, id=None):
    """Get user information."""
    import pymysql
    p = config.get('prefix', 'mdl_')
    
    conn = pymysql.connect(
        host=config['dbhost'], user=config['dbuser'],
        password=config['dbpass'], database=config['dbname'],
        cursorclass=pymysql.cursors.DictCursor,
    )
    
    try:
        with conn.cursor() as cursor:
            where = "1=1"
            if username:
                where += f" AND (u.username LIKE '%{username}%' OR u.firstname LIKE '%{username}%' OR u.lastname LIKE '%{username}%')"
            if email:
                where += f" AND u.email LIKE '%{email}%'"
            if id:
                where += f" AND u.id = {int(id)}"
            
            cursor.execute(
                f"SELECT u.id, u.username, u.firstname, u.lastname, u.email, u.auth, "
                f"u.suspended, u.timecreated, u.lastaccess "
                f"FROM {p}user u WHERE {where} AND u.deleted = 0 LIMIT 20"
            )
            return cursor.fetchall()
    finally:
        conn.close()


def get_enrolments(config, course_id=None):
    """Get enrolment information for a course."""
    import pymysql
    p = config.get('prefix', 'mdl_')
    
    conn = pymysql.connect(
        host=config['dbhost'], user=config['dbuser'],
        password=config['dbpass'], database=config['dbname'],
        cursorclass=pymysql.cursors.DictCursor,
    )
    
    try:
        with conn.cursor() as cursor:
            where = "1=1"
            if course_id:
                where += f" AND e.courseid = {int(course_id)}"
            
            cursor.execute(
                f"SELECT u.id as user_id, u.firstname, u.lastname, u.email, "
                f"e.roleid, e.status, e.enrol, e.timestart, e.timeend "
                f"FROM {p}enrol e "
                f"JOIN {p}user_enrolments ue ON ue.enrolid = e.id "
                f"JOIN {p}user u ON u.id = ue.userid "
                f"WHERE {where} AND e.status = 0 LIMIT 100"
            )
            return cursor.fetchall()
    finally:
        conn.close()


def get_categories(config):
    """Get category hierarchy."""
    import pymysql
    p = config.get('prefix', 'mdl_')
    
    conn = pymysql.connect(
        host=config['dbhost'], user=config['dbuser'],
        password=config['dbpass'], database=config['dbname'],
        cursorclass=pymysql.cursors.DictCursor,
    )
    
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                f"SELECT id, name, parent, idnumber, description, visible "
                f"FROM {p}course_categories ORDER BY sortorder"
            )
            return cursor.fetchall()
    finally:
        conn.close()


def main():
    parser = argparse.ArgumentParser(description='Moodle Admin tool')
    subparsers = parser.add_subparsers(dest='action')
    
    course_parser = subparsers.add_parser('courses', help='List courses')
    course_parser.add_argument('--id', help='Course ID')
    course_parser.add_argument('--shortname', help='Course shortname')
    
    user_parser = subparsers.add_parser('users', help='Search users')
    user_parser.add_argument('--username', help='Username')
    user_parser.add_argument('--email', help='Email')
    user_parser.add_argument('--id', help='User ID')
    
    enrol_parser = subparsers.add_parser('enrolments', help='Course enrolments')
    enrol_parser.add_argument('--courseid', help='Course ID')
    
    subparsers.add_parser('categories', help='Course categories')
    
    args = parser.parse_args()
    config = load_moodle_config()
    
    if args.action == 'courses':
        result = get_course_info(config, args.id, args.shortname)
        print(json.dumps({'courses': result, 'count': len(result)}))
    elif args.action == 'users':
        result = get_user_info(config, args.username, args.email, args.id)
        print(json.dumps({'users': result, 'count': len(result)}))
    elif args.action == 'enrolments':
        result = get_enrolments(config, args.courseid)
        print(json.dumps({'enrolments': result, 'count': len(result)}))
    elif args.action == 'categories':
        result = get_categories(config)
        print(json.dumps({'categories': result, 'count': len(result)}))
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == '__main__':
    main()
